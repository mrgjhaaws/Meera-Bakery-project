"""
utils/notifications.py
========================
Best-effort order notifications via AWS SNS.

Two channels, both through the same boto3 SNS client:

- Direct-to-phone SMS: client.publish(PhoneNumber=..., Message=...).
  No topic or subscription needed — SNS sends straight to the number.
  Used for order-placed / order-status-changed messages to the customer.

- Topic-based publish: client.publish(TopicArn=..., Subject=..., Message=...).
  Used for a shared "bakery admin" topic (e.g. low-stock alerts) that has
  an email (or SMS) subscription attached in the SNS console.

Design decisions
-----------------
- Notifications are OFF by default (settings.sns_notifications_enabled).
  This keeps local dev and the test suite free of any AWS calls unless
  you've deliberately set up SNS and opted in via .env.
- Every public function swallows all exceptions and logs a warning instead
  of raising. A notification failure (bad phone number, SNS sandbox
  restriction, missing IAM permission, network blip) must never fail the
  order request — the order is already committed to the database by the
  time we try to notify.
- No AWS access keys are read from .env or anywhere in this codebase. On
  EC2, boto3 picks up credentials automatically from the instance's IAM
  role (see the IAM policy in the setup notes below). Locally, boto3 falls
  back to your AWS CLI profile if you have one configured — or
  notifications simply stay disabled, which is fine since they're not
  required for the app to function.

Real-world caveats (read before enabling in production)
-----------------------------------------------------------
- New AWS accounts start in the SNS "SMS sandbox" and can only send SMS to
  phone numbers you've manually verified in the SNS console. Request
  production access to lift this.
- SMS to Indian phone numbers is additionally subject to TRAI's DLT
  (Distributed Ledger Technology) regulations — carriers typically filter
  messages from an unregistered sender/template regardless of what AWS
  reports back. Until you've completed DLT registration, prefer the
  topic-based channel (publish_to_topic) with an email subscription, which
  has no such restriction.

Public interface
------------------
    notify_order_placed(phone_number, order_id, total_amount) -> None
    notify_order_status_changed(phone_number, order_id, status) -> None
    publish_to_topic(subject, message, topic_arn=None) -> None
"""

from __future__ import annotations

import logging
from decimal import Decimal
from functools import lru_cache
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_sns_client():
    """Lazily create (and cache) the boto3 SNS client.

    On EC2 this picks up credentials from the instance's IAM role
    automatically — no access keys are read from .env or anywhere else in
    this codebase. Cached with lru_cache so we don't rebuild the client on
    every notification.
    """
    return boto3.client("sns", region_name=settings.aws_region)


def _publish_sms(phone_number: str, message: str) -> None:
    if not settings.sns_notifications_enabled:
        logger.debug("SNS notifications disabled — skipping SMS to %s", phone_number)
        return
    try:
        client = _get_sns_client()
        client.publish(
            PhoneNumber=phone_number,
            Message=message,
            MessageAttributes={
                "AWS.SNS.SMS.SMSType": {
                    "DataType": "String",
                    "StringValue": "Transactional",
                }
            },
        )
        logger.info("SNS SMS sent to %s", phone_number)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("SNS SMS failed for %s: %s", phone_number, exc)
    except Exception as exc:  # pragma: no cover - defensive, must never bubble up
        logger.warning("Unexpected error sending SNS SMS to %s: %s", phone_number, exc)


def publish_to_topic(subject: str, message: str, topic_arn: Optional[str] = None) -> None:
    """Publish to an SNS topic (e.g. the bakery-admin topic for low-stock alerts).

    Falls back to settings.sns_admin_topic_arn if topic_arn isn't given.
    A no-op (with a warning log) if notifications are disabled or no ARN
    is configured — never raises.
    """
    if not settings.sns_notifications_enabled:
        logger.debug("SNS notifications disabled — skipping topic publish: %s", subject)
        return
    arn = topic_arn or settings.sns_admin_topic_arn
    if not arn:
        logger.warning("publish_to_topic called with no topic ARN configured — skipping.")
        return
    try:
        client = _get_sns_client()
        client.publish(TopicArn=arn, Subject=subject[:100], Message=message)
        logger.info("SNS topic publish OK: %s", subject)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("SNS topic publish failed (%s): %s", subject, exc)
    except Exception as exc:  # pragma: no cover
        logger.warning("Unexpected error publishing to SNS topic: %s", exc)


def notify_order_placed(phone_number: Optional[str], order_id: int, total_amount: Decimal) -> None:
    """Fire-and-forget SMS to the customer confirming their new order."""
    if not phone_number:
        logger.debug("notify_order_placed: no phone number on file for order %d", order_id)
        return
    message = (
        f"Meera Bakery: Thanks for your order #{order_id}! "
        f"Total: Rs.{total_amount}. We'll notify you as it's prepared."
    )
    _publish_sms(phone_number, message)


def notify_order_status_changed(phone_number: Optional[str], order_id: int, status: str) -> None:
    """Fire-and-forget SMS to the customer when their order's status changes."""
    if not phone_number:
        logger.debug("notify_order_status_changed: no phone number on file for order %d", order_id)
        return
    friendly = {
        "confirmed": "has been confirmed and is being prepared",
        "preparing": "is being freshly prepared",
        "shipped": "is on its way to you",
        "delivered": "has been delivered. Enjoy!",
        "cancelled": "has been cancelled",
    }.get(status, f"is now '{status}'")
    message = f"Meera Bakery: Your order #{order_id} {friendly}."
    _publish_sms(phone_number, message)


def notify_out_of_stock(phone, order_id, product_name, requested, available):
    if not settings.sns_notifications_enabled:
        return

    message = (
        f"Meera Bakery: Order #{order_id} cannot be confirmed. "
        f"{product_name} is out of stock. "
        f"Requested: {requested}, Available: {available}."
    )

    try:
        sns = boto3.client("sns", region_name=settings.aws_region)

        sns.publish(
            PhoneNumber=phone,
            Message=message
        )

        logger.info(
            "Out-of-stock SMS sent for order #%s to customer",
            order_id
        )

    except Exception as exc:
        logger.warning(
            "Failed to send out-of-stock SMS for order #%s: %s",
            order_id,
            exc
        )