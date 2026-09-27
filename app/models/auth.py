"""
models/auth.py
================
Pydantic request/response models for the OTP email-login flow.

See services/auth_service.py for the full flow, and utils/email.py for why
this uses email (via AWS SES) rather than SMS (via AWS SNS) — SES has a
usable free tier, SNS SMS doesn't.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from models.customer import CustomerResponse


class RequestOtpIn(BaseModel):
    """POST /auth/request-otp request body."""

    email: EmailStr = Field(..., examples=["asha.rao@example.com"])
    first_name: Optional[str] = Field(
        None,
        max_length=80,
        description="Required only the first time this email logs in (new account).",
        examples=["Asha"],
    )
    last_name: Optional[str] = Field(
        None, max_length=80, description="Required only for a new account.", examples=["Rao"]
    )


class RequestOtpOut(BaseModel):
    """POST /auth/request-otp response body."""

    message: str = Field(..., examples=["Verification code sent. It expires in 10 minutes."])
    email: str = Field(..., examples=["asha.rao@example.com"])
    dev_otp_code: Optional[str] = Field(
        None,
        description="Only populated outside production when SES is disabled — "
                    "lets you log in during local development without reading "
                    "server logs. Always null when SES is enabled or in production.",
        examples=[None],
    )


class VerifyOtpIn(BaseModel):
    """POST /auth/verify-otp request body."""

    email: EmailStr = Field(..., examples=["asha.rao@example.com"])
    code: str = Field(
        ..., min_length=6, max_length=6, pattern=r"^\d{6}$", examples=["042817"]
    )


class VerifyOtpOut(BaseModel):
    """POST /auth/verify-otp response body — a fresh session for the customer."""

    access_token: str = Field(..., description="Bearer token for Authorization headers")
    token_type: str = Field(default="bearer")
    expires_in_minutes: int = Field(..., examples=[10080])
    customer: CustomerResponse
