"""
services/address_service.py
============================
Business logic for the addresses resource.

Responsibilities
----------------
- Enforce pagination limits (MAX_PAGE_SIZE = 100, consistent with Phase 2).
- Validate inputs and raise BusinessRuleError for bad params.
- Delegate all DB access to address_repository.
- Translate raw repository dicts into Pydantic response models.

The service never touches SQL directly.  It receives a PooledMySQLConnection
from the FastAPI dependency get_db() via the router handler.
"""

from __future__ import annotations

import logging

from mysql.connector.pooling import PooledMySQLConnection

from models.address import AddressListResponse, AddressResponse, AddressSummary
from repositories import address_repository
from utils.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100


def list_addresses(
    conn: PooledMySQLConnection,
    customer_id: int,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> AddressListResponse:
    """Return a paginated list of addresses for a given customer.

    Parameters
    ----------
    conn        : DB connection from get_db() dependency.
    customer_id : PK of the customer whose addresses to list.
    active_only : Exclude soft-deleted addresses when True (default).
    page        : 1-based page number.
    page_size   : Rows per page; silently capped at MAX_PAGE_SIZE.

    Returns
    -------
    AddressListResponse

    Raises
    ------
    BusinessRuleError : page < 1 or page_size < 1.
    NotFoundError     : Propagated from repository when customer_id does not exist.
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

    effective_page_size = min(page_size, MAX_PAGE_SIZE)

    logger.debug(
        "list_addresses customer_id=%d active_only=%s page=%d page_size=%d",
        customer_id, active_only, page, effective_page_size,
    )

    total, rows = address_repository.get_all_for_customer(
        conn,
        customer_id,
        active_only=active_only,
        page=page,
        page_size=effective_page_size,
    )

    items = [AddressSummary(**row) for row in rows]

    return AddressListResponse(
        total=total,
        page=page,
        page_size=effective_page_size,
        items=items,
    )


def get_address(
    conn: PooledMySQLConnection,
    address_id: int,
) -> AddressResponse:
    """Return a single address by primary key.

    Parameters
    ----------
    conn       : DB connection from get_db() dependency.
    address_id : PK of the address to fetch.

    Returns
    -------
    AddressResponse

    Raises
    ------
    NotFoundError : Propagated from repository when address_id does not exist.
    DatabaseError : Propagated from repository on unexpected MySQL error.
    """
    logger.debug("get_address id=%d", address_id)
    row = address_repository.get_by_id(conn, address_id)
    return AddressResponse(**row)
