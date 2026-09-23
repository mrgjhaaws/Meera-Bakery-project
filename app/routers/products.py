"""
routers/products.py
====================
FastAPI router for the products resource.

Endpoints (Phase 2 — read-only)
---------------------------------
GET /api/v1/products
    List products with optional category_id filter, active_only flag, and pagination.

GET /api/v1/products/{product_id}
    Fetch a single product by primary key.
    Pass ?include_inventory=true to embed current stock info.

Router rules
------------
- Handlers are thin: validate path/query params, call the service, return.
- No SQL or business logic lives here.
- Path parameter {product_id} is typed int — FastAPI rejects non-integers with 422.
- Response models are declared for OpenAPI docs and response validation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from mysql.connector.pooling import PooledMySQLConnection

from dependencies import get_db
from models.product import ProductListResponse, ProductResponse
from services import product_service

router = APIRouter(prefix="/products", tags=["Products"])


@router.get(
    "",
    response_model=ProductListResponse,
    summary="List products",
    description=(
        "Returns a paginated list of bakery products. "
        "Filter by category using `category_id`. "
        "By default only active products are returned. "
        "Pass `active_only=false` to include soft-deleted products."
    ),
)
def list_products(
    category_id: Optional[int] = Query(
        default=None,
        ge=1,
        description="Filter products by category ID",
    ),
    active_only: bool = Query(
        default=True,
        description="Return only active products (is_active = 1)",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> ProductListResponse:
    return product_service.list_products(
        conn,
        category_id=category_id,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get product by ID",
    description=(
        "Returns a single product record. "
        "Pass `include_inventory=true` to embed current stock levels. "
        "Returns 404 if the product does not exist."
    ),
)
def get_product(
    product_id: int,
    include_inventory: bool = Query(
        default=False,
        description="Embed current inventory stock info in the response",
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> ProductResponse:
    return product_service.get_product(
        conn,
        product_id,
        include_inventory=include_inventory,
    )
