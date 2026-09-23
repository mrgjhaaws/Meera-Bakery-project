"""
tests/test_categories.py
=========================
Unit tests for the categories repository and service layers.

Strategy
--------
- No real database connection is used.  The PooledMySQLConnection is replaced
  with a lightweight MagicMock whose cursor() method returns a mock cursor.
- Repository tests verify: correct SQL fragments, correct parameter binding,
  correct type normalisation (TINYINT→bool), NotFoundError on missing rows,
  DatabaseError on MySQLError.
- Service tests verify: pagination cap, invalid-param BusinessRuleError,
  correct delegation to repository, correct Pydantic model construction.

Run with:
    cd C:\\MeeraBakery\\app
    pytest tests/test_categories.py -v
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from models.category import CategoryListResponse, CategoryResponse
from repositories import category_repository
from services import category_service
from utils.exceptions import BusinessRuleError, DatabaseError, NotFoundError


# =============================================================================
# Shared fixtures
# =============================================================================

def _make_conn(fetchone_return=None, fetchall_return=None, count_return=None):
    """Build a mock connection whose cursor behaves as expected.

    If count_return is provided the first fetchone() call returns the count
    dict and subsequent calls return fetchone_return (used for get_all which
    calls fetchone for COUNT then fetchall for data).
    """
    cursor = MagicMock()

    if count_return is not None:
        # get_all: first fetchone → count, then fetchall → rows
        cursor.fetchone.side_effect = [count_return]
        cursor.fetchall.return_value = fetchall_return or []
    else:
        cursor.fetchone.return_value = fetchone_return
        cursor.fetchall.return_value = fetchall_return or []

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _cat_row(
    category_id: int = 1,
    name: str = "Bread",
    description: str = "Fresh bread",
    is_active: int = 1,
) -> dict:
    """Return a dict that mirrors a MySQL cursor row for a category."""
    return {
        "category_id": category_id,
        "name": name,
        "description": description,
        "is_active": is_active,
        "created_at": datetime(2026, 1, 1, 10, 0, 0),
        "updated_at": datetime(2026, 1, 1, 10, 0, 0),
    }


# =============================================================================
# category_repository.get_by_id
# =============================================================================

class TestCategoryRepositoryGetById:

    def test_returns_dict_for_existing_category(self):
        row = _cat_row()
        conn, _ = _make_conn(fetchone_return=row)
        result = category_repository.get_by_id(conn, 1)
        assert result["category_id"] == 1
        assert result["name"] == "Bread"

    def test_normalises_is_active_to_bool_true(self):
        conn, _ = _make_conn(fetchone_return=_cat_row(is_active=1))
        result = category_repository.get_by_id(conn, 1)
        assert result["is_active"] is True

    def test_normalises_is_active_to_bool_false(self):
        conn, _ = _make_conn(fetchone_return=_cat_row(is_active=0))
        result = category_repository.get_by_id(conn, 1)
        assert result["is_active"] is False

    def test_raises_not_found_when_row_is_none(self):
        conn, _ = _make_conn(fetchone_return=None)
        with pytest.raises(NotFoundError) as exc_info:
            category_repository.get_by_id(conn, 99)
        assert exc_info.value.error_code == "RESOURCE_NOT_FOUND"
        assert "99" in exc_info.value.message

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("connection lost")
        with pytest.raises(DatabaseError):
            category_repository.get_by_id(conn, 1)

    def test_cursor_called_with_category_id_param(self):
        row = _cat_row(category_id=3)
        conn, cursor = _make_conn(fetchone_return=row)
        category_repository.get_by_id(conn, 3)
        # The execute call must pass (3,) as the parameter tuple
        call_args = cursor.execute.call_args
        assert call_args[0][1] == (3,)

    def test_cursor_opened_with_dictionary_true(self):
        conn, _ = _make_conn(fetchone_return=_cat_row())
        category_repository.get_by_id(conn, 1)
        conn.cursor.assert_called_with(dictionary=True)


# =============================================================================
# category_repository.get_all
# =============================================================================

class TestCategoryRepositoryGetAll:

    def test_returns_total_and_rows(self):
        rows = [_cat_row(1, "Bread"), _cat_row(2, "Cake")]
        conn, _ = _make_conn(
            count_return={"total": 2},
            fetchall_return=rows,
        )
        total, result_rows = category_repository.get_all(conn)
        assert total == 2
        assert len(result_rows) == 2

    def test_normalises_is_active_in_all_rows(self):
        rows = [
            _cat_row(1, "Bread", is_active=1),
            _cat_row(2, "Cake",  is_active=0),
        ]
        conn, _ = _make_conn(count_return={"total": 2}, fetchall_return=rows)
        _, result_rows = category_repository.get_all(conn, active_only=False)
        assert result_rows[0]["is_active"] is True
        assert result_rows[1]["is_active"] is False

    def test_empty_result_returns_zero_total(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        total, rows = category_repository.get_all(conn)
        assert total == 0
        assert rows == []

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("timeout")
        with pytest.raises(DatabaseError):
            category_repository.get_all(conn)

    def test_pagination_params_passed_to_execute(self):
        conn, cursor = _make_conn(
            count_return={"total": 0}, fetchall_return=[]
        )
        category_repository.get_all(conn, page=2, page_size=5)
        # Second execute call is the data query; args should include limit=5, offset=5
        data_call = cursor.execute.call_args_list[1]
        limit, offset = data_call[0][1]
        assert limit == 5
        assert offset == 5   # (page-1) * page_size = (2-1)*5 = 5


# =============================================================================
# category_service.get_category
# =============================================================================

class TestCategoryServiceGetCategory:

    def test_returns_category_response_model(self):
        row = _cat_row()
        conn, _ = _make_conn(fetchone_return=row)
        result = category_service.get_category(conn, 1)
        assert isinstance(result, CategoryResponse)
        assert result.category_id == 1
        assert result.name == "Bread"

    def test_is_active_is_bool_in_response(self):
        conn, _ = _make_conn(fetchone_return=_cat_row(is_active=1))
        result = category_service.get_category(conn, 1)
        assert result.is_active is True

    def test_not_found_propagates(self):
        conn, _ = _make_conn(fetchone_return=None)
        with pytest.raises(NotFoundError):
            category_service.get_category(conn, 999)

    def test_description_can_be_none(self):
        row = _cat_row()
        row["description"] = None
        conn, _ = _make_conn(fetchone_return=row)
        result = category_service.get_category(conn, 1)
        assert result.description is None


# =============================================================================
# category_service.list_categories
# =============================================================================

class TestCategoryServiceListCategories:

    def test_returns_category_list_response(self):
        rows = [_cat_row(1, "Bread"), _cat_row(2, "Cake")]
        conn, _ = _make_conn(count_return={"total": 6}, fetchall_return=rows)
        result = category_service.list_categories(conn)
        assert isinstance(result, CategoryListResponse)
        assert result.total == 6
        assert len(result.items) == 2

    def test_items_are_category_response_models(self):
        rows = [_cat_row(1, "Bread")]
        conn, _ = _make_conn(count_return={"total": 1}, fetchall_return=rows)
        result = category_service.list_categories(conn)
        assert isinstance(result.items[0], CategoryResponse)

    def test_page_size_capped_at_100(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        with patch.object(category_repository, "get_all", return_value=(0, [])) as mock_get_all:
            category_service.list_categories(conn, page_size=999)
            _, kwargs = mock_get_all.call_args
            assert kwargs["page_size"] == 100

    def test_invalid_page_zero_raises_business_rule_error(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            category_service.list_categories(conn, page=0)
        assert exc_info.value.error_code == "INVALID_PAGINATION"

    def test_invalid_page_negative_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError):
            category_service.list_categories(conn, page=-1)

    def test_invalid_page_size_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            category_service.list_categories(conn, page_size=0)
        assert exc_info.value.error_code == "INVALID_PAGINATION"

    def test_pagination_metadata_in_response(self):
        rows = [_cat_row()]
        conn, _ = _make_conn(count_return={"total": 50}, fetchall_return=rows)
        result = category_service.list_categories(conn, page=3, page_size=10)
        assert result.page == 3
        assert result.page_size == 10
        assert result.total == 50

    def test_active_only_false_delegates_to_repository(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        with patch.object(
            category_repository, "get_all", return_value=(0, [])
        ) as mock_get_all:
            category_service.list_categories(conn, active_only=False)
            _, kwargs = mock_get_all.call_args
            assert kwargs["active_only"] is False

    def test_empty_list_returns_valid_response(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        result = category_service.list_categories(conn)
        assert result.total == 0
        assert result.items == []
