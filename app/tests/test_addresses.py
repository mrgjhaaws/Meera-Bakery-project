"""
tests/test_addresses.py
========================
Unit tests for the addresses repository and service layers.

Strategy
--------
- No real database — PooledMySQLConnection replaced with MagicMock.
- Repository tests verify: TINYINT→bool normalisation for both is_active
  AND is_default, customer-existence pre-check, NotFoundError for missing
  customer or address, DatabaseError on MySQLError, dictionary=True cursor,
  parameterised queries, pagination offset arithmetic.
- Service tests verify: pagination cap, BusinessRuleError on bad params,
  correct Pydantic model construction, active_only delegation,
  NotFoundError propagation from customer check.

Run with:
    cd C:\\MeeraBakery\\app
    pytest tests/test_addresses.py -v
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from models.address import AddressListResponse, AddressResponse, AddressSummary
from repositories import address_repository
from services import address_service
from utils.exceptions import BusinessRuleError, DatabaseError, NotFoundError


# =============================================================================
# Shared helpers
# =============================================================================

def _make_conn_for_get_by_id(fetchone_return=None):
    """Single fetchone() call — used by get_by_id."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_return
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _make_conn_for_get_all(
    customer_exists: bool = True,
    count: int = 0,
    rows: list | None = None,
):
    """Three-step cursor: verify customer, count, fetch rows.

    get_all_for_customer calls cursor.execute three times and
    cursor.fetchone twice (verify + count) before cursor.fetchall.
    """
    cursor = MagicMock()

    # fetchone call 1 → customer verify row (or None if customer missing)
    customer_row = {"customer_id": 1} if customer_exists else None
    # fetchone call 2 → count row
    count_row = {"total": count}

    cursor.fetchone.side_effect = [customer_row, count_row]
    cursor.fetchall.return_value = rows or []

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _addr_row(
    address_id: int = 1,
    customer_id: int = 1,
    label: str = "Home",
    address_line1: str = "42 MG Road",
    address_line2: str | None = None,
    city: str = "Bengaluru",
    state: str = "Karnataka",
    postal_code: str = "560001",
    country: str = "India",
    is_default: int = 1,
    is_active: int = 1,
) -> dict:
    """Return a dict that mirrors a MySQL cursor row for an address."""
    return {
        "address_id": address_id,
        "customer_id": customer_id,
        "label": label,
        "address_line1": address_line1,
        "address_line2": address_line2,
        "city": city,
        "state": state,
        "postal_code": postal_code,
        "country": country,
        "is_default": is_default,
        "is_active": is_active,
        "created_at": datetime(2026, 1, 1, 10, 0, 0),
        "updated_at": datetime(2026, 1, 1, 10, 0, 0),
    }


# =============================================================================
# address_repository.get_by_id
# =============================================================================

class TestAddressRepositoryGetById:

    def test_returns_dict_for_existing_address(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row())
        result = address_repository.get_by_id(conn, 1)
        assert result["address_id"] == 1
        assert result["city"] == "Bengaluru"

    def test_is_active_1_normalised_to_true(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row(is_active=1))
        result = address_repository.get_by_id(conn, 1)
        assert result["is_active"] is True

    def test_is_active_0_normalised_to_false(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row(is_active=0))
        result = address_repository.get_by_id(conn, 1)
        assert result["is_active"] is False

    def test_is_default_1_normalised_to_true(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row(is_default=1))
        result = address_repository.get_by_id(conn, 1)
        assert result["is_default"] is True

    def test_is_default_0_normalised_to_false(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row(is_default=0))
        result = address_repository.get_by_id(conn, 1)
        assert result["is_default"] is False

    def test_raises_not_found_when_row_is_none(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=None)
        with pytest.raises(NotFoundError) as exc_info:
            address_repository.get_by_id(conn, 99)
        assert exc_info.value.error_code == "RESOURCE_NOT_FOUND"
        assert "99" in exc_info.value.message

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("connection lost")
        with pytest.raises(DatabaseError):
            address_repository.get_by_id(conn, 1)

    def test_cursor_opened_with_dictionary_true(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row())
        address_repository.get_by_id(conn, 1)
        conn.cursor.assert_called_with(dictionary=True)

    def test_parameterised_query_uses_address_id(self):
        conn, cursor = _make_conn_for_get_by_id(fetchone_return=_addr_row(address_id=7))
        address_repository.get_by_id(conn, 7)
        call_args = cursor.execute.call_args
        assert call_args[0][1] == (7,)

    def test_address_line2_can_be_none(self):
        conn, _ = _make_conn_for_get_by_id(
            fetchone_return=_addr_row(address_line2=None)
        )
        result = address_repository.get_by_id(conn, 1)
        assert result["address_line2"] is None


# =============================================================================
# address_repository.get_all_for_customer
# =============================================================================

