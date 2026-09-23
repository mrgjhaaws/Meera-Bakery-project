"""
models/customer.py
==================
Pydantic models for the customers resource.

Schema source of truth  : database/schema/02_create_customers.sql
Table columns used here :
    customer_id   INT UNSIGNED   PK AUTO_INCREMENT
    first_name    VARCHAR(80)    NOT NULL
    last_name     VARCHAR(80)    NOT NULL
    email         VARCHAR(254)   NOT NULL  UNIQUE
    phone         VARCHAR(20)    NULL
    is_active     TINYINT(1)     NOT NULL  DEFAULT 1
    created_at    DATETIME       NOT NULL
    updated_at    DATETIME       NOT NULL

Security notes
--------------
- No password or password_hash field — authentication is external (AWS Cognito).
- email is included in responses; the application layer must ensure that
  only authorised callers can list or look up customer records.

Response models
---------------
CustomerResponse      — full customer record (GET /customers/{id})
CustomerSummary       — slim row for list responses
CustomerListResponse  — paginated list wrapper, consistent with
                        CategoryListResponse and ProductListResponse
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CustomerResponse(BaseModel):
    """Full customer record returned by GET /customers/{customer_id}."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: int = Field(..., description="Primary key", examples=[1])
    first_name: str = Field(..., description="Customer first name", examples=["Meera"])
    last_name: str = Field(..., description="Customer last name", examples=["Sharma"])
    email: str = Field(
        ...,
        description="Unique email address (business identifier)",
        examples=["meera@example.com"],
    )
    phone: Optional[str] = Field(
        None,
        description="Phone number in E.164 format (optional)",
        examples=["+919876543210"],
    )
    is_active: bool = Field(
        ...,
        description="False means the customer account has been soft-deleted",
    )
    created_at: datetime = Field(..., description="UTC timestamp of account creation")
    updated_at: datetime = Field(..., description="UTC timestamp of last update")


class CustomerSummary(BaseModel):
    """Slim customer row returned inside list responses."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: int = Field(..., examples=[1])
    first_name: str = Field(..., examples=["Meera"])
    last_name: str = Field(..., examples=["Sharma"])
    email: str = Field(..., examples=["meera@example.com"])
    is_active: bool = Field(..., examples=[True])


class CustomerListResponse(BaseModel):
    """Paginated list of customers.

    Consistent with CategoryListResponse and ProductListResponse:
    total / page / page_size / items.
    """

    total: int = Field(..., description="Total number of matching customers")
    page: int = Field(..., description="Current page (1-based)")
    page_size: int = Field(..., description="Items per page")
    items: List[CustomerSummary] = Field(..., description="Customer records")
