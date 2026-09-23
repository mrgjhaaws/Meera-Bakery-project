-- =============================================================================
-- Meera Bakery Online
-- File   : seed_categories.sql
-- Purpose: Insert the initial set of product categories.
--          Run ONCE after 01_create_categories.sql has been executed.
--          Uses INSERT IGNORE so re-running is safe (no duplicates).
-- Depends: categories table must exist
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

INSERT IGNORE INTO categories (name, description, is_active)
VALUES
    ('Bread',     'Loaves, rolls, buns, and flatbreads baked fresh daily',       1),
    ('Cake',      'Layer cakes, celebration cakes, and cupcakes',                1),
    ('Pastry',    'Croissants, danishes, puffs, and flaky baked goods',          1),
    ('Cookie',    'Biscuits, cookies, and bite-sized baked treats',              1),
    ('Beverage',  'Hot and cold drinks served at the bakery counter',            1),
    ('Other',     'Seasonal specials and items that do not fit other categories',1);

-- Verify
SELECT category_id, name, is_active, created_at
FROM   categories
ORDER  BY category_id;

-- =============================================================================
-- End of seed_categories.sql
-- =============================================================================
