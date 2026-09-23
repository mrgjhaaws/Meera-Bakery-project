"""
models/product.py
=================
Pydantic models for the products resource.

Schema source of truth  : database/schema/03_create_products.sql
                          database/schema/04_create_inventory.sql
Table columns used here :
    products:
        product_id    INT UNSIGNED      PK
        category_id   TINYINT UNSIGNED  FK → categories
        name          VARCHAR(150)      NOT NULL  UNIQUE
        description   TEXT              NULL
        unit_price    DECIMAL(10,2)     NOT NULL  CHECK >= 0
        is_active     TINYINT(1)        NOT NULL  DEFAULT 1
        created_at    DATETIME          NOT NULL
        updated_at    DATETIME          NOT NULL
    inventory (joined read-only):
        quantity_on_hand  INT UNSIGNED
        reorder_level     INT UNSIGNED
        last_restocked_at DATETIME NULL

Response models
---------------
ProductInventoryInfo  — inventory sub-object embedded in full product response
ProductResponse       — full product (used by GET /products/{id})
ProductSummary        — slim row used inside list responses
ProductListResponse   — paginated list wrapper

All DECIMAL(10,2) prices are exposed as float in JSON (standard practice).
The Decimal→float conversion happens in the repository layer so Pydantic
receives a plain float and serialises it cleanly.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProductInventoryInfo(BaseModel):
    """Inventory stock details embedded inside a ProductResponse.

    Returned when include_inventory=true is passed to GET /products/{id}.
    Also used in the low-stock report (Phase 6).
    """

    model_config = ConfigDict(from_attributes=True)

    quantity_on_hand: int = Field(
        ..., description="Current units in stock", examples=[25]
    )
    reorder_level: int = Field(
        ..., description="Alert threshold — restock when stock reaches this level",
        examples=[10],
    )
    reorder_quantity: int = Field(
        ..., description="Suggested units to order when restocking", examples=[50]
    )
    last_restocked_at: Optional[datetime] = Field(
        None, description="UTC timestamp of most recent restock"
    )


class ProductResponse(BaseModel):
    """Full product record returned by GET /products/{product_id}."""

    model_config = ConfigDict(from_attributes=True)

    product_id: int = Field(..., description="Primary key", examples=[1])
    category_id: int = Field(..., description="FK to categories", examples=[1])
    category_name: str = Field(
        ..., description="Denormalised category name for convenience",
        examples=["Bread"],
    )
    name: str = Field(
        ..., description="Product name", examples=["Sourdough Loaf"]
    )
    description: Optional[str] = Field(
        None,
        description="Product description",
        examples=["Classic long-fermented sourdough with a crisp crust"],
    )
    unit_price: float = Field(
        ..., description="Price per unit in INR (DECIMAL(10,2) in DB)",
        examples=[120.00],
    )
    is_active: bool = Field(
        ..., description="False means the product is soft-deleted / hidden"
    )
    inventory: Optional[ProductInventoryInfo] = Field(
        None,
        description="Stock info — present only when include_inventory=true",
    )
    created_at: datetime = Field(..., description="UTC timestamp of creation")
    updated_at: datetime = Field(..., description="UTC timestamp of last update")


class ProductSummary(BaseModel):
    """Slim product row returned inside list responses."""

    model_config = ConfigDict(from_attributes=True)

    product_id: int = Field(..., examples=[1])
    category_id: int = Field(..., examples=[1])
    category_name: str = Field(..., examples=["Bread"])
    name: str = Field(..., examples=["Sourdough Loaf"])
    unit_price: float = Field(..., examples=[120.00])
    is_active: bool = Field(..., examples=[True])


class ProductListResponse(BaseModel):
    """Paginated list of products with optional filters applied."""

    total: int = Field(..., description="Total number of matching products")
    page: int = Field(..., description="Current page (1-based)")
    page_size: int = Field(..., description="Items per page")
    filters: dict = Field(
        default_factory=dict,
        description="Filters that were applied (category_id, active_only)",
    )
    items: List[ProductSummary] = Field(..., description="Product records")
