"""
routers/customers.py
=====================
FastAPI router for the customers and addresses resources.

Endpoints (Phase 3 — read-only)
---------------------------------
GET /api/v1/customers
    Paginated list of customers with optional active_only filter.

GET /api/v1/customers/{customer_id}
    Single customer by primary key.

GET /api/v1/customers/{customer_id}/addresses
    Paginated list of addresses belonging to a customer.
    Returns 404 if the customer does not exist.

GET /api/v1/customers/{customer_id}/orders
    Paginated order history for a customer (Phase 4).
    Returns 404 if the customer does not exist.

GET /api/v1/addresses/{address_id}
    Single address by primary key.

Router design
-------------
Both /customers and /addresses prefixes are registered in this file
because they are closely related (addresses belong to customers) and
Phase 3 only introduces read-only operations on both.

Router rules (consistent with Phase 2)
---------------------------------------
- Handlers are thin: receive validated params, call service, return model.
- No SQL or business logic lives here.
- Integer path parameters are typed so FastAPI rejects non-integers with 422.
- Response models are declared for OpenAPI docs and automatic validation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from mysql.connector.pooling import PooledMySQLConnection

from dependencies import get_db
from models.address import AddressListResponse, AddressResponse
from models.customer import CustomerListResponse, CustomerResponse
from models.order import OrderListResponse, OrderStatus
from services import address_service, customer_service, order_service

# Two routers — one per URL prefix — both exported from this module.
# main.py mounts them individually so each gets the correct prefix.
customers_router = APIRouter(prefix="/customers", tags=["Customers"])
addresses_router = APIRouter(prefix="/addresses", tags=["Addresses"])

# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@customers_router.get(
    "",
    response_model=CustomerListResponse,
    summary="List customers",
    description=(
        "Returns a paginated list of registered customers. "
        "By default only active customers are returned. "
        "Pass `active_only=false` to include soft-deleted accounts."
    ),
)
def list_customers(
    active_only: bool = Query(
        default=True,
        description="Return only active customers (is_active = 1)",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> CustomerListResponse:
    return customer_service.list_customers(
        conn,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )


@customers_router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Get customer by ID",
    description="Returns a single customer record. Returns 404 if not found.",
)
def get_customer(
    customer_id: int,
    conn: PooledMySQLConnection = Depends(get_db),
) -> CustomerResponse:
    return customer_service.get_customer(conn, customer_id)


@customers_router.get(
    "/{customer_id}/addresses",
    response_model=AddressListResponse,
    summary="List addresses for a customer",
    description=(
        "Returns a paginated list of delivery addresses for the given customer. "
        "The default address is always returned first. "
        "Returns 404 if the customer does not exist."
    ),
)
def list_addresses(
    customer_id: int,
    active_only: bool = Query(
        default=True,
        description="Return only active addresses (is_active = 1)",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> AddressListResponse:
    return address_service.list_addresses(
        conn,
        customer_id,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )


@customers_router.get(
    "/{customer_id}/orders",
    response_model=OrderListResponse,
    summary="List orders for a customer",
    description=(
        "Returns a paginated order history for the given customer "
        "(summaries only — use GET /orders/{order_id} for line items). "
        "Filter by `status`. Returns 404 if the customer does not exist."
    ),
)
def list_customer_orders(
    customer_id: int,
    status: Optional[OrderStatus] = Query(
        default=None, description="Filter orders by lifecycle status"
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> OrderListResponse:
    return order_service.list_orders_for_customer(
        conn,
        customer_id,
        status=status.value if status is not None else None,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Addresses (standalone lookup — no customer context required)
# ---------------------------------------------------------------------------

@addresses_router.get(
    "/{address_id}",
    response_model=AddressResponse,
    summary="Get address by ID",
    description=(
        "Returns a single address record by its primary key. "
        "Returns 404 if not found."
    ),
)
def get_address(
    address_id: int,
    conn: PooledMySQLConnection = Depends(get_db),
) -> AddressResponse:
    return address_service.get_address(conn, address_id)
