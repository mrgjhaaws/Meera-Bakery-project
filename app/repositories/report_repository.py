"""
repositories/report_repository.py
===================================
Direct SQL queries powering the reporting endpoints.

Source of truth: these queries are the parameterised, application-callable
equivalents of the standalone scripts in database/queries/:
    - low_stock_report.sql
    - daily_revenue.sql   (three queries: daily / by-category / top-5)

Rules (consistent with Phases 2-4 repositories)
--------------------------------------------------
- All SQL is parameterised.
- Cursors always use dictionary=True.
- DECIMAL columns are converted to float before returning.
- Raw MySQLError is caught and re-raised as DatabaseError.
- These are read-only — no commit needed.

Index-friendly date ranges
---------------------------
All date-range filters use `ordered_at >= %s AND ordered_at < DATE_ADD(%s,
INTERVAL 1 DAY)` rather than wrapping the column in DATE(...), so
idx_ord_ordered_at stays usable (matches the audit correction applied to
the standalone daily_revenue.sql script).

Public interface
----------------
    get_low_stock(conn) -> list[dict]
    get_daily_revenue(conn, date_from, date_to) -> list[dict]
    get_revenue_by_category(conn, date_from, date_to) -> list[dict]
    get_top_products(conn, date_from, date_to, limit=5) -> list[dict]
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

# Monetary columns per report row — converted DECIMAL -> float.
_DAILY_DECIMAL_COLS = ("total_subtotal", "total_discounts", "total_tax", "total_revenue")
_CATEGORY_DECIMAL_COLS = ("category_revenue",)
_PRODUCT_DECIMAL_COLS = ("product_revenue",)


def _to_float(row: dict, cols: tuple[str, ...]) -> dict:
    for col in cols:
        if row.get(col) is not None:
            row[col] = float(row[col])
    return row


def get_low_stock(conn: PooledMySQLConnection) -> List[dict]:
    """Return all active products at or below their reorder threshold.

    Ordered by stock deficit descending (most urgent restock first), then
    by product name.
    """
    sql = """
        SELECT
            p.product_id,
            c.name AS category,
            p.name AS product,
            i.quantity_on_hand,
            i.reorder_level,
            i.reorder_quantity,
            (CAST(i.reorder_level AS SIGNED) - CAST(i.quantity_on_hand AS SIGNED))
                                                    AS units_below_threshold,
            i.last_restocked_at
        FROM inventory i
        JOIN products p USING (product_id)
        JOIN categories c USING (category_id)
        WHERE i.quantity_on_hand <= i.reorder_level
          AND p.is_active = 1
        ORDER BY
            (CAST(i.reorder_level AS SIGNED) - CAST(i.quantity_on_hand AS SIGNED)) DESC,
            p.name ASC
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql)
        rows: List[dict] = cursor.fetchall()
        cursor.close()
        return rows
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=f"report_repository.get_low_stock: {exc}"
        ) from exc


def get_daily_revenue(
    conn: PooledMySQLConnection,
    date_from: date,
    date_to: date,
) -> List[dict]:
    """Return daily revenue totals for delivered orders in [date_from, date_to]."""
    sql = """
        SELECT
            DATE(o.ordered_at)          AS order_date,
            COUNT(DISTINCT o.order_id)  AS orders_delivered,
            SUM(o.subtotal)             AS total_subtotal,
            SUM(o.discount_amount)      AS total_discounts,
            SUM(o.tax_amount)           AS total_tax,
            SUM(o.total_amount)         AS total_revenue
        FROM orders o
        WHERE o.status = 'delivered'
          AND o.ordered_at >= %s
          AND o.ordered_at <  DATE_ADD(%s, INTERVAL 1 DAY)
        GROUP BY DATE(o.ordered_at)
        ORDER BY order_date ASC
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (date_from, date_to))
        rows: List[dict] = cursor.fetchall()
        cursor.close()
        for row in rows:
            _to_float(row, _DAILY_DECIMAL_COLS)
        return rows
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"report_repository.get_daily_revenue "
                f"from={date_from} to={date_to}: {exc}"
            )
        ) from exc


def get_revenue_by_category(
    conn: PooledMySQLConnection,
    date_from: date,
    date_to: date,
) -> List[dict]:
    """Return revenue by product category for delivered orders in the range."""
    sql = """
        SELECT
            c.name                      AS category,
            COUNT(DISTINCT o.order_id)  AS orders_count,
            SUM(oi.quantity)            AS units_sold,
            SUM(oi.line_total)          AS category_revenue
        FROM orders       o
        JOIN order_items  oi USING (order_id)
        JOIN products     p  USING (product_id)
        JOIN categories   c  ON c.category_id = p.category_id
        WHERE o.status = 'delivered'
          AND o.ordered_at >= %s
          AND o.ordered_at <  DATE_ADD(%s, INTERVAL 1 DAY)
        GROUP BY c.category_id, c.name
        ORDER BY category_revenue DESC
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (date_from, date_to))
        rows: List[dict] = cursor.fetchall()
        cursor.close()
        for row in rows:
            _to_float(row, _CATEGORY_DECIMAL_COLS)
        return rows
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"report_repository.get_revenue_by_category "
                f"from={date_from} to={date_to}: {exc}"
            )
        ) from exc


def get_top_products(
    conn: PooledMySQLConnection,
    date_from: date,
    date_to: date,
    limit: int = 5,
) -> List[dict]:
    """Return the top-selling products (by quantity) for the date range."""
    sql = """
        SELECT
            p.name                      AS product,
            c.name                      AS category,
            SUM(oi.quantity)            AS units_sold,
            SUM(oi.line_total)          AS product_revenue
        FROM orders       o
        JOIN order_items  oi USING (order_id)
        JOIN products     p  USING (product_id)
        JOIN categories   c  ON c.category_id = p.category_id
        WHERE o.status = 'delivered'
          AND o.ordered_at >= %s
          AND o.ordered_at <  DATE_ADD(%s, INTERVAL 1 DAY)
        GROUP BY p.product_id, p.name, c.name
        ORDER BY units_sold DESC
        LIMIT %s
    """
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (date_from, date_to, limit))
        rows: List[dict] = cursor.fetchall()
        cursor.close()
        for row in rows:
            _to_float(row, _PRODUCT_DECIMAL_COLS)
        return rows
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"report_repository.get_top_products "
                f"from={date_from} to={date_to}: {exc}"
            )
        ) from exc
