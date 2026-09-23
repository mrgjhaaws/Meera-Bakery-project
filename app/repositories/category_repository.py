"""
repositories/category_repository.py
====================================
Direct SQL queries for the categories table.

Rules
-----
- All SQL is parameterised — no string interpolation of user input.
- Cursors always use dictionary=True so rows are returned as dicts.
- DECIMAL and TINYINT values from MySQL are returned as-is; the service
  layer normalises types before building Pydantic models.
- Raw MySQLError is caught here, logged internally, and re-raised as
  DatabaseError so the service layer never sees a MySQL-specific exception.
- Soft-deleted rows (is_active = 0) are excluded by default via the
  active_only parameter.  Pass active_only=False to include them (admin use).

Public interface
----------------
    get_all(conn, active_only, page, page_size) -> (total: int, rows: list[dict])
    get_by_id(conn, category_id)                -> dict
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import DatabaseError, NotFoundError

logger = logging.getLogger(__name__)


def get_all(
    conn: PooledMySQLConnection,
    *,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[dict]]:
    """Return a paginated list of categories.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    active_only : When True (default), exclude is_active = 0 rows.
    page        : 1-based page number.
    page_size   : Rows per page (max enforced by service layer).

    Returns
    -------
    (total, rows)
        total — total matching row count (for pagination metadata)
        rows  — list of dicts for the requested page
    """
    offset = (page - 1) * page_size
    where = "WHERE is_active = 1" if active_only else ""

    count_sql = f"SELECT COUNT(*) AS total FROM categories {where}"
    data_sql = f"""
        SELECT
            category_id,
            name,
            description,
            is_active,
            created_at,
            updated_at
        FROM categories
        {where}
        ORDER BY name ASC
        LIMIT %s OFFSET %s
    """
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(count_sql)
        total: int = (cursor.fetchone() or {}).get("total", 0)

        cursor.execute(data_sql, (page_size, offset))
        rows: List[dict] = cursor.fetchall()
        cursor.close()

        # Normalise is_active tinyint → bool
        for row in rows:
            row["is_active"] = bool(row["is_active"])

        return total, rows

    except MySQLError as exc:
        raise DatabaseError(internal_detail=f"category_repository.get_all: {exc}") from exc


def get_by_id(
    conn: PooledMySQLConnection,
    category_id: int,
) -> dict:
    """Return a single category row by primary key.

    Parameters
    ----------
    conn        : Pooled connection from get_db() dependency.
    category_id : PK value to look up.

    Returns
    -------
    dict — row with all category columns.

    Raises
    ------
    NotFoundError  : No row found for the given category_id.
    DatabaseError  : Unexpected MySQL error.
    """
    sql = """
        SELECT
            category_id,
            name,
            description,
            is_active,
            created_at,
            updated_at
        FROM categories
        WHERE category_id = %s
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (category_id,))
        row: dict | None = cursor.fetchone()
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"category_repository.get_by_id id={category_id}: {exc}"
        ) from exc

    if row is None:
        raise NotFoundError("category", category_id)

    row["is_active"] = bool(row["is_active"])
    return row
