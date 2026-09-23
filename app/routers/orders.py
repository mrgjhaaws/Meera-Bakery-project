"""
routers/orders.py
==================
FastAPI router for the orders resource.

Endpoints (Phase 4)
--------------------
POST /api/v1/orders
    Create a new order. Validates customer/address/products, prices every
    line item, computes order totals, and persists everything in one
    transaction. Does not touch inventory (see order_service docstring).

GET /api/v1/orders
    Paginated list of order summaries. Filter by customer_id and/or status.

GET /api/v1/orders/{order_id}
    Full order detail, including line items.

PATCH /api/v1/orders/{order_id}/status
    Transition an order to a new status. Applies inventory decrement on
    confirm, increment on cancel-after-confirm, per utils.financial rules.

Router rules (consistent with Phases 2-3)
-------------------------------------------
- Handlers are thin: validate path/query params, call the service, return.
- No SQL or business logic lives here.
- Integer path parameters are typed so FastAPI rejects non-integers with 422.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status as http_status
from mysql.connector.pooling import PooledMySQLConnection

from dependencies import get_db
from models.order import (
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatus,
    OrderStatusUpdate,
)
from services import order_service

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "",
    response_model=OrderResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create a new order",
    description=(
        "Creates a pending order. Validates that the customer, address, and "
        "every product exist and are active, snapshots current unit prices, "
        "and computes subtotal/discount/tax/total using the mandated "
        "calculation sequence. Inventory is not touched at this stage — "
        "stock is checked and decremented only when the order is confirmed."
    ),
)
def create_order(
    payload: OrderCreate,
    conn: PooledMySQLConnection = Depends(get_db),
) -> OrderResponse:
    return order_service.create_order(conn, payload)


@router.get(
    "",
    response_model=OrderListResponse,
    summary="List orders",
    description=(
        "Returns a paginated list of order summaries (no line items). "
        "Filter by `customer_id` and/or `status`."
    ),
)
def list_orders(
    customer_id: Optional[int] = Query(
        default=None, ge=1, description="Filter orders by customer ID"
    ),
    status: Optional[OrderStatus] = Query(
        default=None, description="Filter orders by lifecycle status"
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> OrderListResponse:
    return order_service.list_orders(
        conn,
        customer_id=customer_id,
        status=status.value if status is not None else None,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get order by ID",
    description=(
        "Returns a single order with all its line items. "
        "Returns 404 if the order does not exist."
    ),
)
def get_order(
    order_id: int,
    conn: PooledMySQLConnection = Depends(get_db),
) -> OrderResponse:
    return order_service.get_order(conn, order_id)


@router.patch(
    "/{order_id}/status",
    response_model=OrderResponse,
    summary="Update order status",
    description=(
        "Transitions an order to a new lifecycle status. Valid transitions: "
        "pending -> confirmed -> preparing -> shipped -> delivered, and any "
        "pre-delivered stage -> cancelled. Confirming decrements inventory "
        "(fails with 409 if stock is insufficient); cancelling a confirmed/"
        "preparing/shipped order reverses the decrement."
    ),
)
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    conn: PooledMySQLConnection = Depends(get_db),
) -> OrderResponse:
    return order_service.update_order_status(conn, order_id, payload.status)
