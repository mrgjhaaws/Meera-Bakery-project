"""
routers/categories.py
======================
FastAPI router for the categories resource.

Endpoints (Phase 2 — read-only)
--------------------------------
GET /api/v1/categories
    List all categories with optional active_only filter and pagination.

GET /api/v1/categories/{category_id}
    Fetch a single category by primary key.

GET /api/v1/categories/{category_id}/products
    List all products belonging to a category (delegates to product_service).

Router rules
------------
- Handlers are thin: validate path/query params, call the service, return.
- No SQL or business logic lives here.
- All path parameters are typed (int) so FastAPI rejects non-integer IDs
  with a 422 Unprocessable Entity before the handler is called.
- Response models are declared on each endpoint for automatic OpenAPI docs
  and response validation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from mysql.connector.pooling import PooledMySQLConnection

from dependencies import get_db
from models.category import CategoryListResponse, CategoryResponse
from models.product import ProductListResponse
from services import category_service, product_service

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get(
    "",
    response_model=CategoryListResponse,
    summary="List categories",
    description=(
        "Returns a paginated list of product categories. "
        "By default only active categories are returned. "
        "Pass `active_only=false` to include soft-deleted categories."
    ),
)
def list_categories(
    active_only: bool = Query(
        default=True,
        description="Return only active categories (is_active = 1)",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> CategoryListResponse:
    return category_service.list_categories(
        conn,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Get category by ID",
    description="Returns a single category record. Returns 404 if not found.",
)
def get_category(
    category_id: int,
    conn: PooledMySQLConnection = Depends(get_db),
) -> CategoryResponse:
    return category_service.get_category(conn, category_id)


@router.get(
    "/{category_id}/products",
    response_model=ProductListResponse,
    summary="List products in a category",
    description=(
        "Returns a paginated list of products belonging to the specified category. "
        "Returns 404 if the category does not exist."
    ),
)
def list_products_by_category(
    category_id: int,
    active_only: bool = Query(
        default=True,
        description="Return only active products",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    conn: PooledMySQLConnection = Depends(get_db),
) -> ProductListResponse:
    return product_service.list_products_by_category(
        conn,
        category_id,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )
