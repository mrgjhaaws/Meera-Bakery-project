"""
repositories/order_repository.py
==================================
Direct SQL queries for the orders and order_items tables.

Rules (consistent with Phases 2–3 repositories)
------------------------------------------------
- All SQL is parameterised — no string interpolation of user input.
- Cursors always use dictionary=True so rows are returned as dicts.
- DECIMAL columns are converted to float before returning (monetary and
  percentage fields) so Pydantic receives plain Python floats.
- Raw MySQLError is caught here, logged internally, and re-raised as
  DatabaseError so the service layer never sees a MySQL-specific exception.
- NotFoundError is raised here when a primary-key lookup returns no row.
- This repository never calls conn.commit() — that responsibility belongs
  entirely to the service layer so that multi-statement transactions are
  always controlled at one level.

Join strategy
-------------
get_by_id:
    orders LEFT JOIN order_items → products so a single query returns the
    full order with all line items and denormalised product names.
    A LEFT JOIN is used so an order with zero items (edge case) still returns.

get_all / get_all_for_customer:
    orders LEFT JOIN a COUNT subquery for item_count so the summary list
    does not fetch every line item row.

Normalisation
-------------
_normalise_order     : DECIMAL→float for all financial columns.
_normalise_item      : DECIMAL→float for item financial columns.

Public interface
----------------
    get_by_id(conn, order_id)
        -> dict  (order header + items list)

    get_all(conn, *, customer_id, status, page, page_size)
        -> (total: int, rows: list[dict])

    get_all_for_customer(conn, customer_id, *, status, page, page_size)
        -> (total: int, rows: list[dict])

    create(conn, order_data: dict, items_data: list[dict])
        -> int  (new order_id)
        NOTE: caller must call conn.commit() after this returns.

    update_status(conn, order_id: int, new_status: str)
        -> None
        NOTE: caller must call conn.commit() after this returns.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import DatabaseError, NotFoundError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column lists
# ---------------------------------------------------------------------------

# All financial + metadata columns on the orders table.
_ORDER_COLS = """
    o.order_id,
    o.customer_id,
    o.address_id,
    o.shipping_address_snapshot,
    o.status,
    o.subtotal,
    o.discount_amount,
    o.discount_percent,
    o.taxable_amount,
    o.tax_percent,
    o.tax_amount,
    o.total_amount,
    o.notes,
    o.ordered_at,
    o.created_at,
    o.updated_at
"""

# All financial + metadata columns on order_items, plus denormalised product name.
_ITEM_COLS = """
    oi.order_item_id,
    oi.order_id,
    oi.product_id,
    p.name              AS product_name,
    oi.quantity,
    oi.unit_price_at_order,
    oi.item_discount_amount,
    oi.item_discount_percent,
    oi.line_total,
    oi.created_at,
    oi.updated_at
