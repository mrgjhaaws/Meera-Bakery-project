"""
utils/otp.py
=============
OTP code generation and hashing helpers.

Codes are 6 digits (e.g. "042817"), zero-padded, generated with `secrets`
(cryptographically secure) rather than `random` — this is a login
credential, not test data. Only the SHA-256 hash of the code is ever
persisted to the database; the plaintext code exists only in memory long
enough to email it (or, in local dev mode, to log/return it).
"""

from __future__ import annotations

import hashlib
import secrets


def generate_otp_code() -> str:
    """Return a cryptographically random 6-digit code, e.g. '042817'."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp_code(code: str) -> str:
    """SHA-256 hex digest of a code — what actually gets stored in the DB."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
