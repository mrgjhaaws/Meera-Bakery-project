-- =============================================================================
-- Meera Bakery Online
-- File   : daily_revenue.sql
-- Purpose: Daily revenue summary for a given date range.
--          Shows per-day order counts and financial totals.
--          Only delivered orders are included in the revenue figure
--          (cancelled orders are excluded).
--          A second query below breaks revenue down by product category
--          for the same period.
--
-- Usage example (MySQL CLI):
--   SET @date_from = '2026-01-01';
--   SET @date_to   = '2026-01-31';
--   SOURCE daily_revenue.sql;
--
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

-- Set the reporting window (change values as needed)
SET @date_from = '2026-01-01';
SET @date_to   = '2026-12-31';

-- NOTE: Range predicates are used directly on orders.ordered_at (a DATETIME
-- column) instead of wrapping it in DATE(). Wrapping a column in a function
-- prevents MySQL from using the idx_ord_ordered_at index, causing a full table
-- scan on large datasets. The range below is index-friendly and equivalent.
-- (audit correction C-4)
--
-- Pattern:  ordered_at >= @date_from
--           AND ordered_at <  DATE_ADD(@date_to, INTERVAL 1 DAY)
-- This captures all timestamps on @date_to right up to 23:59:59.999999.

-- -----------------------------------------------------------------------------
-- Query 1: Daily revenue — delivered orders only
-- -----------------------------------------------------------------------------
SELECT
    DATE(o.ordered_at)              AS order_date,
    COUNT(DISTINCT o.order_id)      AS orders_delivered,
    SUM(o.subtotal)                 AS total_subtotal,
    SUM(o.discount_amount)          AS total_discounts,
    SUM(o.tax_amount)               AS total_tax,
    SUM(o.total_amount)             AS total_revenue
FROM
    orders o
WHERE
    o.status    = 'delivered'
    AND o.ordered_at >= @date_from
    AND o.ordered_at <  DATE_ADD(@date_to, INTERVAL 1 DAY)
GROUP BY
    DATE(o.ordered_at)
ORDER BY
    order_date ASC;

-- -----------------------------------------------------------------------------
-- Query 2: Revenue by product category for the same period
-- -----------------------------------------------------------------------------
SELECT
    c.name                          AS category,
    COUNT(DISTINCT o.order_id)      AS orders_count,
    SUM(oi.quantity)                AS units_sold,
    SUM(oi.line_total)              AS category_revenue
FROM
    orders       o
    JOIN order_items  oi USING (order_id)
    JOIN products      p USING (product_id)
    JOIN categories    c ON c.category_id = p.category_id
WHERE
    o.status = 'delivered'
    AND o.ordered_at >= @date_from
    AND o.ordered_at <  DATE_ADD(@date_to, INTERVAL 1 DAY)
GROUP BY
    c.category_id,
    c.name
ORDER BY
    category_revenue DESC;

-- -----------------------------------------------------------------------------
-- Query 3: Top 5 best-selling products by quantity in the period
-- -----------------------------------------------------------------------------
SELECT
    p.name                          AS product,
    c.name                          AS category,
    SUM(oi.quantity)                AS units_sold,
    SUM(oi.line_total)              AS product_revenue
FROM
    orders       o
    JOIN order_items  oi USING (order_id)
    JOIN products      p USING (product_id)
    JOIN categories    c ON c.category_id = p.category_id
WHERE
    o.status = 'delivered'
    AND o.ordered_at >= @date_from
    AND o.ordered_at <  DATE_ADD(@date_to, INTERVAL 1 DAY)
GROUP BY
    p.product_id,
    p.name,
    c.name
ORDER BY
    units_sold DESC
LIMIT 5;

-- =============================================================================
-- End of daily_revenue.sql
-- =============================================================================
