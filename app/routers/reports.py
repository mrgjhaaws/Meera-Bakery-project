"""
routers/reports.py
===================
FastAPI router for reporting endpoints.

Endpoints (Phase 4)
--------------------
GET /api/v1/reports/low-stock
    All active products currently at or below their reorder level.

GET /api/v1/reports/revenue?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
    Daily revenue, revenue-by-category, and top-5 products for a date
    range, restricted to delivered orders.

Router rules (consistent with Phases 2-4)
--------------------------------------------
- Handlers are thin: validate query params, call the service, return.
- No SQL or business logic lives here.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from mysql.connector.pooling import PooledMySQLConnection

from dependencies import get_db
from models.report import LowStockReport, RevenueReport
from services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "/low-stock",
    response_model=LowStockReport,
    summary="Low-stock report",
    description=(
        "Returns every active product currently at or below its reorder "
        "level, ordered by urgency (largest deficit first)."
    ),
)
def low_stock_report(
    conn: PooledMySQLConnection = Depends(get_db),
) -> LowStockReport:
    return report_service.get_low_stock_report(conn)


@router.get(
    "/revenue",
    response_model=RevenueReport,
    summary="Revenue report",
    description=(
        "Returns daily revenue totals, revenue by category, and the top-5 "
        "best-selling products for the given date range. Only delivered "
        "orders are counted."
    ),
)
def revenue_report(
    date_from: date = Query(..., description="Start of the report range (inclusive)"),
    date_to: date = Query(..., description="End of the report range (inclusive)"),
    conn: PooledMySQLConnection = Depends(get_db),
) -> RevenueReport:
    return report_service.get_revenue_report(conn, date_from, date_to)