class TestAddressRepositoryGetAllForCustomer:

    def test_returns_total_and_rows(self):
        rows = [_addr_row(1), _addr_row(2, label="Office", is_default=0)]
        conn, _ = _make_conn_for_get_all(customer_exists=True, count=2, rows=rows)
        total, result_rows = address_repository.get_all_for_customer(conn, 1)
        assert total == 2
        assert len(result_rows) == 2

    def test_normalises_is_active_and_is_default_in_all_rows(self):
        rows = [
            _addr_row(1, is_default=1, is_active=1),
            _addr_row(2, label="Office", is_default=0, is_active=0),
        ]
        conn, _ = _make_conn_for_get_all(
            customer_exists=True, count=2, rows=rows
        )
        _, result_rows = address_repository.get_all_for_customer(
            conn, 1, active_only=False
        )
        assert result_rows[0]["is_default"] is True
        assert result_rows[0]["is_active"] is True
        assert result_rows[1]["is_default"] is False
        assert result_rows[1]["is_active"] is False

    def test_raises_not_found_when_customer_missing(self):
        conn, _ = _make_conn_for_get_all(customer_exists=False)
        with pytest.raises(NotFoundError) as exc_info:
            address_repository.get_all_for_customer(conn, 999)
        assert "customer" in exc_info.value.message
        assert "999" in exc_info.value.message

    def test_empty_result_returns_zero_total(self):
        conn, _ = _make_conn_for_get_all(customer_exists=True, count=0, rows=[])
        total, rows = address_repository.get_all_for_customer(conn, 1)
        assert total == 0
        assert rows == []

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("timeout")
        with pytest.raises(DatabaseError):
            address_repository.get_all_for_customer(conn, 1)

    def test_pagination_offset_calculated_correctly(self):
        conn, cursor = _make_conn_for_get_all(customer_exists=True, count=0, rows=[])
        address_repository.get_all_for_customer(conn, 1, page=3, page_size=5)
        # Third execute call is the data query; last two params are LIMIT, OFFSET
        data_call = cursor.execute.call_args_list[2]
        params = data_call[0][1]
        limit, offset = params[-2], params[-1]
        assert limit == 5
        assert offset == 10  # (3-1) * 5


# =============================================================================
# address_service.get_address
# =============================================================================

class TestAddressServiceGetAddress:

    def test_returns_address_response_model(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row())
        result = address_service.get_address(conn, 1)
        assert isinstance(result, AddressResponse)
        assert result.address_id == 1
        assert result.city == "Bengaluru"

    def test_is_active_is_bool(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row(is_active=1))
        result = address_service.get_address(conn, 1)
        assert result.is_active is True

    def test_is_default_is_bool(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row(is_default=1))
        result = address_service.get_address(conn, 1)
        assert result.is_default is True

    def test_not_found_propagates(self):
        conn, _ = _make_conn_for_get_by_id(fetchone_return=None)
        with pytest.raises(NotFoundError):
            address_service.get_address(conn, 999)

    def test_address_line2_can_be_none(self):
        conn, _ = _make_conn_for_get_by_id(
            fetchone_return=_addr_row(address_line2=None)
        )
        result = address_service.get_address(conn, 1)
        assert result.address_line2 is None

    def test_inactive_address_still_returned(self):
        """get_address surfaces inactive rows — caller decides visibility."""
        conn, _ = _make_conn_for_get_by_id(fetchone_return=_addr_row(is_active=0))
        result = address_service.get_address(conn, 1)
        assert result.is_active is False


# =============================================================================
# address_service.list_addresses
# =============================================================================

class TestAddressServiceListAddresses:

    def test_returns_address_list_response(self):
        rows = [_addr_row(1), _addr_row(2, label="Office", is_default=0)]
        conn, _ = _make_conn_for_get_all(customer_exists=True, count=2, rows=rows)
        result = address_service.list_addresses(conn, customer_id=1)
        assert isinstance(result, AddressListResponse)
        assert result.total == 2
        assert len(result.items) == 2

    def test_items_are_address_summary_models(self):
        rows = [_addr_row()]
        conn, _ = _make_conn_for_get_all(customer_exists=True, count=1, rows=rows)
        result = address_service.list_addresses(conn, customer_id=1)
        assert isinstance(result.items[0], AddressSummary)

    def test_page_size_capped_at_100(self):
        conn = MagicMock()
        with patch.object(
            address_repository, "get_all_for_customer", return_value=(0, [])
        ) as mock_get_all:
            address_service.list_addresses(conn, customer_id=1, page_size=999)
            _, kwargs = mock_get_all.call_args
            assert kwargs["page_size"] == 100

    def test_invalid_page_zero_raises_business_rule_error(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            address_service.list_addresses(conn, customer_id=1, page=0)
        assert exc_info.value.error_code == "INVALID_PAGINATION"

    def test_invalid_page_size_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            address_service.list_addresses(conn, customer_id=1, page_size=0)
        assert exc_info.value.error_code == "INVALID_PAGINATION"

    def test_customer_not_found_propagates(self):
        """NotFoundError from repository customer-check must reach the caller."""
        conn, _ = _make_conn_for_get_all(customer_exists=False)
        with pytest.raises(NotFoundError) as exc_info:
            address_service.list_addresses(conn, customer_id=999)
        assert "customer" in exc_info.value.message

    def test_active_only_false_delegated_to_repository(self):
        conn = MagicMock()
        with patch.object(
            address_repository, "get_all_for_customer", return_value=(0, [])
        ) as mock_get_all:
            address_service.list_addresses(conn, customer_id=1, active_only=False)
            _, kwargs = mock_get_all.call_args
            assert kwargs["active_only"] is False

    def test_pagination_metadata_in_response(self):
        rows = [_addr_row()]
        conn, _ = _make_conn_for_get_all(customer_exists=True, count=30, rows=rows)
        result = address_service.list_addresses(
            conn, customer_id=1, page=2, page_size=10
        )
        assert result.page == 2
        assert result.page_size == 10
        assert result.total == 30

    def test_empty_list_returns_valid_response(self):
        conn, _ = _make_conn_for_get_all(customer_exists=True, count=0, rows=[])
        result = address_service.list_addresses(conn, customer_id=1)
        assert result.total == 0
        assert result.items == []

    def test_customer_id_passed_to_repository(self):
        conn = MagicMock()
        with patch.object(
            address_repository, "get_all_for_customer", return_value=(0, [])
        ) as mock_get_all:
            address_service.list_addresses(conn, customer_id=7)
            args, _ = mock_get_all.call_args
            # First positional arg after conn is customer_id
            assert args[1] == 7
