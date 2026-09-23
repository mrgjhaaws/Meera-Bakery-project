"""
services/product_service.py
============================
Business logic for the products resource.

Responsibilities
----------------
- Enforce pagination limits (max page_size = 100).
- Validate query parameters (page, page_size, category_id).
- Delegate all DB access to product_repository.
- Assemble Pydantic response models from raw repository dicts.
- Keep inventory embedding logic here so the router stays thin.

The service never touches SQL directly.  It receives a PooledMySQLConnection
from the FastAPI dependency get_db() via the router handler.
"""

from __future__ import annotations

import logging
from typing import Optional

from mysql.connector.pooling import PooledMySQLConnection

from models.product import (
    ProductInventoryInfo,
    ProductListResponse,
    ProductResponse,
)
from repositories import product_repository
from utils.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100


def list_products(
    conn: PooledMySQLConnection,
    *,
    category_id: Optional[int] = None,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> ProductListResponse:
    """Return a paginated list of products with optional filters.

    Parameters
    ----------
    conn        : DB connection from get_db() dependency.
    category_id : Optional — filter to a single category.
    active_only : Exclude soft-deleted products and their categories (default True).
    page        : 1-based page number.
    page_size   : Rows per page; capped at MAX_PAGE_SIZE.

    Returns
    -------
    ProductListResponse

    Raises
    ------
    BusinessRuleError : Invalid pagination params.
    DatabaseError     : Propagated from repository.
    """
    if page < 1:
        raise BusinessRuleError(
            "INVALID_PAGINATION",
            f"page must be >= 1, got {page}.",
            detail={"page": page},
        )
    if page_size < 1:
        raise BusinessRuleError(
            "INVALID_PAGINATION",
            f"page_size must be >= 1, got {page_size}.",
            detail={"page_size": page_size},
        )
    if category_id is not None and category_id < 1:
        raise BusinessRuleError(
            "INVALID_FILTER",
            f"category_id must be a positive integer, got {category_id}.",
            detail={"category_id": category_id},
        )

    effective_page_size = min(page_size, MAX_PAGE_SIZE)

    logger.debug(
        "list_products category_id=%s active_only=%s page=%d page_size=%d",
        category_id, active_only, page, effective_page_size,
    )

    total, rows = product_repository.get_all(
        conn,
        category_id=category_id,
        active_only=active_only,
        page=page,
        page_size=effective_page_size,
    )

    from models.product import ProductSummary  # local import avoids circular at module level
    items = [ProductSummary(**row) for row in rows]

    filters: dict = {}
    if category_id is not None:
        filters["category_id"] = category_id
    if not active_only:
        filters["active_only"] = False

    return ProductListResponse(
        total=total,
        page=page,
        page_size=effective_page_size,
        filters=filters,
        items=items,
    )


def get_product(
    conn: PooledMySQLConnection,
    product_id: int,
    *,
    include_inventory: bool = False,
) -> ProductResponse:
    """Return a single product by primary key.

    Parameters
    ----------
    conn              : DB connection from get_db() dependency.
    product_id        : PK of the product to fetch.
    include_inventory : When True, embed current stock info in the response.

    Returns
    -------
    ProductResponse (with optional inventory sub-object)

    Raises
    ------
    NotFoundError : Propagated from repository.
    DatabaseError : Propagated from repository.
    """
    logger.debug("get_product id=%d include_inventory=%s", product_id, include_inventory)

    row = product_repository.get_by_id(
        conn,
        product_id,
        include_inventory=include_inventory,
    )

    # Build the optional inventory sub-model
    inventory_model: Optional[ProductInventoryInfo] = None
    if include_inventory and row.get("inventory") is not None:
        inventory_model = ProductInventoryInfo(**row["inventory"])

    return ProductResponse(
        product_id=row["product_id"],
        category_id=row["category_id"],
        category_name=row["category_name"],
        name=row["name"],
        description=row.get("description"),
        unit_price=row["unit_price"],
        is_active=row["is_active"],
        inventory=inventory_model,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_products_by_category(
    conn: PooledMySQLConnection,
    category_id: int,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> ProductListResponse:
    """Convenience wrapper — products filtered to a single category.

    Delegates to list_products() with category_id set.  Used by the
    nested route GET /categories/{category_id}/products.
    """
    return list_products(
        conn,
        category_id=category_id,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )
