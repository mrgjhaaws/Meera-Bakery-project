"""
utils/financial.py
==================
Pure financial calculation functions for the Meera Bakery API.

These functions implement the exact calculation order mandated by the database
design (see database/schema/06_create_orders.sql and the design plan):

    1. line_total     = (unit_price × quantity) − item_discount
    2. subtotal       = SUM(line_total)
    3. discount_amount = flat OR percent (mutually exclusive, app enforces)
    4. taxable_amount = subtotal − discount_amount
    5. tax_amount     = taxable_amount × tax_percent / 100
    6. total_amount   = taxable_amount + tax_amount

Design rules enforced here
--------------------------
- All arithmetic uses Python's Decimal type to match DECIMAL(10,2) in MySQL
  and avoid floating-point rounding errors.
- Inputs may arrive as float/int from JSON — they are normalised to Decimal
  internally and rounded to 2 decimal places before returning.
- Discount mechanisms are mutually exclusive per order and per line item:
  if both flat and percent are non-zero, BusinessRuleError is raised.
- Negative results are clamped to zero (e.g. discount > gross total).
- All returned values are Python Decimal rounded to 2 d.p., ready to be
  written directly into DECIMAL(10,2) columns.

Usage
-----
    from utils.financial import calculate_line_total, calculate_order_totals

    line = calculate_line_total(
        unit_price=Decimal("50.00"),
        quantity=2,
        item_discount_amount=Decimal("0.00"),
        item_discount_percent=Decimal("10.00"),
    )
    # Returns LineTotal(gross=Decimal("100.00"), discount=Decimal("10.00"),
    #                   line_total=Decimal("90.00"), ...)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from utils.exceptions import BusinessRuleError

# Two-decimal-place quantizer
_TWO_PLACES = Decimal("0.01")


def _d(value: float | int | str | Decimal) -> Decimal:
    """Normalise any numeric input to a Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round2(value: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP (standard financial rounding)."""
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _clamp_zero(value: Decimal) -> Decimal:
    """Ensure a value cannot go below zero."""
    return max(value, Decimal("0.00"))


# =============================================================================
# Line-item calculation
# =============================================================================

@dataclass(frozen=True)
class LineTotal:
    """Result of calculate_line_total()."""
    gross: Decimal               # unit_price × quantity (before discount)
    item_discount_amount: Decimal  # flat discount applied (stored in DB)
    item_discount_percent: Decimal  # percent stored (0 if flat was used)
    discount_applied: Decimal    # actual monetary discount deducted
    line_total: Decimal          # gross − discount_applied  (stored in DB)


def calculate_line_total(
    unit_price: float | int | str | Decimal,
    quantity: int,
    item_discount_amount: float | int | str | Decimal = 0,
    item_discount_percent: float | int | str | Decimal = 0,
) -> LineTotal:
    """Calculate the line total for one order item.

    Parameters
    ----------
    unit_price            : Price per unit (snapshot from products.unit_price).
    quantity              : Number of units (>= 1).
    item_discount_amount  : Flat monetary discount for this line (default 0).
    item_discount_percent : Percentage discount for this line (default 0, 0–100).

    Returns
    -------
    LineTotal dataclass with all computed values.

    Raises
    ------
    BusinessRuleError
        If both item_discount_amount and item_discount_percent are non-zero
        (mutually exclusive discount mechanisms).
    ValueError
        If quantity < 1, unit_price < 0, or discount values are out of range.
    """
    price = _d(unit_price)
    qty = int(quantity)
    flat = _d(item_discount_amount)
    pct = _d(item_discount_percent)

    # --- Input validation ----------------------------------------------------
    if qty < 1:
        raise ValueError(f"quantity must be >= 1, got {qty}")
    if price < Decimal("0"):
        raise ValueError(f"unit_price must be >= 0, got {price}")
    if flat < Decimal("0"):
        raise ValueError(f"item_discount_amount must be >= 0, got {flat}")
    if not (Decimal("0") <= pct <= Decimal("100")):
        raise ValueError(f"item_discount_percent must be 0–100, got {pct}")

    # Mutually exclusive discount check
    if flat > Decimal("0") and pct > Decimal("0"):
        raise BusinessRuleError(
            error_code="INVALID_DISCOUNT",
            message=(
                "Cannot apply both a flat discount and a percentage discount "
                "to the same line item. Use one or the other."
            ),
            detail={
                "item_discount_amount": str(flat),
                "item_discount_percent": str(pct),
            },
        )

    # --- Calculation ---------------------------------------------------------
    gross = _round2(price * qty)

    if pct > Decimal("0"):
        # Percentage discount path
        discount_applied = _round2(gross * pct / Decimal("100"))
        stored_flat = Decimal("0.00")
        stored_pct = pct
    else:
        # Flat discount path (or no discount at all)
        discount_applied = _round2(flat)
        stored_flat = flat
        stored_pct = Decimal("0.00")

    line_total = _clamp_zero(_round2(gross - discount_applied))

    return LineTotal(
        gross=gross,
        item_discount_amount=_round2(stored_flat),
        item_discount_percent=_round2(stored_pct),
        discount_applied=_round2(discount_applied),
        line_total=line_total,
    )


# =============================================================================
# Order-level calculation
# =============================================================================

@dataclass(frozen=True)
class OrderTotals:
    """Result of calculate_order_totals()."""
    subtotal: Decimal         # SUM(line_totals)
    discount_amount: Decimal  # flat discount applied at order level (stored in DB)
    discount_percent: Decimal # percent discount stored (0 if flat was used)
    taxable_amount: Decimal   # subtotal − discount_applied
    tax_percent: Decimal      # tax rate stored
    tax_amount: Decimal       # taxable_amount × tax_percent / 100
    total_amount: Decimal     # taxable_amount + tax_amount


def calculate_order_totals(
    line_totals: List[float | int | str | Decimal],
    discount_amount: float | int | str | Decimal = 0,
    discount_percent: float | int | str | Decimal = 0,
    tax_percent: float | int | str | Decimal = 0,
) -> OrderTotals:
    """Calculate all financial totals for an order header.

    Implements the mandatory calculation sequence from the design plan:
        subtotal → discount → taxable_amount → tax_amount → total_amount

    Parameters
    ----------
    line_totals       : List of already-calculated line totals (from calculate_line_total).
    discount_amount   : Flat order-level discount (default 0).
    discount_percent  : Percentage order-level discount (default 0, 0–100).
    tax_percent       : Tax rate, e.g. 18.00 for GST 18% (default 0).

    Returns
    -------
    OrderTotals dataclass.

    Raises
    ------
    BusinessRuleError
        If both discount_amount and discount_percent are non-zero.
    ValueError
        If any input value is out of valid range.
    """
    flat = _d(discount_amount)
    pct = _d(discount_percent)
    tax_pct = _d(tax_percent)

    # --- Input validation ----------------------------------------------------
    if flat < Decimal("0"):
        raise ValueError(f"discount_amount must be >= 0, got {flat}")
    if not (Decimal("0") <= pct <= Decimal("100")):
        raise ValueError(f"discount_percent must be 0–100, got {pct}")
    if tax_pct < Decimal("0"):
        raise ValueError(f"tax_percent must be >= 0, got {tax_pct}")
    if not line_totals:
        raise ValueError("line_totals must not be empty")

    # Mutually exclusive discount check
    if flat > Decimal("0") and pct > Decimal("0"):
        raise BusinessRuleError(
            error_code="INVALID_DISCOUNT",
            message=(
                "Cannot apply both a flat discount and a percentage discount "
                "to the same order. Use one or the other."
            ),
            detail={
                "discount_amount": str(flat),
                "discount_percent": str(pct),
            },
        )

    # --- Step 1: subtotal ----------------------------------------------------
    subtotal = _round2(sum(_d(lt) for lt in line_totals))

    # --- Step 2: discount ----------------------------------------------------
    if pct > Decimal("0"):
        discount_applied = _round2(subtotal * pct / Decimal("100"))
        stored_flat = Decimal("0.00")
        stored_pct = pct
    else:
        discount_applied = _round2(flat)
        stored_flat = flat
        stored_pct = Decimal("0.00")

    # Discount cannot exceed subtotal
    discount_applied = _clamp_zero(min(discount_applied, subtotal))

    # --- Step 3: taxable_amount ----------------------------------------------
    taxable_amount = _clamp_zero(_round2(subtotal - discount_applied))

    # --- Step 4: tax_amount --------------------------------------------------
    tax_amount = _round2(taxable_amount * tax_pct / Decimal("100"))

    # --- Step 5: total_amount ------------------------------------------------
    total_amount = _round2(taxable_amount + tax_amount)

    return OrderTotals(
        subtotal=subtotal,
        discount_amount=_round2(stored_flat),
        discount_percent=_round2(stored_pct),
        taxable_amount=taxable_amount,
        tax_percent=_round2(tax_pct),
        tax_amount=tax_amount,
        total_amount=total_amount,
    )


# =============================================================================
# Valid order status transitions
# =============================================================================

# Maps each status to the set of statuses it may legally transition to.
# Used by order_service.py when processing PATCH /orders/{id}/status.
VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending":   {"confirmed", "cancelled"},
    "confirmed": {"preparing", "cancelled"},
    "preparing": {"shipped",   "cancelled"},
    "shipped":   {"delivered"},
    "delivered": set(),   # terminal — no further transitions
    "cancelled": set(),   # terminal — no further transitions
}

# Statuses that require an inventory DECREMENT when entered
INVENTORY_DECREMENT_ON: set[str] = {"confirmed"}

# Statuses that require an inventory INCREMENT (reversal) when entered
INVENTORY_INCREMENT_ON: set[str] = {"cancelled"}

# Statuses from which cancellation should NOT reverse inventory
# (inventory was never decremented yet)
NO_INVENTORY_REVERSAL_FROM: set[str] = {"pending"}


def validate_status_transition(current: str, requested: str) -> None:
    """Raise BusinessRuleError if the transition is not permitted.

    Parameters
    ----------
    current   : Current order status (from the database row).
    requested : Requested new status (from the API request body).

    Raises
    ------
    BusinessRuleError
        If the transition is invalid.
    """
    allowed = VALID_STATUS_TRANSITIONS.get(current, set())
    if requested not in allowed:
        raise BusinessRuleError(
            error_code="INVALID_STATUS_TRANSITION",
            message=(
                f"Cannot move order from '{current}' to '{requested}'. "
                f"Allowed transitions: {sorted(allowed) if allowed else 'none (terminal state)'}."
            ),
            detail={
                "current_status": current,
                "requested_status": requested,
                "allowed_transitions": sorted(allowed),
            },
        )