"""

# Monetary columns on the orders table that must be converted DECIMAL→float.
_ORDER_DECIMAL_COLS = (
    "subtotal",
    "discount_amount",
    "discount_percent",
    "taxable_amount",
    "tax_percent",
    "tax_amount",
    "total_amount",
)

# Monetary/percentage columns on order_items.
_ITEM_DECIMAL_COLS = (
    "unit_price_at_order",
    "item_discount_amount",
    "item_discount_percent",
    "line_total",
)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_order(row: dict) -> dict:
    """Convert DECIMAL order columns to float in-place."""
    for col in _ORDER_DECIMAL_COLS:
        if col in row and row[col] is not None:
            row[col] = float(row[col])
    return row


def _normalise_item(row: dict) -> dict:
    """Convert DECIMAL order_item columns to float in-place."""
    for col in _ITEM_DECIMAL_COLS:
        if col in row and row[col] is not None:
            row[col] = float(row[col])
    return row


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_by_id(
    conn: PooledMySQLConnection,
    order_id: int,
) -> dict:
    """Return a single order with all its line items.

    The order header and every line item are fetched in two queries on the
    same cursor (one for the header, one for items) rather than a wide JOIN
    that would duplicate the order header row once per item.

    Parameters
    ----------
    conn     : Pooled connection from get_db() dependency.
    order_id : PK value to look up.

    Returns
    -------
    dict — order header with key 'items' containing a list of item dicts.

    Raises
    ------
    NotFoundError : No row found for order_id.
    DatabaseError : Unexpected MySQL error.
    """
    order_sql = f"""
        SELECT {_ORDER_COLS}
        FROM orders o
        WHERE o.order_id = %s
    """

    items_sql = f"""
        SELECT {_ITEM_COLS}
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        WHERE oi.order_id = %s
        ORDER BY oi.order_item_id ASC
    """

    try:
        cursor = conn.cursor(dictionary=True)

        # Fetch order header
        cursor.execute(order_sql, (order_id,))
        order_row: dict | None = cursor.fetchone()

        if order_row is None:
            cursor.close()
            raise NotFoundError("order", order_id)

        _normalise_order(order_row)

        # Fetch line items
        cursor.execute(items_sql, (order_id,))
        item_rows: List[dict] = cursor.fetchall()
        cursor.close()

        for item in item_rows:
            _normalise_item(item)

        order_row["items"] = item_rows
        return order_row

    except NotFoundError:
        raise
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"order_repository.get_by_id id={order_id}: {exc}"
        ) from exc


def get_all(
    conn: PooledMySQLConnection,
    *,
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[dict]]:
    """Return a paginated list of order summaries with optional filters.

    Each summary row includes item_count (number of distinct line items)
    computed via a subquery — no full item fetch on list queries.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    customer_id : When provided, restrict to this customer's orders.
    status      : When provided, restrict to orders with this status value.
    page        : 1-based page number.
    page_size   : Rows per page (max enforced by the service layer).

    Returns
    -------
    (total, rows)
        total — total matching row count
        rows  — order summary dicts for the requested page, each containing:
                order_id, customer_id, status, total_amount,
                item_count, ordered_at
    """
    offset = (page - 1) * page_size

    # Build WHERE clause dynamically — all params bound, never interpolated
    conditions: list[str] = []
    params: list = []

    if customer_id is not None:
        conditions.append("o.customer_id = %s")
        params.append(customer_id)
    if status is not None:
        conditions.append("o.status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM orders o
        {where}
    """

    # item_count is a correlated subquery — avoids a GROUP BY on the outer query
    # and keeps the summary row clean for Pydantic without extra aggregation.
    data_sql = f"""
        SELECT
            o.order_id,
            o.customer_id,
            o.status,
            o.total_amount,
            (
                SELECT COUNT(*)
                FROM order_items oi
                WHERE oi.order_id = o.order_id
            )                   AS item_count,
            o.ordered_at
        FROM orders o
        {where}
        ORDER BY o.ordered_at DESC, o.order_id DESC
        LIMIT %s OFFSET %s
    """

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(count_sql, params)
        total: int = (cursor.fetchone() or {}).get("total", 0)

        cursor.execute(data_sql, params + [page_size, offset])
        rows: List[dict] = cursor.fetchall()
        cursor.close()

        for row in rows:
            if "total_amount" in row and row["total_amount"] is not None:
                row["total_amount"] = float(row["total_amount"])
            # item_count is INT — no conversion needed

        return total, rows

    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"order_repository.get_all "
                f"customer_id={customer_id} status={status}: {exc}"
            )
        ) from exc


