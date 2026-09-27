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

from typing import Generator, Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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


# auto_error=False so a missing/malformed Authorization header reaches our
# own AuthenticationError (consistent JSON error shape) instead of FastAPI's
# default 403 with a different shape.
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_customer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    conn: PooledMySQLConnection = Depends(get_db),
):
    """Resolve the logged-in customer from the request's Bearer token.

    Use on any endpoint that should require login:
        customer = Depends(get_current_customer)

    Raises
    ------
    AuthenticationError : missing/malformed header, expired/invalid token,
                          or the token's customer no longer exists / is
                          inactive. Maps to HTTP 401 (see utils/exceptions.py).
    """
    # Local imports to avoid a circular import at module load time
    # (repositories -> utils.exceptions -> ... -> dependencies in some
    # import orders); cheap enough to not matter for a per-request call.
    from models.customer import CustomerResponse
    from repositories import customer_repository
    from utils import jwt_auth
    from utils.exceptions import AuthenticationError, NotFoundError

    if credentials is None:
        raise AuthenticationError("Missing or malformed Authorization header.")

    try:
        payload = jwt_auth.decode_access_token(credentials.credentials)
    except jwt_auth.InvalidTokenException as exc:
        raise AuthenticationError(str(exc)) from exc

    customer_id = int(payload["sub"])
    try:
        customer = customer_repository.get_by_id(conn, customer_id)
    except NotFoundError as exc:
        # The token is structurally valid but its customer is gone — this
        # is an auth failure from the caller's point of view, not a 404.
        raise AuthenticationError("This account no longer exists.") from exc

    if not customer["is_active"]:
        raise AuthenticationError("This account is no longer active.")

    return CustomerResponse(**customer)
