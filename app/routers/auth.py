"""
routers/auth.py
=================
FastAPI router for OTP-based email login.

POST /api/v1/auth/request-otp
    Sends (or logs, in dev mode) a 6-digit code to the given email.
    Auto-creates a customer record on the first-ever request for a new
    email (first_name/last_name required in that case).

POST /api/v1/auth/verify-otp
    Verifies the code and returns a JWT access token + the customer record.

GET /api/v1/auth/me
    Returns the customer identified by the current Bearer token. Send
    "Authorization: Bearer <access_token>" from POST /auth/verify-otp.

Router rules (consistent with Phases 2-4)
--------------------------------------------
- Handlers are thin: validate the body, call the service, return.
- No SQL or business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from mysql.connector.pooling import PooledMySQLConnection

from dependencies import get_current_customer, get_db
from models.auth import RequestOtpIn, RequestOtpOut, VerifyOtpIn, VerifyOtpOut
from models.customer import CustomerResponse
from services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/request-otp",
    response_model=RequestOtpOut,
    summary="Request a login code",
    description=(
        "Sends a 6-digit verification code to the given email via AWS SES. "
        "If no account exists for this email yet, first_name and last_name "
        "are required and a new customer record is created immediately."
    ),
)
def request_otp(
    payload: RequestOtpIn,
    conn: PooledMySQLConnection = Depends(get_db),
) -> RequestOtpOut:
    return auth_service.request_otp(conn, payload.email, payload.first_name, payload.last_name)


@router.post(
    "/verify-otp",
    response_model=VerifyOtpOut,
    summary="Verify code and log in",
    description=(
        "Verifies the 6-digit code and, on success, returns a Bearer "
        "access token plus the customer record. Use the token in an "
        "'Authorization: Bearer <token>' header for GET /auth/me."
    ),
)
def verify_otp(
    payload: VerifyOtpIn,
    conn: PooledMySQLConnection = Depends(get_db),
) -> VerifyOtpOut:
    return auth_service.verify_otp(conn, payload.email, payload.code)


@router.get(
    "/me",
    response_model=CustomerResponse,
    summary="Current logged-in customer",
    description="Returns the customer identified by the current Bearer access token.",
)
def me(
    customer: CustomerResponse = Depends(get_current_customer),
) -> CustomerResponse:
    return customer
