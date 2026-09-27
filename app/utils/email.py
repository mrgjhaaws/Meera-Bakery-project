"""
utils/email.py
================
Sends the OTP login email via AWS SES.

Unlike utils/notifications.py (which is fire-and-forget for order-status
updates — a notification failure must never fail an already-successful
order), OTP delivery IS on the critical path of the login flow: if the
email can't be sent, the person genuinely cannot log in. So send_otp_email
DOES raise on failure — auth_service turns that into a clear HTTP 502
rather than silently pretending the code went out.

Dev-mode fallback
-------------------
When settings.ses_enabled is False (the default), no AWS call is made at
all — the code is just logged. This lets you build and test the entire
login flow locally with zero AWS setup. auth_service additionally returns
the code directly in the API response when the app is NOT running in
production (see models/auth.py's dev_otp_code field), so you can log in
without even reading server logs.

Why SES instead of SNS for this
-----------------------------------
SES has a genuinely useful free tier: 62,000 emails/month when sent from
an EC2 instance. SNS SMS has no free tier at all — it's pay-per-message
from the first text. That's the whole reason order notifications (SNS,
see utils/notifications.py) and login (SES, here) use different AWS
services.

Real-world setup notes
-------------------------
- SES starts every new AWS account in a sandbox: you can only send TO
  addresses you've manually verified in the SES console, until you request
  production access.
- The FROM address (settings.ses_sender_email) must itself be a verified
  SES identity — either that single address, or the whole sending domain.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import settings
from utils.exceptions import EmailDeliveryError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_ses_client():
    """Lazily create (and cache) the boto3 SES client.

    On EC2 this picks up credentials from the instance's IAM role
    automatically — no access keys are read from .env or anywhere else in
    this codebase (same pattern as utils/notifications.py's SNS client).
    """
    return boto3.client("ses", region_name=settings.aws_region)


def send_otp_email(to_email: str, code: str) -> None:
    """Send the OTP login email.

    In dev mode (settings.ses_enabled=False), this only logs the code —
    see module docstring. It never raises in that mode.

    Raises
    ------
    EmailDeliveryError : SES is enabled but the send failed (bad sender
                          identity, sandbox restriction, throttling,
                          network error, or anything else from SES).
    """
    if not settings.ses_enabled:
        logger.info("[DEV MODE — SES disabled] OTP for %s is %s", to_email, code)
        return

    subject = "Your Meera Bakery login code"
    body_text = (
        f"Your Meera Bakery verification code is: {code}\n\n"
        f"This code expires in {settings.otp_expiry_minutes} minutes. "
        f"If you didn't request this, you can safely ignore this email."
    )

    try:
        client = _get_ses_client()
        client.send_email(
            Source=settings.ses_sender_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            },
        )
        logger.info("OTP email sent to %s", to_email)
    except (BotoCoreError, ClientError) as exc:
        logger.error("SES send_email failed for %s: %s", to_email, exc)
        raise EmailDeliveryError(to_email) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error sending OTP email to %s: %s", to_email, exc)
        raise EmailDeliveryError(to_email) from exc
