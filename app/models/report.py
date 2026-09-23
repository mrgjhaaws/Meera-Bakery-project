"""
models/report.py
=================
Pydantic models for the reporting endpoints.

Source of truth: database/queries/low_stock_report.sql and
database/queries/daily_revenue.sql — these models mirror the exact columns
those queries return so report_repository stays a thin pass-through.

Model hierarchy
---------------
    LowStockItem     — one row of the low-stock report
    LowStockReport    — wrapper with generated_at + count + items

    DailyRevenueRow   — one day's revenue totals (delivered orders only)
    CategoryRevenueRow— revenue broken down by product category
    TopProductRow     — best-selling products by quantity
    RevenueReport     — wrapper bundling all three for one date range
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Low-stock report
# =============================================================================

class LowStockItem(BaseModel):
    """One product currently at or below its reorder threshold."""

    product_id: int = Field(..., examples=[3])
    category: str = Field(..., examples=["Pastry"])
    product: str = Field(..., examples=["Butter Croissant"])
    quantity_on_hand: int = Field(..., examples=[4])
    reorder_level: int = Field(..., examples=[10])
    reorder_quantity: int = Field(..., examples=[50])
    units_below_threshold: int = Field(
        ...,
        description="reorder_level - quantity_on_hand (0 = exactly at threshold)",
        examples=[6],
    )
    last_restocked_at: Optional[datetime] = Field(None, examples=[None])


class LowStockReport(BaseModel):
    """Full low-stock report, ordered most-urgent first."""

    generated_at: datetime = Field(..., description="UTC timestamp the report was run")
    count: int = Field(..., description="Number of products at or below reorder level")
    items: List[LowStockItem] = Field(...)


# =============================================================================
# Revenue report
# =============================================================================

class DailyRevenueRow(BaseModel):
    """Revenue totals for a single calendar day (delivered orders only)."""

    order_date: date = Field(..., examples=["2026-01-15"])
    orders_delivered: int = Field(..., examples=[7])
    total_subtotal: float = Field(..., examples=[3150.00])
    total_discounts: float = Field(..., examples=[120.00])
    total_tax: float = Field(..., examples=[544.00])
    total_revenue: float = Field(..., examples=[3574.00])


class CategoryRevenueRow(BaseModel):
    """Revenue broken down by product category for the report period."""

    category: str = Field(..., examples=["Cake"])
    orders_count: int = Field(..., examples=[12])
    units_sold: int = Field(..., examples=[18])
    category_revenue: float = Field(..., examples=[5400.00])


class TopProductRow(BaseModel):
    """One row of the top-5 best-selling products (by quantity)."""

    product: str = Field(..., examples=["Butter Croissant"])
    category: str = Field(..., examples=["Pastry"])
    units_sold: int = Field(..., examples=[42])
    product_revenue: float = Field(..., examples=[2100.00])


class RevenueReport(BaseModel):
    """Full revenue report for a date range — daily totals, category
    breakdown, and top-5 products, all restricted to delivered orders."""

    date_from: date = Field(..., examples=["2026-01-01"])
    date_to: date = Field(..., examples=["2026-01-31"])
    daily: List[DailyRevenueRow] = Field(...)
    by_category: List[CategoryRevenueRow] = Field(...)
    top_products: List[TopProductRow] = Field(...)
