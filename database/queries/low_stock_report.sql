-- =============================================================================
-- Meera Bakery Online
-- File   : low_stock_report.sql
-- Purpose: Report all active products whose current stock is at or below
--          their reorder threshold.
--          Use this query to trigger restocking alerts (IR-6, IR-7).
--
-- Returns: product name, category, current stock, reorder level, and the
--          recommended reorder quantity.
--          Results are ordered by stock deficit (most urgent first).
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

SELECT
    p.product_id,
    c.name                                          AS category,
    p.name                                          AS product,
    i.quantity_on_hand,
    i.reorder_level,
    i.reorder_quantity,
    -- How many units below the reorder threshold (0 means exactly at threshold).
    -- Cast both UNSIGNED operands to SIGNED before subtracting to avoid
    -- modular wraparound in non-strict sql_mode (audit correction C-1).
    (CAST(i.reorder_level AS SIGNED) - CAST(i.quantity_on_hand AS SIGNED))
                                                    AS units_below_threshold,
    i.last_restocked_at
FROM
    inventory   i
    JOIN products   p USING (product_id)
    JOIN categories c USING (category_id)
WHERE
    -- Only products currently at or below their reorder level
    i.quantity_on_hand <= i.reorder_level
    -- Exclude soft-deleted products
    AND p.is_active = 1
ORDER BY
    -- Most urgent (largest deficit) first.
    -- CAST to SIGNED prevents unsigned-subtraction wraparound (audit C-1).
    (CAST(i.reorder_level AS SIGNED) - CAST(i.quantity_on_hand AS SIGNED)) DESC,
    p.name ASC;

-- =============================================================================
-- End of low_stock_report.sql
-- =============================================================================
