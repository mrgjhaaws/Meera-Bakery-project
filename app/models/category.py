"""
models/category.py
==================
Pydantic models for the categories resource.

Schema source of truth  : database/schema/01_create_categories.sql
Table columns used here :
    category_id   TINYINT UNSIGNED  PK
    name          VARCHAR(80)       NOT NULL  UNIQUE
    description   VARCHAR(255)      NULL
    is_active     TINYINT(1)        NOT NULL  DEFAULT 1
    created_at    DATETIME          NOT NULL
    updated_at    DATETIME          NOT NULL

Response models
---------------
CategoryResponse      — single category (used by GET /categories/{id})
CategorySummary       — slim row used inside list responses
CategoryListResponse  — paginated list wrapper

All models are read-only in Phase 2.  No write/create models yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoryResponse(BaseModel):
    """Full category record returned by GET /categories/{category_id}."""

    model_config = ConfigDict(from_attributes=True)

    category_id: int = Field(..., description="Primary key", examples=[1])
    name: str = Field(..., description="Category name", examples=["Bread"])
    description: Optional[str] = Field(
        None,
        description="Optional category description",
        examples=["Loaves, rolls, buns, and flatbreads baked fresh daily"],
    )
    is_active: bool = Field(..., description="False means the category is soft-deleted")
    created_at: datetime = Field(..., description="UTC timestamp of creation")
    updated_at: datetime = Field(..., description="UTC timestamp of last update")


class CategorySummary(BaseModel):
    """Slim category row returned inside list responses and embedded in products."""

    model_config = ConfigDict(from_attributes=True)

    category_id: int = Field(..., examples=[1])
    name: str = Field(..., examples=["Bread"])
    is_active: bool = Field(..., examples=[True])


class CategoryListResponse(BaseModel):
    """Paginated list of categories."""

    total: int = Field(..., description="Total number of matching categories")
    page: int = Field(..., description="Current page (1-based)")
    page_size: int = Field(..., description="Items per page")
    items: List[CategoryResponse] = Field(..., description="Category records")
