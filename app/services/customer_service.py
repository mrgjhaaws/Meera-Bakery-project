"""
services/customer_service.py
=============================
Business logic for the customers resource.

Responsibilities
----------------
- Enforce pagination limits (MAX_PAGE_SIZE = 100, consistent with Phase 2).
- Validate inputs and raise BusinessRuleError for bad params.
- Delegate all DB access to customer_repository.
- Translate raw repository dicts into Pydantic response models.

The service never touches SQL directly.  It receives a PooledMySQLConnection
from the FastAPI dependency get_db() via the router handler.
"""

from __future__ import annotations

import logging

from mysql.connector.pooling import PooledMySQLConnection

from models.customer import CustomerListResponse, CustomerResponse, CustomerSummary
from repositories import customer_repository
from utils.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100


def list_customers(
    conn: PooledMySQLConnection,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> CustomerListResponse:
    """Return a paginated list of customers.

    Parameters
    ----------
    conn        : DB connection from get_db() dependency.
    active_only : Exclude soft-deleted customers when True (default).
    page        : 1-based page number.
    page_size   : Rows per page; silently capped at MAX_PAGE_SIZE.

    Returns
    -------
    CustomerListResponse

    Raises
    ------
    BusinessRuleError : page < 1 or page_size < 1.
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

    effective_page_size = min(page_size, MAX_PAGE_SIZE)

    logger.debug(
        "list_customers active_only=%s page=%d page_size=%d",
        active_only, page, effective_page_size,
    )

    total, rows = customer_repository.get_all(
        conn,
        active_only=active_only,
        page=page,
        page_size=effective_page_size,
    )

    items = [CustomerSummary(**row) for row in rows]

    return CustomerListResponse(
        total=total,
        page=page,
        page_size=effective_page_size,
        items=items,
    )


def get_customer(
    conn: PooledMySQLConnection,
    customer_id: int,
) -> CustomerResponse:
    """Return a single customer by primary key.

    Parameters
    ----------
    conn        : DB connection from get_db() dependency.
    customer_id : PK of the customer to fetch.

    Returns
    -------
    CustomerResponse

    Raises
    ------
    NotFoundError : Propagated from repository when customer_id does not exist.
    DatabaseError : Propagated from repository on unexpected MySQL error.
    """
    logger.debug("get_customer id=%d", customer_id)
    row = customer_repository.get_by_id(conn, customer_id)
    return CustomerResponse(**row)
