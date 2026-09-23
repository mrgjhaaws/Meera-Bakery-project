"""
services/category_service.py
=============================
Business logic for the categories resource.

Responsibilities
----------------
- Enforce pagination limits (max page_size = 100).
- Validate inputs that the router layer passes through (e.g. page >= 1).
- Call the repository layer and translate raw dicts into Pydantic response models.
- The service layer never touches SQL directly — all DB calls go through
  the repository.

The service functions receive a PooledMySQLConnection that was acquired by
the FastAPI dependency get_db() and injected into the router handler.  The
connection is returned to the pool by the dependency after the handler returns.
"""

from __future__ import annotations

import logging

from mysql.connector.pooling import PooledMySQLConnection

from models.category import CategoryListResponse, CategoryResponse
from repositories import category_repository
from utils.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

# Maximum rows allowed per page — prevents accidentally dumping the whole table
MAX_PAGE_SIZE = 100


def list_categories(
    conn: PooledMySQLConnection,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> CategoryListResponse:
    """Return a paginated list of categories.

    Parameters
    ----------
    conn        : DB connection from get_db() dependency.
    active_only : Exclude soft-deleted categories when True (default).
    page        : 1-based page number.
    page_size   : Rows per page; capped at MAX_PAGE_SIZE.

    Returns
    -------
    CategoryListResponse — includes total count, pagination metadata, and items.

    Raises
    ------
    BusinessRuleError : page < 1 or page_size < 1.
    DatabaseError     : Propagated from repository on unexpected MySQL error.
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

    # Silently cap — callers that pass 500 still get a valid response
    effective_page_size = min(page_size, MAX_PAGE_SIZE)

    logger.debug(
        "list_categories active_only=%s page=%d page_size=%d",
        active_only, page, effective_page_size,
    )

    total, rows = category_repository.get_all(
        conn,
        active_only=active_only,
        page=page,
        page_size=effective_page_size,
    )

    items = [CategoryResponse(**row) for row in rows]

    return CategoryListResponse(
        total=total,
        page=page,
        page_size=effective_page_size,
        items=items,
    )


def get_category(
    conn: PooledMySQLConnection,
    category_id: int,
) -> CategoryResponse:
    """Return a single category by primary key.

    Parameters
    ----------
    conn        : DB connection from get_db() dependency.
    category_id : PK of the category to fetch.

    Returns
    -------
    CategoryResponse

    Raises
    ------
    NotFoundError : Propagated from repository when category_id does not exist.
    DatabaseError : Propagated from repository on unexpected MySQL error.
    """
    logger.debug("get_category id=%d", category_id)
    row = category_repository.get_by_id(conn, category_id)
    return CategoryResponse(**row)
