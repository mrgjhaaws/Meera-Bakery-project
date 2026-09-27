"""
utils/jwt_auth.py
===================
Issues and verifies the JWT access tokens returned by POST /auth/verify-otp
and required (as a Bearer token) by protected endpoints such as
GET /auth/me.

Token payload
--------------
    {
      "sub": "<customer_id>",   # standard JWT subject claim, as a string
      "email": "<email>",
      "iat": <unix timestamp>,
      "exp": <unix timestamp>,
    }

Signing
--------
HS256 with a symmetric key from settings.jwt_secret_key. That's fine for a
single-service learning project; a system with multiple backend services
verifying the same token would typically move to RS256 with a shared
public key instead, so only the auth service holds the private key.

config.py's _check_production_secrets validator refuses to start the app
in production with the default dev secret key, so this is safe by
construction rather than by convention.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt as pyjwt
from jwt import ExpiredSignatureError, InvalidTokenError

from config import settings


class InvalidTokenException(Exception):
    """Raised for any token problem: expired, malformed, or wrong signature."""


def create_access_token(customer_id: int, email: str) -> str:
    """Issue a signed access token for a customer who just verified their OTP."""
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(customer_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expiry_minutes)).timestamp()),
    }
    return pyjwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> Dict[str, Any]:
    """Verify and decode an access token.

    Raises
    ------
    InvalidTokenException : token is expired, malformed, or has an invalid
                             signature. Callers (see dependencies.py) turn
                             this into an AuthenticationError (HTTP 401).
    """
    try:
        return pyjwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except ExpiredSignatureError as exc:
        raise InvalidTokenException("Token has expired.") from exc
    except InvalidTokenError as exc:
        raise InvalidTokenException("Token is invalid.") from exc
