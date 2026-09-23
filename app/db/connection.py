"""
db/connection.py
================
MySQL connection pool management for the Meera Bakery API.

The pool is created once at application startup (via FastAPI lifespan) and
torn down at application shutdown.  Individual request handlers acquire a
connection from the pool, use it, and return it — they never create or close
connections themselves.

Design notes
------------
- mysql-connector-python's MySQLConnectionPool is thread-safe.
- pool_reset_session=True ensures no leftover session state (SET variables,
  open transactions) bleeds between requests.
- SSL is enforced in production (APP_ENV=production) using the RDS CA cert
  path. In local development SSL is optional (local MySQL may not have a cert).
- autocommit is intentionally left False.  Service-layer code that needs a
  transaction uses the get_db_connection() context manager and calls
  conn.commit() / conn.rollback() explicitly.

Usage
-----
    # In FastAPI lifespan (main.py):
    from db.connection import init_pool, close_pool

    # In repository functions (via dependency injection):
    from db.connection import get_connection
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        ...
        conn.commit()
    finally:
        conn.close()   # returns to pool, does NOT close the TCP connection
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector.pooling import MySQLConnectionPool, PooledMySQLConnection

from config import settings

logger = logging.getLogger(__name__)

# Module-level pool instance — initialised by init_pool(), used by get_connection()
_pool: MySQLConnectionPool | None = None


def _build_pool_config() -> dict:
    """Build the keyword-argument dict for MySQLConnectionPool.

    SSL is required when APP_ENV=production.  The RDS CA bundle is expected at
    the path below; adjust if you place it elsewhere on the EC2 instance.
    """
    cfg: dict = {
        "pool_name": "meera_bakery_pool",
        "pool_size": settings.db_pool_size,
        "pool_reset_session": True,
        "host": settings.db_host,
        "port": settings.db_port,
        "database": settings.db_name,
        "user": settings.db_user,
        "password": settings.db_password,
        "autocommit": False,
        "connect_timeout": 10,
        "connection_timeout": 30,
        # Return column names as strings (used with dictionary=True cursors)
        "use_unicode": True,
        "charset": "utf8mb4",
        # Raise an exception rather than return an error packet silently
        "raise_on_warnings": True,
    }

    if settings.is_production:
        # Enforce TLS — use the AWS RDS CA bundle downloaded to the instance.
        # Download command (run once on EC2 during setup):
        #   curl -o /home/ec2-user/meera-bakery/rds-ca.pem \
        #        https://truststore.pki.rds.amazonaws.com/ap-south-1/ap-south-1-bundle.pem
        cfg["ssl_ca"] = "/home/ec2-user/meera-bakery/rds-ca.pem"
        cfg["ssl_disabled"] = False
        logger.info("Database SSL enabled (production mode).")
    else:
        # Local development — SSL optional
        cfg["ssl_disabled"] = True
        logger.debug("Database SSL disabled (local development mode).")

    return cfg


def init_pool() -> None:
    """Create the global connection pool.

    Called once from the FastAPI lifespan startup handler in main.py.
    Raises MySQLError (with a sanitised message) if the database is
    unreachable at startup — this is intentional: fail fast rather than
    serve requests that will all fail.
    """
    global _pool
    if _pool is not None:
        logger.warning("init_pool() called but pool already exists — skipping.")
        return

    config = _build_pool_config()
    try:
        _pool = MySQLConnectionPool(**config)
        logger.info(
            "Database connection pool created. "
            "host=%s db=%s pool_size=%d",
            settings.db_host,
            settings.db_name,
            settings.db_pool_size,
        )
    except MySQLError as exc:
        # Never log the password — only log the error code and message
        logger.error(
            "Failed to create database connection pool. "
            "errno=%s msg=%s",
            exc.errno,
            exc.msg,
        )
        raise


def close_pool() -> None:
    """Release all pooled connections.

    Called from the FastAPI lifespan shutdown handler in main.py.
    Safe to call even if the pool was never initialised.
    """
    global _pool
    if _pool is None:
        return
    try:
        # mysql-connector-python does not expose an explicit pool.close();
        # setting the reference to None allows GC to close idle connections.
        _pool = None
        logger.info("Database connection pool released.")
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Error while releasing connection pool: %s", exc)


def get_connection() -> PooledMySQLConnection:
    """Acquire a connection from the pool.

    The caller is responsible for returning it via conn.close()
    (which returns it to the pool, not closes the TCP connection).

    Prefer the get_db_connection() context manager for automatic cleanup.

    Raises
    ------
    RuntimeError
        If the pool has not been initialised (application startup error).
    MySQLError
        If all pool connections are in use and the timeout is exceeded.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool is not initialised. "
            "Ensure init_pool() was called during application startup."
        )
    return _pool.get_connection()


@contextmanager
def get_db_connection() -> Generator[PooledMySQLConnection, None, None]:
    """Context manager that acquires a pooled connection and guarantees release.

    Rolls back automatically on any unhandled exception so the returned
    connection is always in a clean state.

    Usage
    -----
        from db.connection import get_db_connection

        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT ...", (param,))
            rows = cursor.fetchall()
        # connection automatically returned to pool here

    For operations that require an explicit commit:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("INSERT ...", (param,))
            conn.commit()
    """
    conn: PooledMySQLConnection = get_connection()
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception as rb_exc:  # pylint: disable=broad-except
            logger.warning("Rollback failed: %s", rb_exc)
        raise
    finally:
        conn.close()  # returns to pool
