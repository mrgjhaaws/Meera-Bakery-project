"""
repositories/otp_repository.py
================================
Direct SQL queries for the otp_codes table.

Rules (consistent with other repositories)
--------------------------------------------
- All SQL is parameterised.
- Cursors always use dictionary=True.
- Raw MySQLError is caught and re-raised as DatabaseError.
- This repository never calls conn.commit() — the service layer owns the
  transaction boundary.

Public interface
------------------
    create(conn, email, code_hash, expires_at, max_attempts) -> otp_id
    get_most_recent(conn, email) -> dict | None
    get_active_for_verification(conn, email) -> dict | None
    increment_attempt(conn, otp_id) -> None
    mark_consumed(conn, otp_id) -> None
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)


def create(
    conn: PooledMySQLConnection,
    email: str,
    code_hash: str,
    expires_at: datetime,
    max_attempts: int = 5,
) -> int:
    """Insert a new OTP row. Caller commits.

    Deliberately does NOT invalidate previous unconsumed rows for this
    email — get_active_for_verification always selects the most recent
    row, so older ones simply become irrelevant rather than needing
    cleanup here.
    """
    sql = """
        INSERT INTO otp_codes (email, code_hash, purpose, max_attempts, expires_at, created_at)
        VALUES (%s, %s, 'login', %s, %s, NOW())
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (email, code_hash, max_attempts, expires_at))
        otp_id = cursor.lastrowid
        cursor.close()
        return otp_id
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"otp_repository.create email={email}: {exc}"
        ) from exc


def get_most_recent(conn: PooledMySQLConnection, email: str) -> Optional[dict]:
    """Return the single most recent OTP row for this email, regardless of
    its consumed/expired state — used only for the request cooldown check."""
    sql = """
        SELECT otp_id, email, created_at
        FROM otp_codes
        WHERE email = %s
        ORDER BY created_at DESC
        LIMIT 1
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (email,))
        row = cursor.fetchone()
        cursor.close()
        return row
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"otp_repository.get_most_recent email={email}: {exc}"
        ) from exc


def get_active_for_verification(conn: PooledMySQLConnection, email: str) -> Optional[dict]:
    """Return the most recent OTP row for this email that is still usable:
    not consumed, not expired, and under its attempt limit.

    Returns None if no such row exists (caller raises AuthenticationError).
    """
    sql = """
        SELECT otp_id, email, code_hash, attempt_count, max_attempts, expires_at
        FROM otp_codes
        WHERE email = %s
          AND consumed_at IS NULL
          AND expires_at > NOW()
          AND attempt_count < max_attempts
        ORDER BY created_at DESC
        LIMIT 1
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (email,))
        row = cursor.fetchone()
        cursor.close()
        return row
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"otp_repository.get_active_for_verification email={email}: {exc}"
        ) from exc


def increment_attempt(conn: PooledMySQLConnection, otp_id: int) -> None:
    sql = "UPDATE otp_codes SET attempt_count = attempt_count + 1 WHERE otp_id = %s"
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (otp_id,))
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"otp_repository.increment_attempt otp_id={otp_id}: {exc}"
        ) from exc


def mark_consumed(conn: PooledMySQLConnection, otp_id: int) -> None:
    sql = "UPDATE otp_codes SET consumed_at = NOW() WHERE otp_id = %s"
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (otp_id,))
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"otp_repository.mark_consumed otp_id={otp_id}: {exc}"
        ) from exc
