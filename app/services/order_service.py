"""
services/order_service.py
==========================
Business logic for the orders resource — the most complex service in the
Meera Bakery API, since it owns the full financial calculation pipeline and
the transactional inventory side-effects of order status transitions.

Responsibilities
----------------
- Validate that the customer, address, and every product referenced in a
  create-order request actually exist (and are active).
- Read current unit_price for each product and snapshot it onto the order
  (unit_price_at_order is immutable from this point on).
- Run every line item and the order header through utils.financial to get
  the mandated calculation sequence: subtotal -> discount -> taxable_amount
  -> tax_amount -> total_amount.
- Persist the order header + items in a single transaction.
- Enforce order status transitions via utils.financial.validate_status_transition.
- Apply inventory side effects (decrement on confirm, increment on cancel)
  in the SAME transaction as the status update.
- Fire a best-effort SNS SMS notification to the customer after order
  creation and after each status change (see utils/notifications.py).
  These run AFTER conn.commit() and never raise — a notification failure
  must never affect the already-successful order.

Inventory timing (important)
-----------------------------
Stock is NOT checked or touched when an order is created — a pending order
is allowed even if stock is currently low (it is effectively a backorder
until the bakery confirms it). Stock is only checked and decremented when
the order transitions to 'confirmed'; InsufficientStockError there blocks
the confirmation. This matches the schema comments in
04_create_inventory.sql and 06_create_orders.sql (IR-4, IR-5).

Transaction boundary
---------------------
The FastAPI dependency get_db() (see dependencies.py / db/connection.py)
wraps every request in get_db_connection(), which automatically rolls back
the connection if any exception propagates out of the route handler. This
service therefore does NOT need its own try/except/rollback — it only calls
conn.commit() after every write step in a given operation has succeeded.
If any step raises, the exception propagates naturally and the dependency's
context manager rolls back the whole transaction before the response is built.

The service never touches raw SQL directly — it delegates to
order_repository, inventory_repository, customer_repository,
address_repository, and product_repository.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from mysql.connector.pooling import PooledMySQLConnection

from models.order import (
    OrderCreate,
    OrderItemResponse,
    OrderListResponse,
    OrderResponse,
    OrderStatus,
    OrderSummary,
)
from repositories import (
    address_repository,
    customer_repository,
    inventory_repository,
    order_repository,
    product_repository,
)
from utils import notifications
from utils.exceptions import BusinessRuleError
from utils.financial import (
    INVENTORY_DECREMENT_ON,
    INVENTORY_INCREMENT_ON,
    NO_INVENTORY_REVERSAL_FROM,
    calculate_line_total,
    calculate_order_totals,
    validate_status_transition,
)

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100


# =============================================================================
# Internal helpers
# =============================================================================

def _format_address_snapshot(address: dict) -> str:
    """Build the immutable shipping_address_snapshot text from an address row.

    Format matches the example used throughout the schema docs:
        "42 MG Road, Flat 3B, Bengaluru, Karnataka 560001, India"
    """
    parts = [address["address_line1"]]
    if address.get("address_line2"):
        parts.append(address["address_line2"])
    parts.append(address["city"])
    parts.append(f"{address['state']} {address['postal_code']}")
    parts.append(address["country"])
    return ", ".join(parts)


def _row_to_order_response(row: dict) -> OrderResponse:
    """Convert an order_repository.get_by_id() dict into an OrderResponse."""
    items_data = row.pop("items")
    items = [OrderItemResponse(**item) for item in items_data]
    return OrderResponse(**row, items=items)


def _validate_pagination(page: int, page_size: int) -> int:
    """Shared pagination validation, consistent with Phases 2-3 services."""
    if page < 1:
        raise BusinessRuleError(
            "INVALID_PAGINATION", f"page must be >= 1, got {page}.", detail={"page": page}
        )
    if page_size < 1:
        raise BusinessRuleError(
            "INVALID_PAGINATION",
            f"page_size must be >= 1, got {page_size}.",
            detail={"page_size": page_size},
        )
    return min(page_size, MAX_PAGE_SIZE)


# =============================================================================
# Create order
# =============================================================================

def create_order(
    conn: PooledMySQLConnection,
    order_data: OrderCreate,
) -> OrderResponse:
    """Validate, price, and persist a new order.

    Parameters
    ----------
    conn       : DB connection from get_db() dependency.
    order_data : Validated OrderCreate request body.

    Returns
    -------
    OrderResponse — the newly created order, fully hydrated with items.

    Raises
    ------
    NotFoundError     : customer_id, address_id, or any product_id does not exist.
    BusinessRuleError : address does not belong to the customer, a referenced
                        customer/product/address is inactive, a duplicate
                        product_id appears in items, or a discount mechanism
                        is invalid (mutually exclusive flat + percent).
    DatabaseError      : Propagated from any repository call.
    """
    # --- 1. Validate customer ------------------------------------------------
    customer = customer_repository.get_by_id(conn, order_data.customer_id)
    if not customer["is_active"]:
        raise BusinessRuleError(
            "CUSTOMER_INACTIVE",
            f"Customer {order_data.customer_id} is not active and cannot place orders.",
            detail={"customer_id": order_data.customer_id},
        )

    # --- 2. Validate address belongs to the customer --------------------------
    address = address_repository.get_by_id(conn, order_data.address_id)
    if address["customer_id"] != order_data.customer_id:
        raise BusinessRuleError(
            "ADDRESS_CUSTOMER_MISMATCH",
            f"Address {order_data.address_id} does not belong to customer "
            f"{order_data.customer_id}.",
            detail={
                "address_id": order_data.address_id,
                "customer_id": order_data.customer_id,
            },
        )
    if not address["is_active"]:
        raise BusinessRuleError(
            "ADDRESS_INACTIVE",
            f"Address {order_data.address_id} has been removed and cannot be "
            f"used for a new order.",
            detail={"address_id": order_data.address_id},
        )

    # --- 3. Reject duplicate products in the same order ------------------------
    seen_product_ids: set[int] = set()
    for item in order_data.items:
        if item.product_id in seen_product_ids:
            raise BusinessRuleError(
                "DUPLICATE_PRODUCT_IN_ORDER",
                f"Product {item.product_id} appears more than once in this order. "
                f"Combine quantities into a single line item instead.",
                detail={"product_id": item.product_id},
            )
        seen_product_ids.add(item.product_id)

    # --- 4. Price every line item ----------------------------------------------
    items_data: list[dict] = []
    line_totals: list[Decimal] = []

    for item in order_data.items:
        product = product_repository.get_by_id(conn, item.product_id)
        if not product["is_active"]:
            raise BusinessRuleError(
                "PRODUCT_INACTIVE",
                f"Product '{product['name']}' (id={item.product_id}) is no "
                f"longer available.",
                detail={"product_id": item.product_id},
            )

        unit_price = Decimal(str(product["unit_price"]))
        line = calculate_line_total(
            unit_price=unit_price,
            quantity=item.quantity,
            item_discount_amount=item.item_discount_amount,
            item_discount_percent=item.item_discount_percent,
        )

        items_data.append({
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_price_at_order": unit_price,
            "item_discount_amount": line.item_discount_amount,
            "item_discount_percent": line.item_discount_percent,
            "line_total": line.line_total,
        })
        line_totals.append(line.line_total)

    # --- 5. Order-level financial totals ---------------------------------------
    totals = calculate_order_totals(
        line_totals=line_totals,
        discount_amount=order_data.discount_amount,
        discount_percent=order_data.discount_percent,
        tax_percent=order_data.tax_percent,
    )

    # --- 6. Persist ---------------------------------------------------------
    order_row = {
        "customer_id": order_data.customer_id,
        "address_id": order_data.address_id,
        "shipping_address_snapshot": _format_address_snapshot(address),
        "status": OrderStatus.pending.value,
        "subtotal": totals.subtotal,
        "discount_amount": totals.discount_amount,
        "discount_percent": totals.discount_percent,
        "taxable_amount": totals.taxable_amount,
        "tax_percent": totals.tax_percent,
        "tax_amount": totals.tax_amount,
        "total_amount": totals.total_amount,
        "notes": order_data.notes,
    }

    new_order_id = order_repository.create(conn, order_row, items_data)
    conn.commit()

    logger.info(
        "create_order: order_id=%d customer_id=%d total_amount=%s",
        new_order_id, order_data.customer_id, totals.total_amount,
    )

    # Best-effort — never raises, and runs after the commit so a notification
    # failure can never roll back an already-successful order.
    notifications.notify_order_placed(customer.get("phone"), new_order_id, totals.total_amount)

    return get_order(conn, new_order_id)


# =============================================================================
# Read operations
# =============================================================================

def get_order(conn: PooledMySQLConnection, order_id: int) -> OrderResponse:
    """Return a single order with all its line items.

    Raises
    ------
    NotFoundError : Propagated from repository.
    DatabaseError : Propagated from repository.
    """
    row = order_repository.get_by_id(conn, order_id)
    return _row_to_order_response(row)


def list_orders(
    conn: PooledMySQLConnection,
    *,
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> OrderListResponse:
    """Return a paginated list of order summaries with optional filters.

    Raises
    ------
    BusinessRuleError : Invalid pagination params.
    DatabaseError      : Propagated from repository.
    """
    effective_page_size = _validate_pagination(page, page_size)

    total, rows = order_repository.get_all(
        conn,
        customer_id=customer_id,
        status=status,
        page=page,
        page_size=effective_page_size,
    )
    items = [OrderSummary(**row) for row in rows]

    filters: dict = {}
    if customer_id is not None:
        filters["customer_id"] = customer_id
    if status is not None:
        filters["status"] = status

    return OrderListResponse(
        total=total,
        page=page,
        page_size=effective_page_size,
        filters=filters,
        items=items,
    )


def list_orders_for_customer(
    conn: PooledMySQLConnection,
    customer_id: int,
    *,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> OrderListResponse:
    """Convenience wrapper — all orders for a single customer.

    Raises
    ------
    NotFoundError     : customer_id does not exist.
    BusinessRuleError : Invalid pagination params.
    DatabaseError      : Propagated from repository.
    """
    effective_page_size = _validate_pagination(page, page_size)

    total, rows = order_repository.get_all_for_customer(
        conn,
        customer_id,
        status=status,
        page=page,
        page_size=effective_page_size,
    )
    items = [OrderSummary(**row) for row in rows]

    filters: dict = {"customer_id": customer_id}
    if status is not None:
        filters["status"] = status

    return OrderListResponse(
        total=total,
        page=page,
        page_size=effective_page_size,
        filters=filters,
        items=items,
    )


# =============================================================================
# Status transition (with inventory side effects)
# =============================================================================

def update_order_status(
    conn: PooledMySQLConnection,
    order_id: int,
    new_status: OrderStatus,
) -> OrderResponse:
    """Transition an order to a new status, applying inventory side effects.

    Parameters
    ----------
    conn       : DB connection from get_db() dependency.
    order_id   : PK of the order to update.
    new_status : Requested new status.

    Returns
    -------
    OrderResponse — the order after the transition, fully hydrated.

    Raises
    ------
    NotFoundError           : order_id does not exist.
    BusinessRuleError       : The requested transition is not permitted.
    InsufficientStockError  : Confirming would push stock below zero for
                               one or more line items.
    DatabaseError            : Propagated from any repository call.
    """
    current_order = order_repository.get_by_id(conn, order_id)
    current_status: str = current_order["status"]
    requested: str = (
        new_status.value if isinstance(new_status, OrderStatus) else new_status
    )

    validate_status_transition(current_status, requested)

    if requested in INVENTORY_DECREMENT_ON:
        for item in current_order["items"]:
            inventory_repository.decrement_stock(
                conn,
                item["product_id"],
                item["product_name"],
                item["quantity"],
            )
    elif requested in INVENTORY_INCREMENT_ON and current_status not in NO_INVENTORY_REVERSAL_FROM:
        for item in current_order["items"]:
            inventory_repository.increment_stock(
                conn,
                item["product_id"],
                item["quantity"],
            )

    order_repository.update_status(conn, order_id, requested)
    conn.commit()

    logger.info(
        "update_order_status: order_id=%d %s -> %s",
        order_id, current_status, requested,
    )

    # Best-effort — must never affect the already-committed status change,
    # so any failure here (including in the customer lookup itself) is
    # swallowed rather than propagated.
    try:
        customer = customer_repository.get_by_id(conn, current_order["customer_id"])
        notifications.notify_order_status_changed(customer.get("phone"), order_id, requested)
    except Exception:
        logger.warning(
            "Could not send status-change notification for order %d", order_id, exc_info=True
        )

    return get_order(conn, order_id)
