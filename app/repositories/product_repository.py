"""
repositories/product_repository.py
====================================
Direct SQL queries for the products table.

Join strategy
-------------
Every query JOINs products → categories to return category_name inline,
avoiding a second round-trip in the service layer.

The inventory JOIN is optional — only performed when include_inventory=True
is requested, keeping the default list query lightweight.

Rules
-----
- All SQL is parameterised — no string interpolation of user input.
- Cursors always use dictionary=True.
- DECIMAL unit_price is converted to float before returning so Pydantic
  receives a plain Python float.
- is_active TINYINT is normalised to bool.
- Raw MySQLError is caught here and re-raised as DatabaseError.

Public interface
----------------
    get_all(conn, *, category_id, active_only, page, page_size)
        -> (total: int, rows: list[dict])
    get_by_id(conn, product_id, *, include_inventory)
        -> dict
    get_by_category(conn, category_id, *, active_only, page, page_size)
        -> (total: int, rows: list[dict])
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import DatabaseError, NotFoundError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared SELECT fragment — product columns + denormalised category_name
# ---------------------------------------------------------------------------
_PRODUCT_SELECT = """
    SELECT
        p.product_id,
        p.category_id,
        c.name          AS category_name,
        p.name,
        p.description,
        p.unit_price,
        p.is_active,
        p.created_at,
        p.updated_at
    FROM products p
    JOIN categories c ON c.category_id = p.category_id
"""

_INVENTORY_SELECT = """
    SELECT
        p.product_id,
        p.category_id,
        c.name              AS category_name,
        p.name,
        p.description,
        p.unit_price,
        p.is_active,
        p.created_at,
        p.updated_at,
        i.quantity_on_hand,
        i.reorder_level,
        i.reorder_quantity,
        i.last_restocked_at
    FROM products p
    JOIN categories c ON c.category_id = p.category_id
    LEFT JOIN inventory i ON i.product_id = p.product_id
"""


def _normalise(row: dict) -> dict:
    """Convert MySQL types to Python-native types in-place."""
    row["is_active"] = bool(row["is_active"])
    # DECIMAL(10,2) → float for JSON serialisation
    if "unit_price" in row and row["unit_price"] is not None:
        row["unit_price"] = float(row["unit_price"])
    return row


def get_all(
    conn: PooledMySQLConnection,
    *,
    category_id: Optional[int] = None,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[dict]]:
    """Return a paginated list of products with optional filters.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    category_id : When provided, filter to this category only.
    active_only : When True (default), exclude is_active = 0 products.
                  Also excludes products whose category is soft-deleted.
    page        : 1-based page number.
    page_size   : Rows per page (max enforced by service layer).

    Returns
    -------
    (total, rows)
    """
    offset = (page - 1) * page_size

    # Build WHERE clause dynamically — parameterised, never interpolated
    conditions: list[str] = []
    params: list = []

    if active_only:
        conditions.append("p.is_active = 1")
        conditions.append("c.is_active = 1")
    if category_id is not None:
        conditions.append("p.category_id = %s")
        params.append(category_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM products p
        JOIN categories c ON c.category_id = p.category_id
        {where}
    """
    data_sql = f"""
        SELECT
            p.product_id,
            p.category_id,
            c.name  AS category_name,
            p.name,
            p.unit_price,
            p.is_active
        FROM products p
        JOIN categories c ON c.category_id = p.category_id
        {where}
        ORDER BY c.name ASC, p.name ASC
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
            _normalise(row)

        return total, rows

    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"product_repository.get_all cat={category_id}: {exc}"
        ) from exc


def get_by_id(
    conn: PooledMySQLConnection,
    product_id: int,
    *,
    include_inventory: bool = False,
) -> dict:
    """Return a single product by primary key.

    Parameters
    ----------
    conn              : Pooled connection.
    product_id        : PK to look up.
    include_inventory : When True, LEFT JOIN inventory and embed stock cols.

    Returns
    -------
    dict — product row, with optional inventory sub-dict under key 'inventory'.

    Raises
    ------
    NotFoundError  : No active or inactive product found for product_id.
    DatabaseError  : Unexpected MySQL error.
    """
    select = _INVENTORY_SELECT if include_inventory else _PRODUCT_SELECT
    sql = f"{select} WHERE p.product_id = %s"

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (product_id,))
        row: dict | None = cursor.fetchone()
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"product_repository.get_by_id id={product_id}: {exc}"
        ) from exc

    if row is None:
        raise NotFoundError("product", product_id)

    _normalise(row)

    # Extract inventory columns into a nested dict (or None if no inventory row)
    if include_inventory:
        if row.get("quantity_on_hand") is not None:
            row["inventory"] = {
                "quantity_on_hand": row.pop("quantity_on_hand"),
                "reorder_level":    row.pop("reorder_level"),
                "reorder_quantity": row.pop("reorder_quantity"),
                "last_restocked_at": row.pop("last_restocked_at"),
            }
        else:
            # LEFT JOIN returned NULLs — product exists but has no inventory row
            for col in ("quantity_on_hand", "reorder_level",
                        "reorder_quantity", "last_restocked_at"):
                row.pop(col, None)
            row["inventory"] = None
    else:
        row["inventory"] = None

    return row


def get_by_category(
    conn: PooledMySQLConnection,
    category_id: int,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[dict]]:
    """Convenience wrapper — all active products in a single category.

    Delegates to get_all() with category_id filter applied.
    """
    return get_all(
        conn,
        category_id=category_id,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )
