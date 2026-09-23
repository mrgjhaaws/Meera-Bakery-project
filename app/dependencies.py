"""
dependencies.py
===============
FastAPI dependency injection providers for the Meera Bakery API.

Dependencies defined here are injected into route handlers via FastAPI's
Depends() mechanism.  This keeps handlers thin and decouples them from
infrastructure concerns (database connections, settings).

Usage in a route handler
------------------------
    from fastapi import APIRouter, Depends
    from mysql.connector.pooling import PooledMySQLConnection
    from dependencies import get_db

    router = APIRouter()

    @router.get("/example")
    def example_route(conn: PooledMySQLConnection = Depends(get_db)):
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT 1")
        return cursor.fetchone()

Design notes
------------
- get_db() uses a context manager (yield) so FastAPI guarantees the
  connection is returned to the pool after the response is sent, even
  if an exception occurs during request processing.
- The connection is NOT committed here — service-layer code that writes
  data calls conn.commit() explicitly before returning.
- get_settings_dep() is a thin wrapper that allows test code to override
  settings via FastAPI's dependency_overrides mechanism.
"""

from __future__ import annotations

from typing import Generator

from mysql.connector.pooling import PooledMySQLConnection

from config import Settings, get_settings
from db.connection import get_db_connection


def get_db() -> Generator[PooledMySQLConnection, None, None]:
    """Yield a pooled MySQL connection, then return it to the pool.

    Use as a FastAPI dependency:
        conn: PooledMySQLConnection = Depends(get_db)
    """
    with get_db_connection() as conn:
        yield conn


def get_settings_dep() -> Settings:
    """Return the application settings singleton.

    Wrapping get_settings() in a dependency allows tests to override it:
        app.dependency_overrides[get_settings_dep] = lambda: test_settings
    """
    return get_settings()
