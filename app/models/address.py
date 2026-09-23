"""
models/address.py
=================
Pydantic models for the addresses resource.

Schema source of truth  : database/schema/05_create_addresses.sql
Table columns used here :
    address_id    INT UNSIGNED   PK AUTO_INCREMENT
    customer_id   INT UNSIGNED   NOT NULL  FK → customers
    label         VARCHAR(50)    NOT NULL  DEFAULT 'Home'
    address_line1 VARCHAR(255)   NOT NULL
    address_line2 VARCHAR(255)   NULL
    city          VARCHAR(100)   NOT NULL
    state         VARCHAR(100)   NOT NULL
    postal_code   VARCHAR(20)    NOT NULL
    country       VARCHAR(60)    NOT NULL  DEFAULT 'India'
    is_default    TINYINT(1)     NOT NULL  DEFAULT 0
    is_active     TINYINT(1)     NOT NULL  DEFAULT 1
    created_at    DATETIME       NOT NULL
    updated_at    DATETIME       NOT NULL

Design notes
------------
- is_default is enforced by the application layer — the DB has no UNIQUE
  constraint on (customer_id, is_default=1).
- At order creation, the chosen address is denormalised into
  orders.shipping_address_snapshot (TEXT, immutable).  Modifying or
  soft-deleting an address never corrupts historical orders.
- address_line2 is optional (NULL in the DB).

Response models
---------------
AddressResponse      — full address record (GET /addresses/{id})
AddressSummary       — slim row for list responses
AddressListResponse  — paginated list wrapper, consistent with other list responses
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AddressResponse(BaseModel):
    """Full address record returned by GET /addresses/{address_id}."""

    model_config = ConfigDict(from_attributes=True)

    address_id: int = Field(..., description="Primary key", examples=[1])
    customer_id: int = Field(..., description="FK to customers", examples=[1])
    label: str = Field(
        ...,
        description="User-defined address label",
        examples=["Home"],
    )
    address_line1: str = Field(
        ...,
        description="Street number, flat, building name",
        examples=["42 MG Road, Flat 3B"],
    )
    address_line2: Optional[str] = Field(
        None,
        description="Landmark, area, floor — optional",
        examples=["Near Central Mall"],
    )
    city: str = Field(..., description="City", examples=["Bengaluru"])
    state: str = Field(..., description="State or union territory", examples=["Karnataka"])
    postal_code: str = Field(..., description="PIN / postal code", examples=["560001"])
    country: str = Field(..., description="Country (default India)", examples=["India"])
    is_default: bool = Field(
        ...,
        description="True means this is the customer's default delivery address",
    )
    is_active: bool = Field(
        ...,
        description="False means the address has been soft-deleted",
    )
    created_at: datetime = Field(..., description="UTC timestamp of creation")
    updated_at: datetime = Field(..., description="UTC timestamp of last update")


class AddressSummary(BaseModel):
    """Slim address row returned inside list responses."""

    model_config = ConfigDict(from_attributes=True)

    address_id: int = Field(..., examples=[1])
    customer_id: int = Field(..., examples=[1])
    label: str = Field(..., examples=["Home"])
    address_line1: str = Field(..., examples=["42 MG Road, Flat 3B"])
    city: str = Field(..., examples=["Bengaluru"])
    state: str = Field(..., examples=["Karnataka"])
    postal_code: str = Field(..., examples=["560001"])
    country: str = Field(..., examples=["India"])
    is_default: bool = Field(..., examples=[True])
    is_active: bool = Field(..., examples=[True])


class AddressListResponse(BaseModel):
    """Paginated list of addresses for a customer.

    Consistent with CategoryListResponse, ProductListResponse,
    and CustomerListResponse: total / page / page_size / items.
    """

    total: int = Field(..., description="Total number of matching addresses")
    page: int = Field(..., description="Current page (1-based)")
    page_size: int = Field(..., description="Items per page")
    items: List[AddressSummary] = Field(..., description="Address records")
