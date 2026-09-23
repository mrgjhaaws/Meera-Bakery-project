"""
tests/test_products.py
=======================
Unit tests for the products repository and service layers.

Strategy
--------
- No real database connection — PooledMySQLConnection replaced with MagicMock.
- Repository tests verify: SQL delegation, DECIMAL→float normalisation,
  TINYINT→bool normalisation, inventory sub-dict extraction, NotFoundError,
  DatabaseError on MySQLError.
- Service tests verify: pagination cap, filter validation, inventory embedding
  via ProductInventoryInfo, correct Pydantic model construction.

Run with:
    cd C:\\MeeraBakery\\app
    pytest tests/test_products.py -v
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from models.product import (
    ProductInventoryInfo,
    ProductListResponse,
    ProductResponse,
    ProductSummary,
)
from repositories import product_repository
from services import product_service
from utils.exceptions import BusinessRuleError, DatabaseError, NotFoundError


# =============================================================================
# Shared fixtures
# =============================================================================

def _make_conn(fetchone_return=None, fetchall_return=None, count_return=None):
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


def _prod_row(
    product_id: int = 1,
    category_id: int = 1,
    category_name: str = "Bread",
    name: str = "Sourdough Loaf",
    unit_price=Decimal("120.00"),
    is_active: int = 1,
    description: str = "A great loaf",
    include_inventory: bool = False,
) -> dict:
    """Return a dict mirroring a MySQL cursor row for a product."""
    row: dict = {
        "product_id": product_id,
        "category_id": category_id,
        "category_name": category_name,
        "name": name,
        "description": description,
        "unit_price": unit_price,
        "is_active": is_active,
        "created_at": datetime(2026, 1, 1, 10, 0, 0),
        "updated_at": datetime(2026, 1, 1, 10, 0, 0),
    }
    if include_inventory:
        row.update({
            "quantity_on_hand": 25,
            "reorder_level": 10,
            "reorder_quantity": 50,
            "last_restocked_at": None,
        })
    return row


def _summary_row(**kwargs) -> dict:
    """Slim product row returned by get_all (no description/timestamps)."""
    base = {
        "product_id": 1,
        "category_id": 1,
        "category_name": "Bread",
        "name": "Sourdough Loaf",
        "unit_price": Decimal("120.00"),
        "is_active": 1,
    }
    base.update(kwargs)
    return base


# =============================================================================
# product_repository._normalise (tested indirectly through get_by_id)
# =============================================================================

class TestProductRepositoryNormalise:

    def test_decimal_price_converted_to_float(self):
        row = _prod_row(unit_price=Decimal("120.00"))
        conn, _ = _make_conn(fetchone_return=row)
        result = product_repository.get_by_id(conn, 1)
        assert isinstance(result["unit_price"], float)
        assert result["unit_price"] == 120.00

    def test_float_price_stays_float(self):
        row = _prod_row(unit_price=120.0)
        conn, _ = _make_conn(fetchone_return=row)
        result = product_repository.get_by_id(conn, 1)
        assert isinstance(result["unit_price"], float)

    def test_is_active_1_normalised_to_true(self):
        conn, _ = _make_conn(fetchone_return=_prod_row(is_active=1))
        result = product_repository.get_by_id(conn, 1)
        assert result["is_active"] is True

    def test_is_active_0_normalised_to_false(self):
        conn, _ = _make_conn(fetchone_return=_prod_row(is_active=0))
        result = product_repository.get_by_id(conn, 1)
        assert result["is_active"] is False


# =============================================================================
# product_repository.get_by_id
# =============================================================================

class TestProductRepositoryGetById:

    def test_returns_dict_for_existing_product(self):
        conn, _ = _make_conn(fetchone_return=_prod_row())
        result = product_repository.get_by_id(conn, 1)
        assert result["product_id"] == 1
        assert result["name"] == "Sourdough Loaf"

    def test_inventory_is_none_when_not_requested(self):
        conn, _ = _make_conn(fetchone_return=_prod_row())
        result = product_repository.get_by_id(conn, 1, include_inventory=False)
        assert result["inventory"] is None

    def test_inventory_dict_present_when_requested(self):
        row = _prod_row(include_inventory=True)
        conn, _ = _make_conn(fetchone_return=row)
        result = product_repository.get_by_id(conn, 1, include_inventory=True)
        assert result["inventory"] is not None
        assert result["inventory"]["quantity_on_hand"] == 25
        assert result["inventory"]["reorder_level"] == 10
        assert result["inventory"]["reorder_quantity"] == 50

    def test_inventory_cols_removed_from_top_level(self):
        """quantity_on_hand etc. must not remain at the product dict top level."""
        row = _prod_row(include_inventory=True)
        conn, _ = _make_conn(fetchone_return=row)
        result = product_repository.get_by_id(conn, 1, include_inventory=True)
        assert "quantity_on_hand" not in result
        assert "reorder_level" not in result
        assert "reorder_quantity" not in result
        assert "last_restocked_at" not in result

    def test_inventory_none_when_left_join_returns_nulls(self):
        """LEFT JOIN returns NULLs for inventory columns when no inventory row exists."""
        row = _prod_row()
        row["quantity_on_hand"] = None
        row["reorder_level"] = None
        row["reorder_quantity"] = None
        row["last_restocked_at"] = None
        conn, _ = _make_conn(fetchone_return=row)
        result = product_repository.get_by_id(conn, 1, include_inventory=True)
        assert result["inventory"] is None

    def test_raises_not_found_when_row_is_none(self):
        conn, _ = _make_conn(fetchone_return=None)
        with pytest.raises(NotFoundError) as exc_info:
            product_repository.get_by_id(conn, 99)
        assert "99" in exc_info.value.message

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("lost connection")
        with pytest.raises(DatabaseError):
            product_repository.get_by_id(conn, 1)

    def test_cursor_opened_with_dictionary_true(self):
        conn, _ = _make_conn(fetchone_return=_prod_row())
        product_repository.get_by_id(conn, 1)
        conn.cursor.assert_called_with(dictionary=True)

    def test_parameterised_query_uses_product_id(self):
        conn, cursor = _make_conn(fetchone_return=_prod_row(product_id=7))
        product_repository.get_by_id(conn, 7)
        call_args = cursor.execute.call_args
        assert call_args[0][1] == (7,)


# =============================================================================
# product_repository.get_all
# =============================================================================

class TestProductRepositoryGetAll:

    def test_returns_total_and_rows(self):
        rows = [_summary_row(product_id=1), _summary_row(product_id=2)]
        conn, _ = _make_conn(count_return={"total": 13}, fetchall_return=rows)
        total, result = product_repository.get_all(conn)
        assert total == 13
        assert len(result) == 2

    def test_normalises_decimal_price_in_list(self):
        rows = [_summary_row(unit_price=Decimal("50.00"))]
        conn, _ = _make_conn(count_return={"total": 1}, fetchall_return=rows)
        _, result = product_repository.get_all(conn)
        assert isinstance(result[0]["unit_price"], float)

    def test_normalises_is_active_in_list(self):
        rows = [_summary_row(is_active=1)]
        conn, _ = _make_conn(count_return={"total": 1}, fetchall_return=rows)
        _, result = product_repository.get_all(conn)
        assert result[0]["is_active"] is True

    def test_empty_result(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        total, rows = product_repository.get_all(conn)
        assert total == 0
        assert rows == []

    def test_pagination_offset_calculated_correctly(self):
        conn, cursor = _make_conn(count_return={"total": 0}, fetchall_return=[])
        product_repository.get_all(conn, page=3, page_size=10)
        data_call = cursor.execute.call_args_list[1]
        params = data_call[0][1]
        limit, offset = params[-2], params[-1]
        assert limit == 10
        assert offset == 20   # (3-1)*10

    def test_raises_database_error_on_mysql_error(self):
        from mysql.connector import Error as MySQLError
        conn = MagicMock()
        conn.cursor.side_effect = MySQLError("timeout")
        with pytest.raises(DatabaseError):
            product_repository.get_all(conn)


# =============================================================================
# product_service.get_product
# =============================================================================

class TestProductServiceGetProduct:

    def test_returns_product_response_model(self):
        conn, _ = _make_conn(fetchone_return=_prod_row())
        result = product_service.get_product(conn, 1)
        assert isinstance(result, ProductResponse)
        assert result.product_id == 1
        assert result.name == "Sourdough Loaf"
        assert result.category_name == "Bread"

    def test_unit_price_is_float(self):
        conn, _ = _make_conn(fetchone_return=_prod_row(unit_price=Decimal("120.00")))
        result = product_service.get_product(conn, 1)
        assert isinstance(result.unit_price, float)
        assert result.unit_price == 120.00

    def test_is_active_is_bool(self):
        conn, _ = _make_conn(fetchone_return=_prod_row(is_active=1))
        result = product_service.get_product(conn, 1)
        assert result.is_active is True

    def test_inventory_none_by_default(self):
        conn, _ = _make_conn(fetchone_return=_prod_row())
        result = product_service.get_product(conn, 1, include_inventory=False)
        assert result.inventory is None

    def test_inventory_embedded_when_requested(self):
        row = _prod_row(include_inventory=True)
        conn, _ = _make_conn(fetchone_return=row)

        with patch.object(
            product_repository, "get_by_id", return_value={
                "product_id": 1,
                "category_id": 1,
                "category_name": "Bread",
                "name": "Sourdough Loaf",
                "description": "A great loaf",
                "unit_price": 120.0,
                "is_active": True,
                "created_at": datetime(2026, 1, 1),
                "updated_at": datetime(2026, 1, 1),
                "inventory": {
                    "quantity_on_hand": 25,
                    "reorder_level": 10,
                    "reorder_quantity": 50,
                    "last_restocked_at": None,
                },
            }
        ):
            result = product_service.get_product(conn, 1, include_inventory=True)

        assert result.inventory is not None
        assert isinstance(result.inventory, ProductInventoryInfo)
        assert result.inventory.quantity_on_hand == 25
        assert result.inventory.reorder_level == 10

    def test_not_found_propagates(self):
        conn, _ = _make_conn(fetchone_return=None)
        with pytest.raises(NotFoundError):
            product_service.get_product(conn, 999)

    def test_description_can_be_none(self):
        row = _prod_row()
        row["description"] = None
        conn, _ = _make_conn(fetchone_return=row)
        result = product_service.get_product(conn, 1)
        assert result.description is None


# =============================================================================
# product_service.list_products
# =============================================================================

class TestProductServiceListProducts:

    def test_returns_product_list_response(self):
        rows = [_summary_row()]
        conn, _ = _make_conn(count_return={"total": 13}, fetchall_return=rows)
        result = product_service.list_products(conn)
        assert isinstance(result, ProductListResponse)
        assert result.total == 13

    def test_items_are_product_summary_models(self):
        rows = [_summary_row()]
        conn, _ = _make_conn(count_return={"total": 1}, fetchall_return=rows)
        result = product_service.list_products(conn)
        assert isinstance(result.items[0], ProductSummary)

    def test_page_size_capped_at_100(self):
        conn = MagicMock()
        with patch.object(
            product_repository, "get_all", return_value=(0, [])
        ) as mock_get_all:
            product_service.list_products(conn, page_size=500)
            _, kwargs = mock_get_all.call_args
            assert kwargs["page_size"] == 100

    def test_invalid_page_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            product_service.list_products(conn, page=0)
        assert exc_info.value.error_code == "INVALID_PAGINATION"

    def test_invalid_page_size_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError):
            product_service.list_products(conn, page_size=0)

    def test_invalid_category_id_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            product_service.list_products(conn, category_id=0)
        assert exc_info.value.error_code == "INVALID_FILTER"

    def test_invalid_category_id_negative_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError):
            product_service.list_products(conn, category_id=-5)

    def test_category_id_filter_passed_to_repository(self):
        conn = MagicMock()
        with patch.object(
            product_repository, "get_all", return_value=(0, [])
        ) as mock_get_all:
            product_service.list_products(conn, category_id=3)
            _, kwargs = mock_get_all.call_args
            assert kwargs["category_id"] == 3

    def test_category_id_in_filters_metadata(self):
        conn = MagicMock()
        with patch.object(product_repository, "get_all", return_value=(0, [])):
            result = product_service.list_products(conn, category_id=2)
        assert result.filters.get("category_id") == 2

    def test_no_filter_metadata_when_defaults_used(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        result = product_service.list_products(conn)
        # filters should be empty when no non-default params were passed
        assert "category_id" not in result.filters

    def test_pagination_metadata_correct(self):
        rows = [_summary_row()]
        conn, _ = _make_conn(count_return={"total": 30}, fetchall_return=rows)
        result = product_service.list_products(conn, page=2, page_size=10)
        assert result.page == 2
        assert result.page_size == 10
        assert result.total == 30

    def test_empty_result_valid_response(self):
        conn, _ = _make_conn(count_return={"total": 0}, fetchall_return=[])
        result = product_service.list_products(conn)
        assert result.total == 0
        assert result.items == []

    def test_active_only_false_passed_to_repository(self):
        conn = MagicMock()
        with patch.object(
            product_repository, "get_all", return_value=(0, [])
        ) as mock_get_all:
            product_service.list_products(conn, active_only=False)
            _, kwargs = mock_get_all.call_args
            assert kwargs["active_only"] is False


# =============================================================================
# product_service.list_products_by_category
# =============================================================================

class TestProductServiceListProductsByCategory:

    def test_delegates_to_list_products_with_category_id(self):
        conn = MagicMock()
        with patch.object(
            product_service, "list_products", return_value=MagicMock()
        ) as mock_list:
            product_service.list_products_by_category(conn, category_id=4)
            _, kwargs = mock_list.call_args
            assert kwargs["category_id"] == 4

    def test_returns_product_list_response(self):
        rows = [_summary_row()]
        conn, _ = _make_conn(count_return={"total": 3}, fetchall_return=rows)
        result = product_service.list_products_by_category(conn, category_id=1)
        assert isinstance(result, ProductListResponse)
