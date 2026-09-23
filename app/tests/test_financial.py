"""
tests/test_financial.py
=======================
Unit tests for utils/financial.py.

These tests exercise every calculation path in isolation — no database,
no network, no FastAPI app required.  Run with:

    cd C:\\MeeraBakery\\app
    pytest tests/test_financial.py -v

Test coverage targets
---------------------
- calculate_line_total: no discount, flat discount, percent discount,
  mutual-exclusion error, edge cases (zero price, quantity=1)
- calculate_order_totals: no discount + no tax, flat discount + tax,
  percent discount + tax, discount > subtotal clamping, empty list error,
  mutual-exclusion error
- validate_status_transition: all valid transitions, all invalid transitions,
  terminal states
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from utils.exceptions import BusinessRuleError
from utils.financial import (
    VALID_STATUS_TRANSITIONS,
    LineTotal,
    OrderTotals,
    calculate_line_total,
    calculate_order_totals,
    validate_status_transition,
)


# =============================================================================
# Helpers
# =============================================================================

def d(value: str) -> Decimal:
    """Shorthand for Decimal(value)."""
    return Decimal(value)


# =============================================================================
# calculate_line_total
# =============================================================================

class TestCalculateLineTotal:

    def test_no_discount(self):
        result = calculate_line_total(unit_price="50.00", quantity=2)
        assert isinstance(result, LineTotal)
        assert result.gross == d("100.00")
        assert result.discount_applied == d("0.00")
        assert result.line_total == d("100.00")
        assert result.item_discount_amount == d("0.00")
        assert result.item_discount_percent == d("0.00")

    def test_flat_discount(self):
        result = calculate_line_total(
            unit_price="50.00",
            quantity=2,
            item_discount_amount="10.00",
        )
        assert result.gross == d("100.00")
        assert result.discount_applied == d("10.00")
        assert result.line_total == d("90.00")
        assert result.item_discount_amount == d("10.00")
        assert result.item_discount_percent == d("0.00")

    def test_percent_discount(self):
        result = calculate_line_total(
            unit_price="50.00",
            quantity=2,
            item_discount_percent="10.00",
        )
        assert result.gross == d("100.00")
        assert result.discount_applied == d("10.00")
        assert result.line_total == d("90.00")
        assert result.item_discount_amount == d("0.00")
        assert result.item_discount_percent == d("10.00")

    def test_percent_discount_rounds_half_up(self):
        # 33.33% of 100.00 = 33.33 → line_total = 66.67
        result = calculate_line_total(
            unit_price="100.00",
            quantity=1,
            item_discount_percent="33.33",
        )
        assert result.discount_applied == d("33.33")
        assert result.line_total == d("66.67")

    def test_both_discounts_raises(self):
        with pytest.raises(BusinessRuleError) as exc_info:
            calculate_line_total(
                unit_price="50.00",
                quantity=2,
                item_discount_amount="5.00",
                item_discount_percent="10.00",
            )
        assert exc_info.value.error_code == "INVALID_DISCOUNT"

    def test_flat_discount_exceeds_gross_clamped_to_zero(self):
        result = calculate_line_total(
            unit_price="10.00",
            quantity=1,
            item_discount_amount="999.00",
        )
        assert result.line_total == d("0.00")

    def test_quantity_one(self):
        result = calculate_line_total(unit_price="350.00", quantity=1)
        assert result.gross == d("350.00")
        assert result.line_total == d("350.00")

    def test_zero_unit_price(self):
        result = calculate_line_total(unit_price="0.00", quantity=5)
        assert result.gross == d("0.00")
        assert result.line_total == d("0.00")

    def test_float_inputs_accepted(self):
        result = calculate_line_total(unit_price=50.0, quantity=2)
        assert result.line_total == d("100.00")

    def test_invalid_quantity_zero_raises(self):
        with pytest.raises(ValueError, match="quantity must be >= 1"):
            calculate_line_total(unit_price="50.00", quantity=0)

    def test_negative_unit_price_raises(self):
        with pytest.raises(ValueError, match="unit_price must be >= 0"):
            calculate_line_total(unit_price="-1.00", quantity=1)

    def test_negative_flat_discount_raises(self):
        with pytest.raises(ValueError, match="item_discount_amount must be >= 0"):
            calculate_line_total(
                unit_price="50.00", quantity=1, item_discount_amount="-5.00"
            )

    def test_discount_percent_over_100_raises(self):
        with pytest.raises(ValueError, match="item_discount_percent must be 0–100"):
            calculate_line_total(
                unit_price="50.00", quantity=1, item_discount_percent="101.00"
            )

    def test_100_percent_discount(self):
        result = calculate_line_total(
            unit_price="50.00",
            quantity=2,
            item_discount_percent="100.00",
        )
        assert result.line_total == d("0.00")


# =============================================================================
# calculate_order_totals
# =============================================================================

class TestCalculateOrderTotals:

    def test_no_discount_no_tax(self):
        result = calculate_order_totals(line_totals=["100.00", "350.00"])
        assert isinstance(result, OrderTotals)
        assert result.subtotal == d("450.00")
        assert result.discount_amount == d("0.00")
        assert result.discount_percent == d("0.00")
        assert result.taxable_amount == d("450.00")
        assert result.tax_percent == d("0.00")
        assert result.tax_amount == d("0.00")
        assert result.total_amount == d("450.00")

    def test_flat_discount_with_tax(self):
        # Subtotal=440, flat discount=50, taxable=390, GST 18%=70.20, total=460.20
        result = calculate_order_totals(
            line_totals=["90.00", "350.00"],
            discount_amount="50.00",
            tax_percent="18.00",
        )
        assert result.subtotal == d("440.00")
        assert result.discount_amount == d("50.00")
        assert result.taxable_amount == d("390.00")
        assert result.tax_amount == d("70.20")
        assert result.total_amount == d("460.20")

    def test_percent_discount_with_tax(self):
        # Subtotal=440, 10% discount=44, taxable=396, GST 18%=71.28, total=467.28
        result = calculate_order_totals(
            line_totals=["90.00", "350.00"],
            discount_percent="10.00",
            tax_percent="18.00",
        )
        assert result.subtotal == d("440.00")
        assert result.discount_percent == d("10.00")
        assert result.discount_amount == d("0.00")
        assert result.taxable_amount == d("396.00")
        assert result.tax_amount == d("71.28")
        assert result.total_amount == d("467.28")

    def test_tax_applied_on_post_discount_amount(self):
        """Tax must be calculated on taxable_amount, not on subtotal."""
        result = calculate_order_totals(
            line_totals=["200.00"],
            discount_amount="100.00",
            tax_percent="10.00",
        )
        # subtotal=200, discount=100, taxable=100, tax=10, total=110
        assert result.taxable_amount == d("100.00")
        assert result.tax_amount == d("10.00")
        assert result.total_amount == d("110.00")

    def test_discount_clamped_when_exceeds_subtotal(self):
        result = calculate_order_totals(
            line_totals=["50.00"],
            discount_amount="9999.00",
            tax_percent="18.00",
        )
        assert result.taxable_amount == d("0.00")
        assert result.tax_amount == d("0.00")
        assert result.total_amount == d("0.00")

    def test_both_discounts_raises(self):
        with pytest.raises(BusinessRuleError) as exc_info:
            calculate_order_totals(
                line_totals=["100.00"],
                discount_amount="10.00",
                discount_percent="5.00",
            )
        assert exc_info.value.error_code == "INVALID_DISCOUNT"

    def test_empty_line_totals_raises(self):
        with pytest.raises(ValueError, match="line_totals must not be empty"):
            calculate_order_totals(line_totals=[])

    def test_single_item_no_discount_no_tax(self):
        result = calculate_order_totals(line_totals=["120.00"])
        assert result.subtotal == d("120.00")
        assert result.total_amount == d("120.00")

    def test_decimal_inputs(self):
        result = calculate_order_totals(
            line_totals=[d("100.00"), d("50.00")],
            tax_percent=d("5.00"),
        )
        assert result.subtotal == d("150.00")
        assert result.tax_amount == d("7.50")
        assert result.total_amount == d("157.50")

    def test_zero_tax(self):
        result = calculate_order_totals(
            line_totals=["500.00"],
            discount_percent="20.00",
            tax_percent="0.00",
        )
        assert result.taxable_amount == d("400.00")
        assert result.tax_amount == d("0.00")
        assert result.total_amount == d("400.00")

    def test_rounding_consistency(self):
        """Three items at ₹33.33 each = ₹99.99, not ₹100.00."""
        result = calculate_order_totals(
            line_totals=["33.33", "33.33", "33.33"],
        )
        assert result.subtotal == d("99.99")
        assert result.total_amount == d("99.99")


# =============================================================================
# validate_status_transition
# =============================================================================

class TestValidateStatusTransition:

    @pytest.mark.parametrize("current,next_status", [
        ("pending",   "confirmed"),
        ("pending",   "cancelled"),
        ("confirmed", "preparing"),
        ("confirmed", "cancelled"),
        ("preparing", "shipped"),
        ("preparing", "cancelled"),
        ("shipped",   "delivered"),
    ])
    def test_valid_transitions(self, current: str, next_status: str):
        # Should not raise
        validate_status_transition(current, next_status)

    @pytest.mark.parametrize("current,next_status", [
        ("pending",   "preparing"),
        ("pending",   "shipped"),
        ("pending",   "delivered"),
        ("confirmed", "pending"),
        ("confirmed", "shipped"),
        ("confirmed", "delivered"),
        ("preparing", "pending"),
        ("preparing", "confirmed"),
        ("preparing", "delivered"),
        ("shipped",   "pending"),
        ("shipped",   "confirmed"),
        ("shipped",   "cancelled"),
        ("delivered", "cancelled"),
        ("delivered", "confirmed"),
        ("cancelled", "pending"),
        ("cancelled", "confirmed"),
    ])
    def test_invalid_transitions_raise(self, current: str, next_status: str):
        with pytest.raises(BusinessRuleError) as exc_info:
            validate_status_transition(current, next_status)
        assert exc_info.value.error_code == "INVALID_STATUS_TRANSITION"

    def test_terminal_delivered_raises(self):
        with pytest.raises(BusinessRuleError) as exc_info:
            validate_status_transition("delivered", "cancelled")
        assert "terminal state" in exc_info.value.message

    def test_terminal_cancelled_raises(self):
        with pytest.raises(BusinessRuleError) as exc_info:
            validate_status_transition("cancelled", "pending")
        assert exc_info.value.error_code == "INVALID_STATUS_TRANSITION"

    def test_all_statuses_present_in_map(self):
        """Every ENUM value in the DB must be represented in the transition map."""
        db_statuses = {
            "pending", "confirmed", "preparing",
            "shipped", "delivered", "cancelled",
        }
        assert set(VALID_STATUS_TRANSITIONS.keys()) == db_statuses
