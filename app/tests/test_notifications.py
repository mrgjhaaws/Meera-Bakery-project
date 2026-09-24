"""
tests/test_notifications.py
=============================
Unit tests for utils/notifications.py.

Strategy
--------
- No real AWS calls — boto3.client is patched everywhere.
- Verifies the master off-switch (sns_notifications_enabled) is respected,
  that publish failures never raise, and that message content is sensible.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from utils import notifications


def _client_error():
    return ClientError(
        {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}}, "Publish"
    )


class TestNotifyOrderPlaced:

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_sends_sms_when_enabled(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        notifications.notify_order_placed("+919876543210", 42, Decimal("236.00"))

        mock_client.publish.assert_called_once()
        kwargs = mock_client.publish.call_args.kwargs
        assert kwargs["PhoneNumber"] == "+919876543210"
        assert "#42" in kwargs["Message"]
        assert "236.00" in kwargs["Message"]

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_noop_when_disabled(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = False

        notifications.notify_order_placed("+919876543210", 42, Decimal("236.00"))

        mock_get_client.assert_not_called()

    @patch("utils.notifications.settings")
    def test_noop_when_no_phone_number(self, mock_settings):
        mock_settings.sns_notifications_enabled = True
        # Should return immediately without even checking settings/client further
        notifications.notify_order_placed(None, 42, Decimal("236.00"))
        notifications.notify_order_placed("", 42, Decimal("236.00"))

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_publish_failure_never_raises(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_client = MagicMock()
        mock_client.publish.side_effect = _client_error()
        mock_get_client.return_value = mock_client

        # Must not raise
        notifications.notify_order_placed("+919876543210", 42, Decimal("236.00"))

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_unexpected_exception_never_raises(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_get_client.side_effect = RuntimeError("boom")

        # Must not raise even for a completely unexpected error
        notifications.notify_order_placed("+919876543210", 42, Decimal("236.00"))


class TestNotifyOrderStatusChanged:

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_sends_friendly_message_per_status(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        notifications.notify_order_status_changed("+919876543210", 7, "shipped")

        message = mock_client.publish.call_args.kwargs["Message"]
        assert "#7" in message
        assert "on its way" in message

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_unknown_status_falls_back_to_generic_message(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        notifications.notify_order_status_changed("+919876543210", 7, "on_hold")

        message = mock_client.publish.call_args.kwargs["Message"]
        assert "on_hold" in message

    @patch("utils.notifications.settings")
    def test_noop_when_no_phone_number(self, mock_settings):
        mock_settings.sns_notifications_enabled = True
        notifications.notify_order_status_changed(None, 7, "shipped")


class TestPublishToTopic:

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_publishes_with_explicit_arn(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        notifications.publish_to_topic("Low stock", "Butter Croissant is low", topic_arn="arn:aws:sns:x:y:topic")

        mock_client.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:x:y:topic", Subject="Low stock", Message="Butter Croissant is low"
        )

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_falls_back_to_configured_admin_topic(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_settings.sns_admin_topic_arn = "arn:aws:sns:x:y:admin-topic"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        notifications.publish_to_topic("Low stock", "message")

        assert mock_client.publish.call_args.kwargs["TopicArn"] == "arn:aws:sns:x:y:admin-topic"

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_noop_when_no_arn_available(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_settings.sns_admin_topic_arn = ""

        notifications.publish_to_topic("Low stock", "message")

        mock_get_client.assert_not_called()

    @patch("utils.notifications.settings")
    def test_noop_when_disabled(self, mock_settings):
        mock_settings.sns_notifications_enabled = False
        notifications.publish_to_topic("Low stock", "message", topic_arn="arn:aws:sns:x:y:topic")

    @patch("utils.notifications.settings")
    @patch("utils.notifications._get_sns_client")
    def test_publish_failure_never_raises(self, mock_get_client, mock_settings):
        mock_settings.sns_notifications_enabled = True
        mock_client = MagicMock()
        mock_client.publish.side_effect = _client_error()
        mock_get_client.return_value = mock_client

        notifications.publish_to_topic("Low stock", "message", topic_arn="arn:aws:sns:x:y:topic")
