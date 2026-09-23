"""
services/report_service.py
============================
Business logic for the reporting endpoints.

Responsibilities
----------------
- Validate the date range for the revenue report.
- Delegate all DB access to report_repository.
- Assemble Pydantic response models from raw repository dicts.

The service never touches SQL directly.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from mysql.connector.pooling import PooledMySQLConnection

from models.report import (
    CategoryRevenueRow,
    DailyRevenueRow,
    LowStockItem,
    LowStockReport,
    RevenueReport,
    TopProductRow,
)
from repositories import report_repository
from utils.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

# Reports spanning more than this many days are rejected — a learning-project
# safeguard against accidentally scanning the entire orders table.
MAX_REPORT_RANGE_DAYS = 366


def get_low_stock_report(conn: PooledMySQLConnection) -> LowStockReport:
    """Return the full low-stock report, most urgent first."""
    rows = report_repository.get_low_stock(conn)
    items = [LowStockItem(**row) for row in rows]

    return LowStockReport(
        generated_at=datetime.now(timezone.utc),
        count=len(items),
        items=items,
    )


def get_revenue_report(
    conn: PooledMySQLConnection,
    date_from: date,
    date_to: date,
) -> RevenueReport:
    """Return the full revenue report (daily / by-category / top-5) for a range.

    Raises
    ------
    BusinessRuleError : date_from is after date_to, or the range exceeds
                         MAX_REPORT_RANGE_DAYS.
    DatabaseError       : Propagated from repository.
    """
    if date_from > date_to:
        raise BusinessRuleError(
            "INVALID_DATE_RANGE",
            f"date_from ({date_from}) must not be after date_to ({date_to}).",
            detail={"date_from": str(date_from), "date_to": str(date_to)},
        )

    span_days = (date_to - date_from).days
    if span_days > MAX_REPORT_RANGE_DAYS:
        raise BusinessRuleError(
            "DATE_RANGE_TOO_WIDE",
            f"Date range spans {span_days} days; maximum is "
            f"{MAX_REPORT_RANGE_DAYS}. Narrow the range and try again.",
            detail={"span_days": span_days, "max_days": MAX_REPORT_RANGE_DAYS},
        )

    logger.debug("get_revenue_report from=%s to=%s", date_from, date_to)

    daily_rows = report_repository.get_daily_revenue(conn, date_from, date_to)
    category_rows = report_repository.get_revenue_by_category(conn, date_from, date_to)
    top_rows = report_repository.get_top_products(conn, date_from, date_to)

    return RevenueReport(
        date_from=date_from,
        date_to=date_to,
        daily=[DailyRevenueRow(**row) for row in daily_rows],
        by_category=[CategoryRevenueRow(**row) for row in category_rows],
        top_products=[TopProductRow(**row) for row in top_rows],
    )
