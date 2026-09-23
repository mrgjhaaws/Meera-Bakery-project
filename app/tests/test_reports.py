"""
tests/test_reports.py
======================
Unit tests for report_repository and report_service.

Strategy
--------
- No real database — PooledMySQLConnection replaced with MagicMock.
- Repository tests verify: SQL delegation, DECIMAL->float normalisation,
  parameterised date-range predicates, DatabaseError on MySQLError.
- Service tests verify: date-range validation, Pydantic model assembly.

Run with:
    cd C:\\MeeraBakery\\app
    pytest tests/test_reports.py -v
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from mysql.connector import Error as MySQLError

from models.report import LowStockReport, RevenueReport
from repositories import report_repository
from services import report_service
from utils.exceptions import BusinessRuleError, DatabaseError


def _make_conn(fetchall_return=None) -> tuple[MagicMock, MagicMock]:
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchall_return or []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# =============================================================================
# report_repository — low stock
# =============================================================================

class TestGetLowStock:

    def test_returns_rows(self):
        rows = [{
            "product_id": 3, "category": "Pastry", "product": "Butter Croissant",
            "quantity_on_hand": 4, "reorder_level": 10, "reorder_quantity": 50,
            "units_below_threshold": 6, "last_restocked_at": None,
        }]
        conn, cursor = _make_conn(fetchall_return=rows)

        result = report_repository.get_low_stock(conn)

        assert result == rows
        cursor.execute.assert_called_once()

    def test_filters_active_products_below_reorder_level(self):
        conn, cursor = _make_conn()
        report_repository.get_low_stock(conn)

        sql = cursor.execute.call_args.args[0]
        assert "i.quantity_on_hand <= i.reorder_level" in sql
        assert "p.is_active = 1" in sql

    def test_raises_database_error(self):
        conn, cursor = _make_conn()
        cursor.execute.side_effect = MySQLError("boom")

        with pytest.raises(DatabaseError):
            report_repository.get_low_stock(conn)


# =============================================================================
# report_repository — revenue
# =============================================================================

class TestGetDailyRevenue:

    def test_normalises_decimals_to_float(self):
        rows = [{
            "order_date": date(2026, 1, 15), "orders_delivered": 3,
            "total_subtotal": Decimal("500.00"), "total_discounts": Decimal("20.00"),
            "total_tax": Decimal("86.40"), "total_revenue": Decimal("566.40"),
        }]
        conn, cursor = _make_conn(fetchall_return=rows)

        result = report_repository.get_daily_revenue(conn, date(2026, 1, 1), date(2026, 1, 31))

        assert isinstance(result[0]["total_revenue"], float)
        assert result[0]["total_revenue"] == 566.40

    def test_uses_index_friendly_range_predicate(self):
        conn, cursor = _make_conn()
        report_repository.get_daily_revenue(conn, date(2026, 1, 1), date(2026, 1, 31))

        sql, params = cursor.execute.call_args.args
        assert "DATE(o.ordered_at)" not in sql.split("WHERE")[1].split("GROUP BY")[0]
        assert "ordered_at >= %s" in sql
        assert "DATE_ADD(%s, INTERVAL 1 DAY)" in sql
        assert params == (date(2026, 1, 1), date(2026, 1, 31))

    def test_filters_delivered_only(self):
        conn, cursor = _make_conn()
        report_repository.get_daily_revenue(conn, date(2026, 1, 1), date(2026, 1, 31))
        assert "o.status = 'delivered'" in cursor.execute.call_args.args[0]

    def test_raises_database_error(self):
        conn, cursor = _make_conn()
        cursor.execute.side_effect = MySQLError("boom")
        with pytest.raises(DatabaseError):
            report_repository.get_daily_revenue(conn, date(2026, 1, 1), date(2026, 1, 31))


class TestGetRevenueByCategory:

    def test_normalises_category_revenue(self):
        rows = [{"category": "Cake", "orders_count": 5, "units_sold": 9,
                  "category_revenue": Decimal("1200.00")}]
        conn, cursor = _make_conn(fetchall_return=rows)

        result = report_repository.get_revenue_by_category(conn, date(2026, 1, 1), date(2026, 1, 31))
        assert isinstance(result[0]["category_revenue"], float)

    def test_raises_database_error(self):
        conn, cursor = _make_conn()
        cursor.execute.side_effect = MySQLError("boom")
        with pytest.raises(DatabaseError):
            report_repository.get_revenue_by_category(conn, date(2026, 1, 1), date(2026, 1, 31))


class TestGetTopProducts:

    def test_applies_limit_param(self):
        conn, cursor = _make_conn()
        report_repository.get_top_products(conn, date(2026, 1, 1), date(2026, 1, 31), limit=5)

        params = cursor.execute.call_args.args[1]
        assert params[-1] == 5

    def test_normalises_product_revenue(self):
        rows = [{"product": "Butter Croissant", "category": "Pastry",
                  "units_sold": 42, "product_revenue": Decimal("2100.00")}]
        conn, cursor = _make_conn(fetchall_return=rows)

        result = report_repository.get_top_products(conn, date(2026, 1, 1), date(2026, 1, 31))
        assert isinstance(result[0]["product_revenue"], float)

    def test_raises_database_error(self):
        conn, cursor = _make_conn()
        cursor.execute.side_effect = MySQLError("boom")
        with pytest.raises(DatabaseError):
            report_repository.get_top_products(conn, date(2026, 1, 1), date(2026, 1, 31))


# =============================================================================
# report_service
# =============================================================================

class TestGetLowStockReport:

    @patch("services.report_service.report_repository")
    def test_returns_low_stock_report_with_count(self, mock_repo):
        mock_repo.get_low_stock.return_value = [{
            "product_id": 3, "category": "Pastry", "product": "Butter Croissant",
            "quantity_on_hand": 4, "reorder_level": 10, "reorder_quantity": 50,
            "units_below_threshold": 6, "last_restocked_at": None,
        }]
        conn = MagicMock()

        result = report_service.get_low_stock_report(conn)

        assert isinstance(result, LowStockReport)
        assert result.count == 1
        assert result.items[0].product == "Butter Croissant"

    @patch("services.report_service.report_repository")
    def test_empty_report_has_zero_count(self, mock_repo):
        mock_repo.get_low_stock.return_value = []
        conn = MagicMock()

        result = report_service.get_low_stock_report(conn)
        assert result.count == 0
        assert result.items == []


class TestGetRevenueReport:

    @patch("services.report_service.report_repository")
    def test_assembles_full_report(self, mock_repo):
        mock_repo.get_daily_revenue.return_value = [{
            "order_date": date(2026, 1, 15), "orders_delivered": 3,
            "total_subtotal": 500.0, "total_discounts": 20.0,
            "total_tax": 86.4, "total_revenue": 566.4,
        }]
        mock_repo.get_revenue_by_category.return_value = [{
            "category": "Cake", "orders_count": 5, "units_sold": 9, "category_revenue": 1200.0,
        }]
        mock_repo.get_top_products.return_value = [{
            "product": "Butter Croissant", "category": "Pastry",
            "units_sold": 42, "product_revenue": 2100.0,
        }]
        conn = MagicMock()

        result = report_service.get_revenue_report(conn, date(2026, 1, 1), date(2026, 1, 31))

        assert isinstance(result, RevenueReport)
        assert len(result.daily) == 1
        assert len(result.by_category) == 1
        assert len(result.top_products) == 1

    def test_date_from_after_date_to_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            report_service.get_revenue_report(conn, date(2026, 2, 1), date(2026, 1, 1))
        assert exc_info.value.error_code == "INVALID_DATE_RANGE"

    def test_range_too_wide_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError) as exc_info:
            report_service.get_revenue_report(conn, date(2020, 1, 1), date(2026, 1, 1))
        assert exc_info.value.error_code == "DATE_RANGE_TOO_WIDE"

    @patch("services.report_service.report_repository")
    def test_single_day_range_is_valid(self, mock_repo):
        mock_repo.get_daily_revenue.return_value = []
        mock_repo.get_revenue_by_category.return_value = []
        mock_repo.get_top_products.return_value = []
        conn = MagicMock()

        result = report_service.get_revenue_report(conn, date(2026, 1, 15), date(2026, 1, 15))
        assert result.date_from == result.date_to == date(2026, 1, 15)
