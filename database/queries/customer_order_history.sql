-- =============================================================================
-- Meera Bakery Online
-- File   : customer_order_history.sql
-- Purpose: Full order history for a single customer, showing:
--            - Order header (id, date, status, financial totals)
--            - Every line item with price-at-time-of-order and line total
--
--          Replace the parameter placeholder (:customer_id) with a real
--          customer_id value, or bind it as a parameter in your application.
--
-- Usage example (MySQL CLI):
--   SET @customer_id = 1;
--   SOURCE customer_order_history.sql;
--
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

-- Set the customer to look up (change value as needed)
SET @customer_id = 1;

SELECT
    -- Order header
    o.order_id,
    o.ordered_at,
    o.status,
    o.shipping_address_snapshot,

    -- Financial summary
    o.subtotal,
    o.discount_amount,
    o.discount_percent,
    o.taxable_amount,
    o.tax_percent,
    o.tax_amount,
    o.total_amount,

    -- Line item detail
    oi.order_item_id,
    p.name                          AS product_name,
    c.name                          AS category,
    oi.quantity,
    oi.unit_price_at_order,         -- immutable price snapshot (SR-6)
    oi.item_discount_amount,
    oi.item_discount_percent,
    oi.line_total

FROM
    orders       o
    JOIN order_items  oi USING (order_id)
    JOIN products      p USING (product_id)
    JOIN categories    c ON c.category_id = p.category_id
WHERE
    o.customer_id = @customer_id
ORDER BY
    o.ordered_at  DESC,
    o.order_id    DESC,
    oi.order_item_id ASC;

-- =============================================================================
-- End of customer_order_history.sql
-- =============================================================================