def get_all_for_customer(
    conn: PooledMySQLConnection,
    customer_id: int,
    *,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[dict]]:
    """Convenience wrapper — all orders for a single customer.

    Verifies the customer exists before querying orders, consistent with
    address_repository.get_all_for_customer() in Phase 3.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    customer_id : FK — must exist in customers.
    status      : Optional status filter.
    page        : 1-based page number.
    page_size   : Rows per page (max enforced by the service layer).

    Returns
    -------
    (total, rows)

    Raises
    ------
    NotFoundError : customer_id does not exist in the customers table.
    DatabaseError : Unexpected MySQL error.
    """
    verify_sql = "SELECT customer_id FROM customers WHERE customer_id = %s"

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(verify_sql, (customer_id,))
        if cursor.fetchone() is None:
            cursor.close()
            raise NotFoundError("customer", customer_id)
        cursor.close()
    except NotFoundError:
        raise
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"order_repository.get_all_for_customer "
                f"verify customer_id={customer_id}: {exc}"
            )
        ) from exc

    return get_all(
        conn,
        customer_id=customer_id,
        status=status,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def create(
    conn: PooledMySQLConnection,
    order_data: dict,
    items_data: List[dict],
) -> int:
    """Insert one order header row and all its line items.

    IMPORTANT — transaction contract
    ---------------------------------
    This function does NOT call conn.commit().  The caller (order_service)
    is responsible for:
        1. Calling this function.
        2. Decrementing inventory (inventory_repository.decrement_stock).
        3. Calling conn.commit() if both steps succeed, or conn.rollback()
           on any exception.
    This keeps the transaction boundary at a single point in the service layer.

    Parameters
    ----------
    conn       : Pooled connection — autocommit must be False (default).
    order_data : Dict matching orders columns (all financial totals pre-calculated
                 by order_service using utils.financial):
                    customer_id, address_id, shipping_address_snapshot, status,
                    subtotal, discount_amount, discount_percent, taxable_amount,
                    tax_percent, tax_amount, total_amount, notes
    items_data : List of dicts, one per line item:
                    order_id (will be filled in after header INSERT),
                    product_id, quantity, unit_price_at_order,
                    item_discount_amount, item_discount_percent, line_total

    Returns
    -------
    int — the new order_id (lastrowid from the header INSERT).

    Raises
    ------
    DatabaseError : Any MySQLError during INSERT.  Caller must rollback.
    """
    order_insert_sql = """
        INSERT INTO orders (
            customer_id,
            address_id,
            shipping_address_snapshot,
            status,
            subtotal,
            discount_amount,
            discount_percent,
            taxable_amount,
            tax_percent,
            tax_amount,
            total_amount,
            notes
        ) VALUES (
            %(customer_id)s,
            %(address_id)s,
            %(shipping_address_snapshot)s,
            %(status)s,
            %(subtotal)s,
            %(discount_amount)s,
            %(discount_percent)s,
            %(taxable_amount)s,
            %(tax_percent)s,
            %(tax_amount)s,
            %(total_amount)s,
            %(notes)s
        )
    """

    item_insert_sql = """
        INSERT INTO order_items (
            order_id,
            product_id,
            quantity,
            unit_price_at_order,
            item_discount_amount,
            item_discount_percent,
            line_total
        ) VALUES (
            %(order_id)s,
            %(product_id)s,
            %(quantity)s,
            %(unit_price_at_order)s,
            %(item_discount_amount)s,
            %(item_discount_percent)s,
            %(line_total)s
        )
    """

    try:
        cursor = conn.cursor(dictionary=True)

        # Step 1: insert order header
        cursor.execute(order_insert_sql, order_data)
        new_order_id: int = cursor.lastrowid

        # Step 2: insert every line item, stamping with the new order_id
        for item in items_data:
            item["order_id"] = new_order_id
            cursor.execute(item_insert_sql, item)

        cursor.close()

        logger.debug(
            "order_repository.create: inserted order_id=%d with %d item(s)",
            new_order_id, len(items_data),
        )
        return new_order_id

    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"order_repository.create: {exc}"
        ) from exc


def update_status(
    conn: PooledMySQLConnection,
    order_id: int,
    new_status: str,
) -> None:
    """Update the status column of a single order row.

    IMPORTANT — transaction contract
    ---------------------------------
    This function does NOT call conn.commit().  The caller (order_service)
    is responsible for:
        - Validating the transition via utils.financial.validate_status_transition().
        - Adjusting inventory if transitioning to 'confirmed' or 'cancelled'.
        - Calling conn.commit() on success or conn.rollback() on failure.

    Parameters
    ----------
    conn       : Pooled connection — autocommit must be False.
    order_id   : PK of the order to update.
    new_status : One of the six ENUM values defined in 06_create_orders.sql.

    Raises
    ------
    NotFoundError : No row found for order_id (UPDATE affected 0 rows).
    DatabaseError : Unexpected MySQL error.
    """
    sql = """
        UPDATE orders
        SET    status = %s
        WHERE  order_id = %s
    """

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (new_status, order_id))
        rows_affected: int = cursor.rowcount
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"order_repository.update_status "
                f"order_id={order_id} status={new_status}: {exc}"
            )
        ) from exc

    if rows_affected == 0:
        raise NotFoundError("order", order_id)

    logger.debug(
        "order_repository.update_status: order_id=%d → %s",
        order_id, new_status,
    )
