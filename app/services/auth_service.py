"""
services/auth_service.py
==========================
Business logic for OTP-based email login.

Flow
-----
1. request_otp(email, first_name?, last_name?)
   - If no customer exists for this email: first_name and last_name are
     required (BusinessRuleError if missing) and a new customer row is
     created immediately, before the OTP is even generated. phone stays
     NULL — this flow doesn't collect it.
   - Enforces a cooldown between requests for the same email
     (settings.otp_request_cooldown_seconds) so one person can't spam SES
     or spam the recipient's inbox.
   - Generates a 6-digit code, stores only its SHA-256 hash, and emails it
     via utils/email.py (or logs it in dev mode).

2. verify_otp(email, code)
   - Looks up the most recent unconsumed, unexpired, not-locked-out OTP
     for this email (repository query already filters all three).
   - Wrong code -> increments attempt_count and raises AuthenticationError
     with a remaining-attempts count.
   - Right code -> marks the OTP consumed, fetches the customer, and
     issues a JWT access token.

Both functions commit after every write (the dependency-level connection
wrapper rolls back automatically if anything downstream raises — see
db/connection.py / dependencies.py, same pattern as order_service.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from mysql.connector.pooling import PooledMySQLConnection

from config import settings
from models.auth import RequestOtpOut, VerifyOtpOut
from models.customer import CustomerResponse
from repositories import customer_repository, otp_repository
from utils import jwt_auth
from utils.email import send_otp_email
from utils.exceptions import AuthenticationError, BusinessRuleError
from utils.otp import generate_otp_code, hash_otp_code

logger = logging.getLogger(__name__)


def request_otp(
    conn: PooledMySQLConnection,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> RequestOtpOut:
    """Create (if needed) the customer, then generate and send an OTP.

    Raises
    ------
    BusinessRuleError : new email with no first_name/last_name given, or
                        another OTP was requested too recently.
    ConflictError       : propagated from customer_repository.create on a
                          genuine race (two concurrent signups, same email).
    EmailDeliveryError  : propagated from send_otp_email when SES is
                          enabled and the send fails.
    DatabaseError        : propagated from any repository call.
    """
    customer = customer_repository.get_by_email(conn, email)

    if customer is None:
        if not first_name or not last_name:
            raise BusinessRuleError(
                "NAME_REQUIRED_FOR_SIGNUP",
                "This email isn't registered yet — please provide first_name "
                "and last_name to create an account.",
                detail={"email": email},
            )
        new_customer_id = customer_repository.create(
            conn, first_name=first_name, last_name=last_name, email=email
        )
        conn.commit()
        logger.info("request_otp: created new customer id=%d for %s", new_customer_id, email)

    recent = otp_repository.get_most_recent(conn, email)
    if recent is not None:
        elapsed = (datetime.now() - recent["created_at"]).total_seconds()
        if elapsed < settings.otp_request_cooldown_seconds:
            retry_after = int(settings.otp_request_cooldown_seconds - elapsed)
            raise BusinessRuleError(
                "OTP_REQUEST_TOO_SOON",
                f"Please wait {max(retry_after, 1)} more second(s) before "
                f"requesting another code.",
                detail={"retry_after_seconds": max(retry_after, 1)},
            )

    code = generate_otp_code()
    expires_at = datetime.now() + timedelta(minutes=settings.otp_expiry_minutes)
    otp_repository.create(
        conn, email, hash_otp_code(code), expires_at, max_attempts=settings.otp_max_attempts
    )
    conn.commit()

    # Raises EmailDeliveryError on real failure (SES enabled); logs only in dev mode.
    send_otp_email(email, code)

    return RequestOtpOut(
        message=f"Verification code sent. It expires in {settings.otp_expiry_minutes} minutes.",
        email=email,
        dev_otp_code=None if (settings.is_production or settings.ses_enabled) else code,
    )


def verify_otp(conn: PooledMySQLConnection, email: str, code: str) -> VerifyOtpOut:
    """Verify a submitted code and, on success, issue an access token.

    Raises
    ------
    AuthenticationError : no active OTP for this email, or the code is
                          wrong (message includes remaining attempts), or
                          the matching customer is missing/inactive.
    DatabaseError         : propagated from any repository call.
    """
    otp_row = otp_repository.get_active_for_verification(conn, email)
    if otp_row is None:
        raise AuthenticationError(
            "No active verification code for this email. Please request a new one."
        )

    if hash_otp_code(code) != otp_row["code_hash"]:
        otp_repository.increment_attempt(conn, otp_row["otp_id"])
        conn.commit()
        remaining = otp_row["max_attempts"] - otp_row["attempt_count"] - 1
        raise AuthenticationError(f"Incorrect code. {max(remaining, 0)} attempt(s) remaining.")

    otp_repository.mark_consumed(conn, otp_row["otp_id"])
    conn.commit()

    customer = customer_repository.get_by_email(conn, email)
    if customer is None or not customer["is_active"]:
        raise AuthenticationError("This account is no longer active.")

    token = jwt_auth.create_access_token(customer["customer_id"], email)
    logger.info("verify_otp: login success customer_id=%d", customer["customer_id"])

    return VerifyOtpOut(
        access_token=token,
        expires_in_minutes=settings.jwt_expiry_minutes,
        customer=CustomerResponse(**customer),
    )
