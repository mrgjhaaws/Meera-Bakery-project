"""
tests/test_auth.py
====================
Unit tests for the OTP email-login system:
    - utils/otp.py            (code generation/hashing)
    - utils/jwt_auth.py       (token issue/verify)
    - utils/email.py          (SES dev-mode fallback + failure handling)
    - repositories/otp_repository.py
    - repositories/customer_repository.py (get_by_email, create)
    - services/auth_service.py (request_otp, verify_otp)
    - dependencies.get_current_customer

Strategy
--------
- No real database, no real AWS calls — everything mocked.
- settings is patched per-test rather than mutated globally, so tests
  never leak configuration into each other.

Run with:
    cd C:\\MeeraBakery\\app
    pytest tests/test_auth.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from mysql.connector import Error as MySQLError

import dependencies
from repositories import customer_repository, otp_repository
from services import auth_service
from utils import jwt_auth, otp
from utils.email import send_otp_email
from utils.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    DatabaseError,
)


def _make_conn(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# =============================================================================
# utils/otp.py
# =============================================================================

class TestOtpHelpers:

    def test_generate_otp_code_is_six_digits(self):
        for _ in range(20):
            code = otp.generate_otp_code()
            assert len(code) == 6
            assert code.isdigit()

    def test_hash_is_deterministic_and_sha256_length(self):
        h1 = otp.hash_otp_code("042817")
        h2 = otp.hash_otp_code("042817")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_codes_hash_differently(self):
        assert otp.hash_otp_code("111111") != otp.hash_otp_code("222222")


# =============================================================================
# utils/jwt_auth.py
# =============================================================================

class TestJwtAuth:

    @patch("utils.jwt_auth.settings")
    def test_round_trip(self, mock_settings):
        mock_settings.jwt_secret_key = "test-secret"
        mock_settings.jwt_expiry_minutes = 10

        token = jwt_auth.create_access_token(7, "asha@example.com")
        payload = jwt_auth.decode_access_token(token)

        assert payload["sub"] == "7"
        assert payload["email"] == "asha@example.com"

    @patch("utils.jwt_auth.settings")
    def test_expired_token_raises(self, mock_settings):
        mock_settings.jwt_secret_key = "test-secret"
        mock_settings.jwt_expiry_minutes = -1  # already expired

        token = jwt_auth.create_access_token(7, "asha@example.com")
        with pytest.raises(jwt_auth.InvalidTokenException):
            jwt_auth.decode_access_token(token)

    @patch("utils.jwt_auth.settings")
    def test_wrong_secret_raises(self, mock_settings):
        mock_settings.jwt_secret_key = "secret-a"
        mock_settings.jwt_expiry_minutes = 10
        token = jwt_auth.create_access_token(7, "asha@example.com")

        mock_settings.jwt_secret_key = "secret-b"
        with pytest.raises(jwt_auth.InvalidTokenException):
            jwt_auth.decode_access_token(token)

    def test_garbage_token_raises(self):
        with pytest.raises(jwt_auth.InvalidTokenException):
            jwt_auth.decode_access_token("not-a-real-token")


# =============================================================================
# utils/email.py
# =============================================================================

class TestSendOtpEmail:

    @patch("utils.email.settings")
    @patch("utils.email._get_ses_client")
    def test_dev_mode_never_calls_ses(self, mock_get_client, mock_settings):
        mock_settings.ses_enabled = False
        send_otp_email("asha@example.com", "042817")
        mock_get_client.assert_not_called()

    @patch("utils.email.settings")
    @patch("utils.email._get_ses_client")
    def test_sends_via_ses_when_enabled(self, mock_get_client, mock_settings):
        mock_settings.ses_enabled = True
        mock_settings.ses_sender_email = "no-reply@meerabakery.example"
        mock_settings.otp_expiry_minutes = 10
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        send_otp_email("asha@example.com", "042817")

        mock_client.send_email.assert_called_once()
        kwargs = mock_client.send_email.call_args.kwargs
        assert kwargs["Destination"]["ToAddresses"] == ["asha@example.com"]
        assert "042817" in kwargs["Message"]["Body"]["Text"]["Data"]

    @patch("utils.email.settings")
    @patch("utils.email._get_ses_client")
    def test_ses_failure_raises_email_delivery_error(self, mock_get_client, mock_settings):
        from utils.exceptions import EmailDeliveryError

        mock_settings.ses_enabled = True
        mock_settings.ses_sender_email = "no-reply@meerabakery.example"
        mock_client = MagicMock()
        mock_client.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "bad"}}, "SendEmail"
        )
        mock_get_client.return_value = mock_client

        with pytest.raises(EmailDeliveryError):
            send_otp_email("asha@example.com", "042817")


# =============================================================================
# repositories/otp_repository.py
# =============================================================================

class TestOtpRepository:

    def test_create_returns_new_id(self):
        cursor = MagicMock()
        cursor.lastrowid = 5
        conn = _make_conn(cursor)

        otp_id = otp_repository.create(conn, "a@x.com", "hash", datetime.now(), max_attempts=5)
        assert otp_id == 5

    def test_get_active_for_verification_filters_correctly(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "otp_id": 1, "email": "a@x.com", "code_hash": "h",
            "attempt_count": 0, "max_attempts": 5, "expires_at": datetime.now(),
        }
        conn = _make_conn(cursor)

        row = otp_repository.get_active_for_verification(conn, "a@x.com")
        sql = cursor.execute.call_args.args[0]
        assert "consumed_at IS NULL" in sql
        assert "expires_at > NOW()" in sql
        assert "attempt_count < max_attempts" in sql
        assert row["otp_id"] == 1

    def test_get_active_returns_none_when_no_row(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = _make_conn(cursor)
        assert otp_repository.get_active_for_verification(conn, "a@x.com") is None

    def test_increment_attempt_and_mark_consumed(self):
        cursor = MagicMock()
        conn = _make_conn(cursor)
        otp_repository.increment_attempt(conn, 1)
        otp_repository.mark_consumed(conn, 1)
        assert cursor.execute.call_count == 2

    def test_database_error_on_mysql_error(self):
        cursor = MagicMock()
        cursor.execute.side_effect = MySQLError("boom")
        conn = _make_conn(cursor)
        with pytest.raises(DatabaseError):
            otp_repository.create(conn, "a@x.com", "hash", datetime.now())


# =============================================================================
# repositories/customer_repository.py additions
# =============================================================================

class TestCustomerRepositoryEmailAuth:

    def test_get_by_email_found(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "customer_id": 1, "first_name": "Asha", "last_name": "Rao",
            "email": "asha@x.com", "phone": None, "is_active": 1,
            "created_at": datetime.now(), "updated_at": datetime.now(),
        }
        conn = _make_conn(cursor)
        row = customer_repository.get_by_email(conn, "asha@x.com")
        assert row["is_active"] is True

    def test_get_by_email_not_found_returns_none(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = _make_conn(cursor)
        assert customer_repository.get_by_email(conn, "nobody@x.com") is None

    def test_create_returns_new_id(self):
        cursor = MagicMock()
        cursor.lastrowid = 42
        conn = _make_conn(cursor)
        new_id = customer_repository.create(
            conn, first_name="Asha", last_name="Rao", email="asha@x.com"
        )
        assert new_id == 42

    def test_create_duplicate_email_raises_conflict(self):
        cursor = MagicMock()
        err = MySQLError("Duplicate entry")
        err.errno = 1062
        cursor.execute.side_effect = err
        conn = _make_conn(cursor)
        with pytest.raises(ConflictError):
            customer_repository.create(
                conn, first_name="Asha", last_name="Rao", email="asha@x.com"
            )


# =============================================================================
# services/auth_service.py
# =============================================================================

_EXISTING_CUSTOMER = {
    "customer_id": 1, "first_name": "Asha", "last_name": "Rao",
    "email": "asha@x.com", "phone": None, "is_active": True,
    "created_at": datetime.now(), "updated_at": datetime.now(),
}


class TestRequestOtp:

    @patch("services.auth_service.send_otp_email")
    @patch("services.auth_service.otp_repository")
    @patch("services.auth_service.customer_repository")
    def test_existing_customer_no_name_required(
        self, mock_customer_repo, mock_otp_repo, mock_send_email
    ):
        mock_customer_repo.get_by_email.return_value = _EXISTING_CUSTOMER
        mock_otp_repo.get_most_recent.return_value = None
        conn = MagicMock()

        result = auth_service.request_otp(conn, "asha@x.com")

        mock_customer_repo.create.assert_not_called()
        mock_otp_repo.create.assert_called_once()
        mock_send_email.assert_called_once()
        assert result.email == "asha@x.com"

    @patch("services.auth_service.customer_repository")
    def test_new_email_without_name_raises(self, mock_customer_repo):
        mock_customer_repo.get_by_email.return_value = None
        conn = MagicMock()

        with pytest.raises(BusinessRuleError) as exc_info:
            auth_service.request_otp(conn, "new@x.com")
        assert exc_info.value.error_code == "NAME_REQUIRED_FOR_SIGNUP"

    @patch("services.auth_service.send_otp_email")
    @patch("services.auth_service.otp_repository")
    @patch("services.auth_service.customer_repository")
    def test_new_email_with_name_creates_customer(
        self, mock_customer_repo, mock_otp_repo, mock_send_email
    ):
        mock_customer_repo.get_by_email.return_value = None
        mock_customer_repo.create.return_value = 99
        mock_otp_repo.get_most_recent.return_value = None
        conn = MagicMock()

        auth_service.request_otp(conn, "new@x.com", first_name="Nina", last_name="Iyer")

        mock_customer_repo.create.assert_called_once_with(
            conn, first_name="Nina", last_name="Iyer", email="new@x.com"
        )
        conn.commit.assert_called()

    @patch("services.auth_service.otp_repository")
    @patch("services.auth_service.customer_repository")
    def test_cooldown_blocks_rapid_requests(self, mock_customer_repo, mock_otp_repo):
        mock_customer_repo.get_by_email.return_value = _EXISTING_CUSTOMER
        mock_otp_repo.get_most_recent.return_value = {
            "otp_id": 1, "email": "asha@x.com", "created_at": datetime.now()
        }
        conn = MagicMock()

        with pytest.raises(BusinessRuleError) as exc_info:
            auth_service.request_otp(conn, "asha@x.com")
        assert exc_info.value.error_code == "OTP_REQUEST_TOO_SOON"

    @patch("services.auth_service.otp_repository")
    @patch("services.auth_service.customer_repository")
    def test_cooldown_elapsed_allows_request(self, mock_customer_repo, mock_otp_repo):
        mock_customer_repo.get_by_email.return_value = _EXISTING_CUSTOMER
        mock_otp_repo.get_most_recent.return_value = {
            "otp_id": 1, "email": "asha@x.com",
            "created_at": datetime.now() - timedelta(minutes=5),
        }
        conn = MagicMock()

        with patch("services.auth_service.send_otp_email"):
            result = auth_service.request_otp(conn, "asha@x.com")
        assert result.email == "asha@x.com"

    @patch("services.auth_service.settings")
    @patch("services.auth_service.send_otp_email")
    @patch("services.auth_service.otp_repository")
    @patch("services.auth_service.customer_repository")
    def test_dev_otp_code_populated_when_ses_disabled_and_not_production(
        self, mock_customer_repo, mock_otp_repo, mock_send_email, mock_settings
    ):
        mock_customer_repo.get_by_email.return_value = _EXISTING_CUSTOMER
        mock_otp_repo.get_most_recent.return_value = None
        mock_settings.is_production = False
        mock_settings.ses_enabled = False
        mock_settings.otp_expiry_minutes = 10
        mock_settings.otp_max_attempts = 5
        conn = MagicMock()

        result = auth_service.request_otp(conn, "asha@x.com")
        assert result.dev_otp_code is not None
        assert len(result.dev_otp_code) == 6

    @patch("services.auth_service.settings")
    @patch("services.auth_service.send_otp_email")
    @patch("services.auth_service.otp_repository")
    @patch("services.auth_service.customer_repository")
    def test_dev_otp_code_hidden_in_production(
        self, mock_customer_repo, mock_otp_repo, mock_send_email, mock_settings
    ):
        mock_customer_repo.get_by_email.return_value = _EXISTING_CUSTOMER
        mock_otp_repo.get_most_recent.return_value = None
        mock_settings.is_production = True
        mock_settings.ses_enabled = False
        mock_settings.otp_expiry_minutes = 10
        mock_settings.otp_max_attempts = 5
        conn = MagicMock()

        result = auth_service.request_otp(conn, "asha@x.com")
        assert result.dev_otp_code is None


class TestVerifyOtp:

    @patch("services.auth_service.customer_repository")
    @patch("services.auth_service.otp_repository")
    def test_no_active_otp_raises(self, mock_otp_repo, mock_customer_repo):
        mock_otp_repo.get_active_for_verification.return_value = None
        conn = MagicMock()

        with pytest.raises(AuthenticationError):
            auth_service.verify_otp(conn, "asha@x.com", "042817")

    @patch("services.auth_service.customer_repository")
    @patch("services.auth_service.otp_repository")
    def test_wrong_code_increments_attempt_and_raises(self, mock_otp_repo, mock_customer_repo):
        mock_otp_repo.get_active_for_verification.return_value = {
            "otp_id": 1, "code_hash": otp.hash_otp_code("111111"),
            "attempt_count": 0, "max_attempts": 5,
        }
        conn = MagicMock()

        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.verify_otp(conn, "asha@x.com", "999999")

        mock_otp_repo.increment_attempt.assert_called_once_with(conn, 1)
        assert "4 attempt" in exc_info.value.message

    @patch("services.auth_service.jwt_auth")
    @patch("services.auth_service.customer_repository")
    @patch("services.auth_service.otp_repository")
    def test_correct_code_issues_token(self, mock_otp_repo, mock_customer_repo, mock_jwt):
        code = "042817"
        mock_otp_repo.get_active_for_verification.return_value = {
            "otp_id": 1, "code_hash": otp.hash_otp_code(code),
            "attempt_count": 0, "max_attempts": 5,
        }
        mock_customer_repo.get_by_email.return_value = _EXISTING_CUSTOMER
        mock_jwt.create_access_token.return_value = "signed.jwt.token"
        conn = MagicMock()

        result = auth_service.verify_otp(conn, "asha@x.com", code)

        mock_otp_repo.mark_consumed.assert_called_once_with(conn, 1)
        assert result.access_token == "signed.jwt.token"
        assert result.customer.email == "asha@x.com"

    @patch("services.auth_service.customer_repository")
    @patch("services.auth_service.otp_repository")
    def test_inactive_customer_blocked_even_with_right_code(
        self, mock_otp_repo, mock_customer_repo
    ):
        code = "042817"
        mock_otp_repo.get_active_for_verification.return_value = {
            "otp_id": 1, "code_hash": otp.hash_otp_code(code),
            "attempt_count": 0, "max_attempts": 5,
        }
        mock_customer_repo.get_by_email.return_value = {**_EXISTING_CUSTOMER, "is_active": False}
        conn = MagicMock()

        with pytest.raises(AuthenticationError):
            auth_service.verify_otp(conn, "asha@x.com", code)


# =============================================================================
# dependencies.get_current_customer
# =============================================================================

class TestGetCurrentCustomer:

    def test_missing_credentials_raises(self):
        conn = MagicMock()
        with pytest.raises(AuthenticationError):
            dependencies.get_current_customer(credentials=None, conn=conn)

    @patch("utils.jwt_auth.decode_access_token")
    def test_invalid_token_raises(self, mock_decode):
        mock_decode.side_effect = jwt_auth.InvalidTokenException("bad token")
        creds = MagicMock()
        creds.credentials = "garbage"
        conn = MagicMock()

        with pytest.raises(AuthenticationError):
            dependencies.get_current_customer(credentials=creds, conn=conn)

    @patch("repositories.customer_repository.get_by_id")
    @patch("utils.jwt_auth.decode_access_token")
    def test_valid_token_returns_customer(self, mock_decode, mock_get_by_id):
        mock_decode.return_value = {"sub": "1", "email": "asha@x.com"}
        mock_get_by_id.return_value = _EXISTING_CUSTOMER
        creds = MagicMock()
        creds.credentials = "valid.jwt.token"
        conn = MagicMock()

        customer = dependencies.get_current_customer(credentials=creds, conn=conn)
        assert customer.customer_id == 1

    @patch("repositories.customer_repository.get_by_id")
    @patch("utils.jwt_auth.decode_access_token")
    def test_inactive_customer_raises(self, mock_decode, mock_get_by_id):
        mock_decode.return_value = {"sub": "1", "email": "asha@x.com"}
        mock_get_by_id.return_value = {**_EXISTING_CUSTOMER, "is_active": False}
        creds = MagicMock()
        creds.credentials = "valid.jwt.token"
        conn = MagicMock()

        with pytest.raises(AuthenticationError):
            dependencies.get_current_customer(credentials=creds, conn=conn)

    @patch("repositories.customer_repository.get_by_id")
    @patch("utils.jwt_auth.decode_access_token")
    def test_deleted_customer_maps_to_401_not_404(self, mock_decode, mock_get_by_id):
        from utils.exceptions import NotFoundError

        mock_decode.return_value = {"sub": "999", "email": "gone@x.com"}
        mock_get_by_id.side_effect = NotFoundError("customer", 999)
        creds = MagicMock()
        creds.credentials = "valid.jwt.token"
        conn = MagicMock()

        with pytest.raises(AuthenticationError):
            dependencies.get_current_customer(credentials=creds, conn=conn)
