"""
repositories/address_repository.py
=====================================
Direct SQL queries for the addresses table.

Rules (consistent with Phase 2 repositories)
---------------------------------------------
- All SQL is parameterised — no string interpolation of user input.
- Cursors always use dictionary=True so rows are returned as dicts.
- TINYINT(1) columns is_active and is_default are normalised to bool.
- Raw MySQLError is caught and re-raised as DatabaseError.
- Soft-deleted rows (is_active = 0) are excluded by default.

Ordering
--------
get_all_for_customer returns addresses ordered by:
    is_default DESC  — default address always first
    label      ASC   — then alphabetically by label (Home, Office …)

Customer existence check
------------------------
get_all_for_customer verifies the customer exists before querying addresses.
This produces a clean NotFoundError("customer", id) rather than an empty
list when the customer_id is invalid — matching the behaviour callers expect.

Public interface
----------------
    get_all_for_customer(conn, customer_id, *, active_only, page, page_size)
        -> (total: int, rows: list[dict])
    get_by_id(conn, address_id)
        -> dict
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import DatabaseError, NotFoundError

logger = logging.getLogger(__name__)

_SELECT_COLS = """
    address_id,
    customer_id,
    label,
    address_line1,
    address_line2,
    city,
    state,
    postal_code,
    country,
    is_default,
    is_active,
    created_at,
    updated_at
"""


def _normalise(row: dict) -> dict:
    """Normalise MySQL TINYINT(1) columns to Python bool in-place."""
    row["is_active"] = bool(row["is_active"])
    row["is_default"] = bool(row["is_default"])
    return row


def get_all_for_customer(
    conn: PooledMySQLConnection,
    customer_id: int,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[dict]]:
    """Return a paginated list of addresses belonging to a customer.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    customer_id : FK to the customers table.
    active_only : When True (default), exclude is_active = 0 rows.
    page        : 1-based page number.
    page_size   : Rows per page (max enforced by the service layer).

    Returns
    -------
    (total, rows)

    Raises
    ------
    NotFoundError : customer_id does not exist in the customers table.
    DatabaseError : Unexpected MySQL error.
    """
    offset = (page - 1) * page_size

    # Build address filter: always filter by customer_id, optionally by is_active
    addr_conditions = ["customer_id = %s"]
    addr_params: list = [customer_id]
    if active_only:
        addr_conditions.append("is_active = 1")
    addr_where = "WHERE " + " AND ".join(addr_conditions)

    verify_sql = "SELECT customer_id FROM customers WHERE customer_id = %s"
    count_sql = f"SELECT COUNT(*) AS total FROM addresses {addr_where}"
    data_sql = f"""
        SELECT {_SELECT_COLS}
        FROM addresses
        {addr_where}
        ORDER BY is_default DESC, label ASC
        LIMIT %s OFFSET %s
    """

    try:
        cursor = conn.cursor(dictionary=True)

        # Step 1: confirm the customer exists
        cursor.execute(verify_sql, (customer_id,))
        if cursor.fetchone() is None:
            cursor.close()
            raise NotFoundError("customer", customer_id)

        # Step 2: count matching addresses
        cursor.execute(count_sql, addr_params)
        total: int = (cursor.fetchone() or {}).get("total", 0)

        # Step 3: fetch page
        cursor.execute(data_sql, addr_params + [page_size, offset])
        rows: List[dict] = cursor.fetchall()
        cursor.close()

        for row in rows:
            _normalise(row)

        return total, rows

    except NotFoundError:
        raise
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"address_repository.get_all_for_customer "
                f"customer_id={customer_id}: {exc}"
            )
        ) from exc


def get_by_id(
    conn: PooledMySQLConnection,
    address_id: int,
) -> dict:
    """Return a single address row by primary key.

    Parameters
    ----------
    conn       : Pooled connection from get_db() dependency.
    address_id : PK value to look up.

    Returns
    -------
    dict — all address columns (active and inactive rows are both returned;
           the service layer handles visibility rules if needed).

    Raises
    ------
    NotFoundError : No row found for the given address_id.
    DatabaseError : Unexpected MySQL error.
    """
    sql = f"""
        SELECT {_SELECT_COLS}
        FROM addresses
        WHERE address_id = %s
    """

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (address_id,))
        row: dict | None = cursor.fetchone()
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"address_repository.get_by_id id={address_id}: {exc}"
        ) from exc

    if row is None:
        raise NotFoundError("address", address_id)

    return _normalise(row)
