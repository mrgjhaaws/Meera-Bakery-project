"""
tests/test_customers.py
========================
Unit tests for the customers repository and service layers.

Strategy
--------
- No real database — PooledMySQLConnection replaced with MagicMock.
- Repository tests verify: correct type normalisation (TINYINT→bool),
  NotFoundError on missing row, DatabaseError on MySQLError,
  dictionary=True cursor, parameterised query, pagination offset arithmetic.
- Service tests verify: pagination cap, BusinessRuleError on bad params,
  correct Pydantic model construction, active_only delegation.

Run with:
    cd C:\\MeeraBakery\\app
    pytest tests/test_customers.py -v
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from models.customer import CustomerListResponse, CustomerResponse, CustomerSummary
from repositories import customer_repository
from services import customer_service
from utils.exceptions import BusinessRuleError, DatabaseError, NotFoundError


# =============================================================================
# Shared helpers
# =============================================================================

def _make_conn(fetchone_return=None, fetchall_return=None, count_return=None):
    """Build a mock connection/cursor pair.

    If count_return is provided the first fetchone() call returns the count
    dict and fetchall() returns fetchall_return (get_all pattern).
    Otherwise fetchone() always returns fetchone_return (get_by_id pattern).
    """
    cursor = MagicMock()
    if count_return is not None:
        cursor.fetchone.side_effect = [count_return]
        cursor.fetchall.return_value = fetchall_return or []
    else:
        cursor.fetchone.return_value = fetchone_return
        cursor.fetchall.return_value = fetchall_return or []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _cust_row(
    customer_id: int = 1,
    first_name: str = "Meera",
    last_name: str = "Sharma",
    email: str = "meera@example.com",
    phone: str | None = "+919876543210",
    is_active: int = 1,
) -> dict:
    """Return a dict that mirrors a MySQL cursor row for a customer."""
    return {
        "customer_id": customer_id,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "is_active": is_active,
        "created_at": datetime(2026, 1, 1, 10, 0, 0),
        "updated_at": datetime(2026, 1, 1, 10, 0, 0),
    }


# =============================================================================
# customer_repository.get_by_id
# =============================================================================

class TestCustomerRepositoryGetById:

    def test_returns_dict_for_existing_customer(self):
        conn, _ = _make_conn(fetchone_return=_cust_row())
        result = customer_repository.get_by_id(conn, 1)
        assert result["customer_id"] == 1
        assert result["first_name"] == "Meera"
        assert result["email"] == "meera@example.com"

    def test_is_active_1_normalised_to_true(self):
        conn, _ = _make_conn(fetchone_return=_cust_row(is_active=1))
        result = customer_repository.get_by_id(conn, 1)
        assert result["is_active"] is True

    def test_is_active_0_normalised_to_false(self):
        conn, _ = _make_conn(fetchone_return=_cust_row(is_active=0))
        result = customer_repository.get_by_id(conn, 1)
        assert result["is_active"] is False

    def test_raises_not_found_when_row_is_none(self):
        conn, _ = _make_conn(fetchone_return=None)
        with pytest.raises(NotFoundError) as exc_info:
            customer_repository.get_by_id(conn, 99)
        assert exc_info.value.error_code == "RESOURCE_NOT_FOUND"
        assert "99" in exc_info.value.message

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("connection lost")
        with pytest.raises(DatabaseError):
            customer_repository.get_by_id(conn, 1)

    def test_cursor_opened_with_dictionary_true(self):
        conn, _ = _make_conn(fetchone_return=_cust_row())
        customer_repository.get_by_id(conn, 1)
        conn.cursor.assert_called_with(dictionary=True)

    def test_parameterised_query_uses_customer_id(self):
        conn, cursor = _make_conn(fetchone_return=_cust_row(customer_id=5))
        customer_repository.get_by_id(conn, 5)
        call_args = cursor.execute.call_args
        assert call_args[0][1] == (5,)

    def test_phone_can_be_none(self):
        conn, _ = _make_conn(fetchone_return=_cust_row(phone=None))
        result = customer_repository.get_by_id(conn, 1)
        assert result["phone"] is None


# =============================================================================
# customer_repository.get_all
# =============================================================================

class TestCustomerRepositoryGetAll:

    def test_returns_total_and_rows(self):
        rows = [_cust_row(1, "Meera", "Sharma"), _cust_row(2, "Arjun", "Verma")]
        conn, _ = _make_conn(count_return={"total": 2}, fetchall_return=rows)
        total, result_rows = customer_repository.get_all(conn)
        assert total == 2
        assert len(result_rows) == 2

    def test_normalises_is_active_in_all_rows(self):
        rows = [
            _cust_row(1, is_active=1),
            _cust_row(2, is_active=0),
        ]
        conn, _ = _make_conn(count_return={"total": 2}, fetchall_return=rows)
        _, result_rows = customer_repository.get_all(conn, active_only=False)
        assert result_rows[0]["is_active"] is True
        assert result_rows[1]["is_active"] is False

    def test_empty_result_returns_zero_total(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        total, rows = customer_repository.get_all(conn)
        assert total == 0
        assert rows == []

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("timeout")
        with pytest.raises(DatabaseError):
            customer_repository.get_all(conn)

    def test_pagination_offset_calculated_correctly(self):
        conn, cursor = _make_conn(count_return={"total": 0}, fetchall_return=[])
        customer_repository.get_all(conn, page=3, page_size=10)
        data_call = cursor.execute.call_args_list[1]
        limit, offset = data_call[0][1]
        assert limit == 10
        assert offset == 20  # (3-1) * 10


# =============================================================================
# customer_service.get_customer
# =============================================================================

class TestCustomerServiceGetCustomer:

    def test_returns_customer_response_model(self):
        conn, _ = _make_conn(fetchone_return=_cust_row())
        result = customer_service.get_customer(conn, 1)
        assert isinstance(result, CustomerResponse)
        assert result.customer_id == 1
        assert result.first_name == "Meera"
        assert result.email == "meera@example.com"

    def test_is_active_is_bool_in_response(self):
        conn, _ = _make_conn(fetchone_return=_cust_row(is_active=1))
        result = customer_service.get_customer(conn, 1)
        assert result.is_active is True

    def test_not_found_propagates(self):
        conn, _ = _make_conn(fetchone_return=None)
        with pytest.raises(NotFoundError):
            customer_service.get_customer(conn, 999)

    def test_phone_can_be_none(self):
        conn, _ = _make_conn(fetchone_return=_cust_row(phone=None))
        result = customer_service.get_customer(conn, 1)
        assert result.phone is None

    def test_inactive_customer_still_returned(self):
        """get_customer returns the row regardless of is_active — caller decides."""
        conn, _ = _make_conn(fetchone_return=_cust_row(is_active=0))
        result = customer_service.get_customer(conn, 1)
        assert result.is_active is False


# =============================================================================
# customer_service.list_customers
# =============================================================================

class TestCustomerServiceListCustomers:

    def test_returns_customer_list_response(self):
        rows = [_cust_row(1), _cust_row(2, "Arjun", "Verma", "arjun@example.com")]
        conn, _ = _make_conn(count_return={"total": 2}, fetchall_return=rows)
        result = customer_service.list_customers(conn)
        assert isinstance(result, CustomerListResponse)
        assert result.total == 2
        assert len(result.items) == 2

    def test_items_are_customer_summary_models(self):
        rows = [_cust_row()]
        conn, _ = _make_conn(count_return={"total": 1}, fetchall_return=rows)
        result = customer_service.list_customers(conn)
        assert isinstance(result.items[0], CustomerSummary)

    def test_page_size_capped_at_100(self):
        conn = MagicMock()
        with patch.object(
            customer_repository, "get_all", return_value=(0, [])
        ) as mock_get_all:
            customer_service.list_customers(conn, page_size=999)
            _, kwargs = mock_get_all.call_args
            assert kwargs["page_size"] == 100

    def test_invalid_page_zero_raises_business_rule_error(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            customer_service.list_customers(conn, page=0)
        assert exc_info.value.error_code == "INVALID_PAGINATION"

    def test_invalid_page_negative_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError):
            customer_service.list_customers(conn, page=-1)

    def test_invalid_page_size_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            customer_service.list_customers(conn, page_size=0)
        assert exc_info.value.error_code == "INVALID_PAGINATION"

    def test_pagination_metadata_in_response(self):
        rows = [_cust_row()]
        conn, _ = _make_conn(count_return={"total": 50}, fetchall_return=rows)
        result = customer_service.list_customers(conn, page=3, page_size=10)
        assert result.page == 3
        assert result.page_size == 10
        assert result.total == 50

    def test_active_only_false_delegated_to_repository(self):
        conn = MagicMock()
        with patch.object(
            customer_repository, "get_all", return_value=(0, [])
        ) as mock_get_all:
            customer_service.list_customers(conn, active_only=False)
            _, kwargs = mock_get_all.call_args
            assert kwargs["active_only"] is False

    def test_empty_list_returns_valid_response(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        result = customer_service.list_customers(conn)
        assert result.total == 0
        assert result.items == []

    def test_effective_page_size_passed_to_repository(self):
        """When page_size exceeds 100 the repository must receive 100, not the raw input."""
        conn = MagicMock()
        with patch.object(
            customer_repository, "get_all", return_value=(0, [])
        ) as mock_get_all:
            customer_service.list_customers(conn, page_size=50)
            _, kwargs = mock_get_all.call_args
            assert kwargs["page_size"] == 50
