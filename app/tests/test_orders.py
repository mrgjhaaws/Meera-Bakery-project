"""
tests/test_orders.py
=====================
Unit tests for inventory_repository, order_repository, and order_service.

Strategy
--------
- No real database — PooledMySQLConnection replaced with MagicMock.
- Repository tests verify: SQL delegation, DECIMAL->float normalisation,
  FOR UPDATE stock check semantics, NotFoundError / InsufficientStockError /
  DatabaseError raised at the right points.
- Service tests patch each repository module used by order_service so the
  business-rule logic (validation order, discount exclusivity delegation,
  inventory side effects per status transition) can be verified without
  touching SQL at all.

Run with:
    cd C:\\MeeraBakery\\app
    pytest tests/test_orders.py -v
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from mysql.connector import Error as MySQLError

from models.order import OrderCreate, OrderItemCreate, OrderResponse, OrderStatus
from repositories import inventory_repository, order_repository
from services import order_service
from utils.exceptions import (
    BusinessRuleError,
    DatabaseError,
    InsufficientStockError,
    NotFoundError,
)


# =============================================================================
# Shared helpers
# =============================================================================

def _make_conn(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def _order_row(**overrides) -> dict:
    base = {
        "order_id": 1,
        "customer_id": 1,
        "address_id": 1,
        "shipping_address_snapshot": "42 MG Road, Bengaluru, Karnataka 560001, India",
        "status": "pending",
        "subtotal": Decimal("200.00"),
        "discount_amount": Decimal("0.00"),
        "discount_percent": Decimal("0.00"),
        "taxable_amount": Decimal("200.00"),
        "tax_percent": Decimal("18.00"),
        "tax_amount": Decimal("36.00"),
        "total_amount": Decimal("236.00"),
        "notes": None,
        "ordered_at": datetime(2026, 1, 15, 10, 0, 0),
        "created_at": datetime(2026, 1, 15, 10, 0, 0),
        "updated_at": datetime(2026, 1, 15, 10, 0, 0),
    }
    base.update(overrides)
    return base


def _item_row(**overrides) -> dict:
    base = {
        "order_item_id": 1,
        "order_id": 1,
        "product_id": 3,
        "product_name": "Butter Croissant",
        "quantity": 2,
        "unit_price_at_order": Decimal("50.00"),
        "item_discount_amount": Decimal("0.00"),
        "item_discount_percent": Decimal("0.00"),
        "line_total": Decimal("100.00"),
        "created_at": datetime(2026, 1, 15, 10, 0, 0),
        "updated_at": datetime(2026, 1, 15, 10, 0, 0),
    }
    base.update(overrides)
    return base


# =============================================================================
# inventory_repository
# =============================================================================

class TestInventoryRepositoryDecrement:

    def test_success_decrements_stock(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"quantity_on_hand": 10}
        conn = _make_conn(cursor)

        inventory_repository.decrement_stock(conn, 3, "Butter Croissant", 4)

        update_call = cursor.execute.call_args_list[1]
        assert "SET    quantity_on_hand = quantity_on_hand - %s" in update_call.args[0]
        assert update_call.args[1] == (4, 3)

    def test_raises_insufficient_stock(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"quantity_on_hand": 2}
        conn = _make_conn(cursor)

        with pytest.raises(InsufficientStockError) as exc_info:
            inventory_repository.decrement_stock(conn, 3, "Butter Croissant", 5)

        assert exc_info.value.detail["requested"] == 5
        assert exc_info.value.detail["available"] == 2

    def test_raises_not_found_when_no_inventory_row(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = _make_conn(cursor)

        with pytest.raises(NotFoundError):
            inventory_repository.decrement_stock(conn, 99, "Ghost Product", 1)

    def test_uses_select_for_update(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"quantity_on_hand": 10}
        conn = _make_conn(cursor)

        inventory_repository.decrement_stock(conn, 3, "Butter Croissant", 1)

        select_call = cursor.execute.call_args_list[0]
        assert "FOR UPDATE" in select_call.args[0]

    def test_raises_database_error_on_mysql_error(self):
        cursor = MagicMock()
        cursor.execute.side_effect = MySQLError("connection lost")
        conn = _make_conn(cursor)

        with pytest.raises(DatabaseError):
            inventory_repository.decrement_stock(conn, 3, "Butter Croissant", 1)


class TestInventoryRepositoryIncrement:

    def test_success_increments_stock(self):
        cursor = MagicMock()
        cursor.rowcount = 1
        conn = _make_conn(cursor)

        inventory_repository.increment_stock(conn, 3, 2)

        cursor.execute.assert_called_once()
        args = cursor.execute.call_args.args
        assert "quantity_on_hand + %s" in args[0]
        assert args[1] == (2, 3)

    def test_raises_not_found_when_zero_rows_affected(self):
        cursor = MagicMock()
        cursor.rowcount = 0
        conn = _make_conn(cursor)

        with pytest.raises(NotFoundError):
            inventory_repository.increment_stock(conn, 99, 2)

    def test_raises_database_error_on_mysql_error(self):
        cursor = MagicMock()
        cursor.execute.side_effect = MySQLError("deadlock")
        conn = _make_conn(cursor)

        with pytest.raises(DatabaseError):
            inventory_repository.increment_stock(conn, 3, 2)


# =============================================================================
# order_repository
# =============================================================================

class TestOrderRepositoryGetById:

    def test_returns_order_with_items_and_normalised_decimals(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = _order_row()
        cursor.fetchall.return_value = [_item_row()]
        conn = _make_conn(cursor)

        result = order_repository.get_by_id(conn, 1)

        assert isinstance(result["total_amount"], float)
        assert result["total_amount"] == 236.00
        assert len(result["items"]) == 1
        assert isinstance(result["items"][0]["line_total"], float)
        assert result["items"][0]["line_total"] == 100.00

    def test_raises_not_found_when_order_missing(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = _make_conn(cursor)

        with pytest.raises(NotFoundError):
            order_repository.get_by_id(conn, 999)

    def test_raises_database_error_on_mysql_error(self):
        cursor = MagicMock()
        cursor.execute.side_effect = MySQLError("boom")
        conn = _make_conn(cursor)

        with pytest.raises(DatabaseError):
            order_repository.get_by_id(conn, 1)

    def test_order_with_zero_items_still_returns(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = _order_row()
        cursor.fetchall.return_value = []
        conn = _make_conn(cursor)

        result = order_repository.get_by_id(conn, 1)
        assert result["items"] == []


class TestOrderRepositoryGetAll:

    def test_returns_total_and_rows(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"total": 2}]
        cursor.fetchall.return_value = [
            {
                "order_id": 1, "customer_id": 1, "status": "pending",
                "total_amount": Decimal("236.00"), "item_count": 2,
                "ordered_at": datetime(2026, 1, 15, 10, 0, 0),
            }
        ]
        conn = _make_conn(cursor)

        total, rows = order_repository.get_all(conn, page=1, page_size=20)

        assert total == 2
        assert isinstance(rows[0]["total_amount"], float)

    def test_applies_customer_and_status_filters(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"total": 0}]
        cursor.fetchall.return_value = []
        conn = _make_conn(cursor)

        order_repository.get_all(conn, customer_id=5, status="pending", page=1, page_size=20)

        count_call = cursor.execute.call_args_list[0]
        assert count_call.args[1] == [5, "pending"]

    def test_raises_database_error(self):
        cursor = MagicMock()
        cursor.execute.side_effect = MySQLError("boom")
        conn = _make_conn(cursor)

        with pytest.raises(DatabaseError):
            order_repository.get_all(conn)


class TestOrderRepositoryGetAllForCustomer:

    def test_raises_not_found_when_customer_missing(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = _make_conn(cursor)

        with pytest.raises(NotFoundError):
            order_repository.get_all_for_customer(conn, 999)

    def test_delegates_to_get_all_when_customer_exists(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"customer_id": 1}, {"total": 0}]
        cursor.fetchall.return_value = []
        conn = _make_conn(cursor)

        total, rows = order_repository.get_all_for_customer(conn, 1)
        assert total == 0
        assert rows == []


class TestOrderRepositoryCreate:

    def test_inserts_header_and_items_returns_new_id(self):
        cursor = MagicMock()
        cursor.lastrowid = 42
        conn = _make_conn(cursor)

        order_data = {"customer_id": 1, "address_id": 1}
        items_data = [{"product_id": 3, "quantity": 2}]

        new_id = order_repository.create(conn, order_data, items_data)

        assert new_id == 42
        assert items_data[0]["order_id"] == 42
        assert cursor.execute.call_count == 2  # 1 header + 1 item

    def test_multiple_items_all_inserted(self):
        cursor = MagicMock()
        cursor.lastrowid = 7
        conn = _make_conn(cursor)

        items_data = [{"product_id": 1}, {"product_id": 2}, {"product_id": 3}]
        order_repository.create(conn, {"customer_id": 1}, items_data)

        assert cursor.execute.call_count == 4  # 1 header + 3 items
        assert all(item["order_id"] == 7 for item in items_data)

    def test_raises_database_error_on_mysql_error(self):
        cursor = MagicMock()
        cursor.execute.side_effect = MySQLError("dup key")
        conn = _make_conn(cursor)

        with pytest.raises(DatabaseError):
            order_repository.create(conn, {}, [{}])


class TestOrderRepositoryUpdateStatus:

    def test_success(self):
        cursor = MagicMock()
        cursor.rowcount = 1
        conn = _make_conn(cursor)

        order_repository.update_status(conn, 1, "confirmed")
        cursor.execute.assert_called_once()
        assert cursor.execute.call_args.args[1] == ("confirmed", 1)

    def test_raises_not_found_when_zero_rows(self):
        cursor = MagicMock()
        cursor.rowcount = 0
        conn = _make_conn(cursor)

        with pytest.raises(NotFoundError):
            order_repository.update_status(conn, 999, "confirmed")

    def test_raises_database_error(self):
        cursor = MagicMock()
        cursor.execute.side_effect = MySQLError("boom")
        conn = _make_conn(cursor)

        with pytest.raises(DatabaseError):
            order_repository.update_status(conn, 1, "confirmed")


# =============================================================================
# order_service
# =============================================================================

_CUSTOMER = {"customer_id": 1, "is_active": True}
_ADDRESS = {
    "address_id": 1, "customer_id": 1, "is_active": True,
    "address_line1": "42 MG Road", "address_line2": "Flat 3B",
    "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    "country": "India",
}
_PRODUCT = {
    "product_id": 3, "name": "Butter Croissant", "unit_price": 50.00,
    "is_active": True,
}


def _order_create_payload(**item_overrides) -> OrderCreate:
    item = {"product_id": 3, "quantity": 2}
    item.update(item_overrides)
    return OrderCreate(
        customer_id=1,
        address_id=1,
        items=[OrderItemCreate(**item)],
        tax_percent=18.0,
    )


class TestFormatAddressSnapshot:

    def test_includes_line2_when_present(self):
        snapshot = order_service._format_address_snapshot(_ADDRESS)
        assert snapshot == "42 MG Road, Flat 3B, Bengaluru, Karnataka 560001, India"

    def test_omits_line2_when_absent(self):
        addr = dict(_ADDRESS)
        addr["address_line2"] = None
        snapshot = order_service._format_address_snapshot(addr)
        assert snapshot == "42 MG Road, Bengaluru, Karnataka 560001, India"


class TestCreateOrder:

    @patch("services.order_service.get_order")
    @patch("services.order_service.order_repository")
    @patch("services.order_service.product_repository")
    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_happy_path_commits_and_returns_order(
        self, mock_customer_repo, mock_address_repo, mock_product_repo,
        mock_order_repo, mock_get_order,
    ):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = _ADDRESS
        mock_product_repo.get_by_id.return_value = _PRODUCT
        mock_order_repo.create.return_value = 55
        mock_get_order.return_value = "SENTINEL_RESPONSE"

        conn = MagicMock()
        result = order_service.create_order(conn, _order_create_payload())

        mock_order_repo.create.assert_called_once()
        conn.commit.assert_called_once()
        mock_get_order.assert_called_once_with(conn, 55)
        assert result == "SENTINEL_RESPONSE"

    @patch("services.order_service.customer_repository")
    def test_inactive_customer_raises_business_rule_error(self, mock_customer_repo):
        mock_customer_repo.get_by_id.return_value = {"customer_id": 1, "is_active": False}
        conn = MagicMock()

        with pytest.raises(BusinessRuleError) as exc_info:
            order_service.create_order(conn, _order_create_payload())
        assert exc_info.value.error_code == "CUSTOMER_INACTIVE"

    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_address_belonging_to_different_customer_raises(
        self, mock_customer_repo, mock_address_repo
    ):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = {**_ADDRESS, "customer_id": 999}
        conn = MagicMock()

        with pytest.raises(BusinessRuleError) as exc_info:
            order_service.create_order(conn, _order_create_payload())
        assert exc_info.value.error_code == "ADDRESS_CUSTOMER_MISMATCH"

    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_inactive_address_raises(self, mock_customer_repo, mock_address_repo):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = {**_ADDRESS, "is_active": False}
        conn = MagicMock()

        with pytest.raises(BusinessRuleError) as exc_info:
            order_service.create_order(conn, _order_create_payload())
        assert exc_info.value.error_code == "ADDRESS_INACTIVE"

    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_duplicate_product_in_items_raises(self, mock_customer_repo, mock_address_repo):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = _ADDRESS
        conn = MagicMock()

        payload = OrderCreate(
            customer_id=1, address_id=1,
            items=[
                OrderItemCreate(product_id=3, quantity=1),
                OrderItemCreate(product_id=3, quantity=2),
            ],
        )

        with pytest.raises(BusinessRuleError) as exc_info:
            order_service.create_order(conn, payload)
        assert exc_info.value.error_code == "DUPLICATE_PRODUCT_IN_ORDER"

    @patch("services.order_service.product_repository")
    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_inactive_product_raises(
        self, mock_customer_repo, mock_address_repo, mock_product_repo
    ):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = _ADDRESS
        mock_product_repo.get_by_id.return_value = {**_PRODUCT, "is_active": False}
        conn = MagicMock()

        with pytest.raises(BusinessRuleError) as exc_info:
            order_service.create_order(conn, _order_create_payload())
        assert exc_info.value.error_code == "PRODUCT_INACTIVE"

    @patch("services.order_service.product_repository")
    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_product_not_found_propagates(
        self, mock_customer_repo, mock_address_repo, mock_product_repo
    ):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = _ADDRESS
        mock_product_repo.get_by_id.side_effect = NotFoundError("product", 3)
        conn = MagicMock()

        with pytest.raises(NotFoundError):
            order_service.create_order(conn, _order_create_payload())

    @patch("services.order_service.get_order")
    @patch("services.order_service.order_repository")
    @patch("services.order_service.product_repository")
    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_does_not_touch_inventory_at_creation(
        self, mock_customer_repo, mock_address_repo, mock_product_repo,
        mock_order_repo, mock_get_order,
    ):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = _ADDRESS
        mock_product_repo.get_by_id.return_value = _PRODUCT
        mock_order_repo.create.return_value = 1
        mock_get_order.return_value = MagicMock()

        conn = MagicMock()
        with patch("services.order_service.inventory_repository") as mock_inv:
            order_service.create_order(conn, _order_create_payload())
            mock_inv.decrement_stock.assert_not_called()
            mock_inv.increment_stock.assert_not_called()

    @patch("services.order_service.get_order")
    @patch("services.order_service.order_repository")
    @patch("services.order_service.product_repository")
    @patch("services.order_service.address_repository")
    @patch("services.order_service.customer_repository")
    def test_financial_totals_passed_to_repository_create(
        self, mock_customer_repo, mock_address_repo, mock_product_repo,
        mock_order_repo, mock_get_order,
    ):
        mock_customer_repo.get_by_id.return_value = _CUSTOMER
        mock_address_repo.get_by_id.return_value = _ADDRESS
        mock_product_repo.get_by_id.return_value = _PRODUCT
        mock_order_repo.create.return_value = 1
        mock_get_order.return_value = MagicMock()

        conn = MagicMock()
        order_service.create_order(conn, _order_create_payload(quantity=2))

        _, order_row, items_data = mock_order_repo.create.call_args.args
        # unit_price 50.00 x qty 2 = 100.00 subtotal; 18% tax -> 18.00 tax
        assert order_row["subtotal"] == Decimal("100.00")
        assert order_row["tax_amount"] == Decimal("18.00")
        assert order_row["total_amount"] == Decimal("118.00")
        assert items_data[0]["unit_price_at_order"] == Decimal("50.00")


class TestGetOrder:

    @patch("services.order_service.order_repository")
    def test_builds_order_response_with_items(self, mock_order_repo):
        row = _order_row()
        row["items"] = [_item_row()]
        mock_order_repo.get_by_id.return_value = row
        conn = MagicMock()

        result = order_service.get_order(conn, 1)

        assert isinstance(result, OrderResponse)
        assert result.order_id == 1
        assert len(result.items) == 1
        assert result.items[0].product_name == "Butter Croissant"


class TestListOrders:

    @patch("services.order_service.order_repository")
    def test_page_size_capped(self, mock_order_repo):
        mock_order_repo.get_all.return_value = (0, [])
        conn = MagicMock()

        order_service.list_orders(conn, page=1, page_size=500)

        _, kwargs = mock_order_repo.get_all.call_args
        assert kwargs["page_size"] == 100

    def test_page_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError):
            order_service.list_orders(conn, page=0)

    def test_page_size_zero_raises(self):
        conn = MagicMock()
        with pytest.raises(BusinessRuleError):
            order_service.list_orders(conn, page_size=0)

    @patch("services.order_service.order_repository")
    def test_filters_included_in_response(self, mock_order_repo):
        mock_order_repo.get_all.return_value = (0, [])
        conn = MagicMock()

        result = order_service.list_orders(conn, customer_id=5, status="pending")
        assert result.filters == {"customer_id": 5, "status": "pending"}


class TestListOrdersForCustomer:

    @patch("services.order_service.order_repository")
    def test_delegates_and_includes_customer_filter(self, mock_order_repo):
        mock_order_repo.get_all_for_customer.return_value = (0, [])
        conn = MagicMock()

        result = order_service.list_orders_for_customer(conn, 7)
        assert result.filters == {"customer_id": 7}

    @patch("services.order_service.order_repository")
    def test_not_found_propagates(self, mock_order_repo):
        mock_order_repo.get_all_for_customer.side_effect = NotFoundError("customer", 999)
        conn = MagicMock()

        with pytest.raises(NotFoundError):
            order_service.list_orders_for_customer(conn, 999)


class TestUpdateOrderStatus:

    @patch("services.order_service.get_order")
    @patch("services.order_service.order_repository")
    @patch("services.order_service.inventory_repository")
    def test_confirm_decrements_inventory_for_each_item(
        self, mock_inv, mock_order_repo, mock_get_order
    ):
        current = _order_row(status="pending")
        current["items"] = [_item_row(product_id=3, quantity=2), _item_row(product_id=4, quantity=1)]
        mock_order_repo.get_by_id.return_value = current
        mock_get_order.return_value = MagicMock()
        conn = MagicMock()

        order_service.update_order_status(conn, 1, OrderStatus.confirmed)

        assert mock_inv.decrement_stock.call_count == 2
        mock_order_repo.update_status.assert_called_once_with(conn, 1, "confirmed")
        conn.commit.assert_called_once()

    @patch("services.order_service.order_repository")
    @patch("services.order_service.inventory_repository")
    def test_invalid_transition_raises_and_skips_inventory(self, mock_inv, mock_order_repo):
        current = _order_row(status="delivered")
        current["items"] = [_item_row()]
        mock_order_repo.get_by_id.return_value = current
        conn = MagicMock()

        with pytest.raises(BusinessRuleError):
            order_service.update_order_status(conn, 1, OrderStatus.confirmed)

        mock_inv.decrement_stock.assert_not_called()
        mock_order_repo.update_status.assert_not_called()

    @patch("services.order_service.get_order")
    @patch("services.order_service.order_repository")
    @patch("services.order_service.inventory_repository")
    def test_cancel_from_confirmed_reverses_inventory(
        self, mock_inv, mock_order_repo, mock_get_order
    ):
        current = _order_row(status="confirmed")
        current["items"] = [_item_row(product_id=3, quantity=2)]
        mock_order_repo.get_by_id.return_value = current
        mock_get_order.return_value = MagicMock()
        conn = MagicMock()

        order_service.update_order_status(conn, 1, OrderStatus.cancelled)

        mock_inv.increment_stock.assert_called_once_with(conn, 3, 2)
        mock_inv.decrement_stock.assert_not_called()

    @patch("services.order_service.get_order")
    @patch("services.order_service.order_repository")
    @patch("services.order_service.inventory_repository")
    def test_cancel_from_pending_does_not_touch_inventory(
        self, mock_inv, mock_order_repo, mock_get_order
    ):
        current = _order_row(status="pending")
        current["items"] = [_item_row()]
        mock_order_repo.get_by_id.return_value = current
        mock_get_order.return_value = MagicMock()
        conn = MagicMock()

        order_service.update_order_status(conn, 1, OrderStatus.cancelled)

        mock_inv.increment_stock.assert_not_called()
        mock_inv.decrement_stock.assert_not_called()

    @patch("services.order_service.order_repository")
    @patch("services.order_service.inventory_repository")
    def test_insufficient_stock_blocks_confirmation(self, mock_inv, mock_order_repo):
        current = _order_row(status="pending")
        current["items"] = [_item_row(product_id=3, quantity=10)]
        mock_order_repo.get_by_id.return_value = current
        mock_inv.decrement_stock.side_effect = InsufficientStockError(3, "Butter Croissant", 10, 2)
        conn = MagicMock()

        with pytest.raises(InsufficientStockError):
            order_service.update_order_status(conn, 1, OrderStatus.confirmed)

        mock_order_repo.update_status.assert_not_called()
        conn.commit.assert_not_called()

    @patch("services.order_service.order_repository")
    def test_terminal_status_rejects_any_transition(self, mock_order_repo):
        current = _order_row(status="cancelled")
        current["items"] = []
        mock_order_repo.get_by_id.return_value = current
        conn = MagicMock()

        with pytest.raises(BusinessRuleError):
            order_service.update_order_status(conn, 1, OrderStatus.pending)
