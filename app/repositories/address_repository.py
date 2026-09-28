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
    create(conn, customer_id, data)
        -> int
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


def create(conn: PooledMySQLConnection, customer_id: int, data: dict) -> int:
    """Insert a new address for a customer. Caller commits.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    customer_id : FK to customers — existence is verified first.
    data        : dict with keys label, address_line1, address_line2,
                  city, state, postal_code, country, is_default (matches
                  models.address.AddressCreate.model_dump()).

    Returns
    -------
    int — the new address_id.

    Raises
    ------
    NotFoundError : customer_id does not exist.
    DatabaseError  : Unexpected MySQL error.
    """
    verify_sql = "SELECT customer_id FROM customers WHERE customer_id = %s"
    count_active_sql = "SELECT COUNT(*) AS n FROM addresses WHERE customer_id = %s AND is_active = 1"
    clear_default_sql = (
        "UPDATE addresses SET is_default = 0 WHERE customer_id = %s AND is_default = 1"
    )
    insert_sql = """
        INSERT INTO addresses
            (customer_id, label, address_line1, address_line2, city, state,
             postal_code, country, is_default, is_active, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NOW(), NOW())
    """

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(verify_sql, (customer_id,))
        if cursor.fetchone() is None:
            cursor.close()
            raise NotFoundError("customer", customer_id)

        # A customer should never end up with zero default addresses — force
        # is_default=True on their very first one, regardless of what was sent.
        cursor.execute(count_active_sql, (customer_id,))
        is_first_address = (cursor.fetchone() or {}).get("n", 0) == 0
        is_default = 1 if (is_first_address or data.get("is_default")) else 0

        if is_default:
            cursor.execute(clear_default_sql, (customer_id,))

        cursor.execute(
            insert_sql,
            (
                customer_id,
                data["label"],
                data["address_line1"],
                data.get("address_line2"),
                data["city"],
                data["state"],
                data["postal_code"],
                data["country"],
                is_default,
            ),
        )
        new_id = cursor.lastrowid
        cursor.close()
        return new_id

    except NotFoundError:
        raise
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"address_repository.create customer_id={customer_id}: {exc}"
        ) from exc
