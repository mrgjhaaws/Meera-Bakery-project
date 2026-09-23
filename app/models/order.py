"""
models/order.py
===============
Pydantic models for the orders and order_items resources.

Schema source of truth
----------------------
    database/schema/06_create_orders.sql
    database/schema/07_create_order_items.sql

orders columns
--------------
    order_id                   INT UNSIGNED      PK
    customer_id                INT UNSIGNED      NOT NULL  FK → customers
    address_id                 INT UNSIGNED      NULL      FK → addresses (SET NULL on delete)
    shipping_address_snapshot  TEXT              NOT NULL  immutable copy at order creation
    status                     ENUM(...)         NOT NULL  DEFAULT 'pending'
    subtotal                   DECIMAL(10,2)     NOT NULL
    discount_amount            DECIMAL(10,2)     NOT NULL  DEFAULT 0.00
    discount_percent           DECIMAL(5,2)      NOT NULL  DEFAULT 0.00
    taxable_amount             DECIMAL(10,2)     NOT NULL
    tax_percent                DECIMAL(5,2)      NOT NULL  DEFAULT 0.00
    tax_amount                 DECIMAL(10,2)     NOT NULL  DEFAULT 0.00
    total_amount               DECIMAL(10,2)     NOT NULL
    notes                      TEXT              NULL
    ordered_at                 DATETIME          NOT NULL  DEFAULT NOW
    created_at                 DATETIME          NOT NULL
    updated_at                 DATETIME          NOT NULL

order_items columns
-------------------
    order_item_id           INT UNSIGNED      PK
    order_id                INT UNSIGNED      NOT NULL  FK → orders (CASCADE)
    product_id              INT UNSIGNED      NOT NULL  FK → products (RESTRICT)
    quantity                SMALLINT UNSIGNED NOT NULL  CHECK >= 1
    unit_price_at_order     DECIMAL(10,2)     NOT NULL  immutable price snapshot
    item_discount_amount    DECIMAL(10,2)     NOT NULL  DEFAULT 0.00
    item_discount_percent   DECIMAL(5,2)      NOT NULL  DEFAULT 0.00
    line_total              DECIMAL(10,2)     NOT NULL
    created_at              DATETIME          NOT NULL
    updated_at              DATETIME          NOT NULL

Financial column conventions
----------------------------
- All DECIMAL(10,2) monetary fields are exposed as float in JSON responses,
  consistent with unit_price in ProductResponse/ProductSummary (Phase 2).
  The DECIMAL→float conversion happens in the repository layer.
- All DECIMAL(5,2) percentage fields are exposed as float in JSON responses.
- The repository layer performs the conversion; Pydantic receives plain floats.

Status ENUM values (from DB schema)
------------------------------------
    pending | confirmed | preparing | shipped | delivered | cancelled

Calculation order (enforced by order_service, documented here for reference)
-----------------------------------------------------------------------------
    subtotal        = SUM(order_items.line_total)
    discount_amount = flat  OR  subtotal × discount_percent / 100  (exclusive)
    taxable_amount  = subtotal − discount_amount
    tax_amount      = taxable_amount × tax_percent / 100
    total_amount    = taxable_amount + tax_amount

Model hierarchy
---------------
    OrderItemResponse    — single line item (embedded in OrderResponse)
    OrderItemSummary     — slim line item (used in OrderSummary)
    OrderResponse        — full order with embedded items (GET /orders/{id})
    OrderSummary         — slim order row without items (used in list responses)
    OrderListResponse    — paginated list wrapper
    OrderStatusUpdate    — request body for PATCH /orders/{id}/status
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Order status enum
# =============================================================================

class OrderStatus(str, Enum):
    """Mirrors the ENUM definition in 06_create_orders.sql exactly.

    Using str as the mixin means FastAPI serialises the value as a plain
    string (e.g. "pending") rather than the enum name.
    """
    pending   = "pending"
    confirmed = "confirmed"
    preparing = "preparing"
    shipped   = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


# =============================================================================
# Order item models
# =============================================================================

class OrderItemResponse(BaseModel):
    """Full line item embedded inside an OrderResponse.

    unit_price_at_order is the immutable price snapshot captured at order
    creation time — it never changes even if products.unit_price is updated.
    """

    model_config = ConfigDict(from_attributes=True)

    order_item_id: int = Field(..., description="Primary key", examples=[1])
    order_id: int = Field(..., description="FK to orders", examples=[1])
    product_id: int = Field(..., description="FK to products", examples=[3])
    product_name: str = Field(
        ...,
        description="Denormalised product name at query time (not a snapshot)",
        examples=["Butter Croissant"],
    )
    quantity: int = Field(
        ...,
        description="Number of units ordered (>= 1)",
        examples=[2],
    )
    unit_price_at_order: float = Field(
        ...,
        description="Immutable price-per-unit captured at order creation",
        examples=[50.00],
    )
    item_discount_amount: float = Field(
        ...,
        description="Flat item-level discount amount",
        examples=[0.00],
    )
    item_discount_percent: float = Field(
        ...,
        description="Percentage item-level discount (0.00–100.00)",
        examples=[0.00],
    )
    line_total: float = Field(
        ...,
        description="(unit_price_at_order × quantity) − item discount",
        examples=[100.00],
    )
    created_at: datetime = Field(..., description="UTC timestamp of creation")
    updated_at: datetime = Field(..., description="UTC timestamp of last update")


class OrderItemSummary(BaseModel):
    """Slim line item row returned inside OrderSummary list responses."""

    model_config = ConfigDict(from_attributes=True)

    order_item_id: int = Field(..., examples=[1])
    product_id: int = Field(..., examples=[3])
    product_name: str = Field(..., examples=["Butter Croissant"])
    quantity: int = Field(..., examples=[2])
    unit_price_at_order: float = Field(..., examples=[50.00])
    line_total: float = Field(..., examples=[100.00])


# =============================================================================
# Order models
# =============================================================================

class OrderResponse(BaseModel):
    """Full order record with embedded line items.

    Returned by:
        GET  /api/v1/orders/{order_id}

    Items are always included — a full order fetch is always needed to show
    the breakdown to a customer or administrator.
    """

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(..., description="Primary key", examples=[1])
    customer_id: int = Field(..., description="FK to customers", examples=[1])
    address_id: Optional[int] = Field(
        None,
        description=(
            "FK to addresses — may be NULL if the address was hard-deleted "
            "(the snapshot is still preserved in shipping_address_snapshot)"
        ),
        examples=[1],
    )
    shipping_address_snapshot: str = Field(
        ...,
        description="Immutable full address text captured at order creation",
        examples=["42 MG Road, Flat 3B, Bengaluru, Karnataka 560001, India"],
    )
    status: OrderStatus = Field(
        ...,
        description="Current lifecycle status of the order",
        examples=["pending"],
    )

    # --- Financial fields (DECIMAL(10,2) stored, float in JSON) ---------------
    subtotal: float = Field(
        ...,
        description="Sum of all line_totals before order-level discount",
        examples=[200.00],
    )
    discount_amount: float = Field(
        ...,
        description="Flat order-level discount applied",
        examples=[0.00],
    )
    discount_percent: float = Field(
        ...,
        description="Percentage order-level discount (0.00–100.00)",
        examples=[0.00],
    )
    taxable_amount: float = Field(
        ...,
        description="subtotal − discount; tax is calculated on this amount",
        examples=[200.00],
    )
    tax_percent: float = Field(
        ...,
        description="Tax rate applied (0.00–100.00)",
        examples=[18.00],
    )
    tax_amount: float = Field(
        ...,
        description="taxable_amount × tax_percent / 100",
        examples=[36.00],
    )
    total_amount: float = Field(
        ...,
        description="taxable_amount + tax_amount — final payable amount",
        examples=[236.00],
    )

    notes: Optional[str] = Field(
        None,
        description="Customer delivery instructions or special requests",
        examples=["Please leave at the door"],
    )
    ordered_at: datetime = Field(
        ..., description="UTC timestamp when the customer placed the order"
    )
    created_at: datetime = Field(..., description="UTC timestamp of row creation")
    updated_at: datetime = Field(..., description="UTC timestamp of last update")

    # Items are always populated for a full order response
    items: List[OrderItemResponse] = Field(
        ...,
        description="Line items belonging to this order",
    )


class OrderSummary(BaseModel):
    """Slim order row returned inside list responses.

    Does NOT include line items — use GET /orders/{id} for full detail.
    """

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(..., examples=[1])
    customer_id: int = Field(..., examples=[1])
    status: OrderStatus = Field(..., examples=["pending"])
    total_amount: float = Field(..., examples=[236.00])
    item_count: int = Field(
        ...,
        description="Number of distinct product lines in this order",
        examples=[2],
    )
    ordered_at: datetime = Field(..., examples=["2026-01-15T10:30:00"])


class OrderListResponse(BaseModel):
    """Paginated list of orders.

    Consistent with all other list responses in the project:
    total / page / page_size / items.
    """

    total: int = Field(..., description="Total number of matching orders")
    page: int = Field(..., description="Current page (1-based)")
    page_size: int = Field(..., description="Items per page")
    filters: dict = Field(
        default_factory=dict,
        description="Filters applied to this response (customer_id, status)",
    )
    items: List[OrderSummary] = Field(..., description="Order summary records")


# =============================================================================
# Request / write models (used by Phase 4 service and router)
# =============================================================================

class OrderItemCreate(BaseModel):
    """One line item in a create-order request body.

    The service layer reads products.unit_price at submission time and
    stores it as the immutable unit_price_at_order snapshot.
    Only one discount mechanism may be set per line (exclusive).
    """

    product_id: int = Field(..., ge=1, description="Product PK", examples=[3])
    quantity: int = Field(..., ge=1, description="Units to order", examples=[2])
    item_discount_amount: float = Field(
        default=0.0,
        ge=0.0,
        description="Flat item-level discount (0 = no discount)",
        examples=[0.0],
    )
    item_discount_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage item-level discount (0 = no discount)",
        examples=[0.0],
    )


class OrderCreate(BaseModel):
    """Request body for POST /api/v1/orders.

    The service layer will:
    1. Verify the customer and address exist.
    2. Read current unit_price for each product.
    3. Calculate line_totals, subtotal, taxable_amount, tax_amount, total_amount.
    4. Wrap the INSERT into orders + INSERT into order_items in a transaction.
    """

    customer_id: int = Field(..., ge=1, description="Customer PK", examples=[1])
    address_id: int = Field(
        ..., ge=1, description="Address PK (must belong to customer)", examples=[1]
    )
    items: List[OrderItemCreate] = Field(
        ...,
        min_length=1,
        description="At least one line item required",
    )
    discount_amount: float = Field(
        default=0.0,
        ge=0.0,
        description="Flat order-level discount (exclusive with discount_percent)",
        examples=[0.0],
    )
    discount_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage order-level discount (exclusive with discount_amount)",
        examples=[0.0],
    )
    tax_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Tax rate to apply (e.g. 18.0 for GST 18%)",
        examples=[18.0],
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional delivery instructions",
        examples=["Leave at the door"],
    )


class OrderStatusUpdate(BaseModel):
    """Request body for PATCH /api/v1/orders/{order_id}/status.

    Valid transitions are enforced by the service layer using
    utils.financial.validate_status_transition().
    """

    status: OrderStatus = Field(
        ...,
        description="The new status to transition the order to",
        examples=["confirmed"],
    )
