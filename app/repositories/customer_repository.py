"""
repositories/customer_repository.py
=====================================
Direct SQL queries for the customers table.

Rules (consistent with Phase 2 repositories)
---------------------------------------------
- All SQL is parameterised — no string interpolation of user input.
- Cursors always use dictionary=True so rows are returned as dicts.
- TINYINT(1) is_active is normalised to bool before returning.
- Raw MySQLError is caught here, logged internally, and re-raised as
  DatabaseError so the service layer never sees a MySQL-specific exception.
- Soft-deleted rows (is_active = 0) are excluded by default; pass
  active_only=False to include them.
- No password, password_hash, or credential column is touched. (SR-9)

Public interface
----------------
    get_all(conn, *, active_only, page, page_size) -> (total: int, rows: list[dict])
    get_by_id(conn, customer_id)                   -> dict
    get_by_email(conn, email)                       -> dict | None
    create(conn, *, first_name, last_name, email, phone=None) -> int
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import ConflictError, DatabaseError, NotFoundError

logger = logging.getLogger(__name__)

# Columns selected in every customer query — listed explicitly so that any
# future column additions (e.g. external_auth_id) don't leak into responses.
_SELECT_COLS = """
    customer_id,
    first_name,
    last_name,
    email,
    phone,
    is_active,
    created_at,
    updated_at
"""


def _normalise(row: dict) -> dict:
    """Normalise MySQL types to Python-native types in-place."""
    row["is_active"] = bool(row["is_active"])
    return row


def get_all(
    conn: PooledMySQLConnection,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[dict]]:
    """Return a paginated list of customers.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    active_only : When True (default), exclude is_active = 0 rows.
    page        : 1-based page number.
    page_size   : Rows per page (max enforced by the service layer).

    Returns
    -------
    (total, rows)
        total — total matching row count (used for pagination metadata)
        rows  — list of dicts for the requested page
    """
    offset = (page - 1) * page_size
    where = "WHERE is_active = 1" if active_only else ""

    count_sql = f"SELECT COUNT(*) AS total FROM customers {where}"
    data_sql = f"""
        SELECT {_SELECT_COLS}
        FROM customers
        {where}
        ORDER BY last_name ASC, first_name ASC
        LIMIT %s OFFSET %s
    """

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(count_sql)
        total: int = (cursor.fetchone() or {}).get("total", 0)

        cursor.execute(data_sql, (page_size, offset))
        rows: List[dict] = cursor.fetchall()
        cursor.close()

        for row in rows:
            _normalise(row)

        return total, rows

    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"customer_repository.get_all: {exc}"
        ) from exc


def get_by_id(
    conn: PooledMySQLConnection,
    customer_id: int,
) -> dict:
    """Return a single customer row by primary key.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    customer_id : PK value to look up.

    Returns
    -------
    dict — all customer columns (both active and inactive rows are returned;
           the service layer decides whether to surface inactive customers).

    Raises
    ------
    NotFoundError : No row found for the given customer_id.
    DatabaseError : Unexpected MySQL error.
    """
    sql = f"""
        SELECT {_SELECT_COLS}
        FROM customers
        WHERE customer_id = %s
    """

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (customer_id,))
        row: dict | None = cursor.fetchone()
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"customer_repository.get_by_id id={customer_id}: {exc}"
        ) from exc

    if row is None:
        raise NotFoundError("customer", customer_id)

    return _normalise(row)


def get_by_email(conn: PooledMySQLConnection, email: str) -> dict | None:
    """Return a customer row by email, or None if not found.

    Unlike get_by_id, this does NOT raise NotFoundError — it's used by
    services/auth_service.py to check "does an account already exist for
    this email?", where "no" is an expected, ordinary outcome (new
    signup), not an error.

    Parameters
    ----------
    conn  : Pooled connection from get_db() dependency.
    email : Email address to look up (exact match — emails are stored
            lowercase-as-typed; no normalisation is applied here).

    Returns
    -------
    dict | None
    """
    sql = f"""
        SELECT {_SELECT_COLS}
        FROM customers
        WHERE email = %s
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (email,))
        row: dict | None = cursor.fetchone()
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"customer_repository.get_by_email email={email}: {exc}"
        ) from exc

    return _normalise(row) if row else None


def create(
    conn: PooledMySQLConnection,
    *,
    first_name: str,
    last_name: str,
    email: str,
    phone: str | None = None,
) -> int:
    """Insert a new customer row. Caller commits.

    Used by services/auth_service.py to auto-register a customer the first
    time they successfully request an OTP for a new email.

    Raises
    ------
    ConflictError : email already exists (e.g. a race between two
                    concurrent signups for the same address).
    DatabaseError  : Unexpected MySQL error.
    """
    sql = """
        INSERT INTO customers (first_name, last_name, email, phone, is_active, created_at, updated_at)
        VALUES (%s, %s, %s, %s, 1, NOW(), NOW())
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (first_name, last_name, email, phone))
        new_id = cursor.lastrowid
        cursor.close()
        return new_id
    except MySQLError as exc:
        if exc.errno == 1062:  # ER_DUP_ENTRY — the email UNIQUE constraint
            raise ConflictError(
                "email", f"An account with email {email} already exists."
            ) from exc
        raise DatabaseError(
            internal_detail=f"customer_repository.create email={email}: {exc}"
        ) from exc
