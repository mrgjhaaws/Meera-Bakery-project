-- =============================================================================
-- Meera Bakery Online
-- File   : seed_products.sql
-- Purpose: Insert a representative set of bakery products and create their
--          corresponding inventory rows.
--
--          Each INSERT into products is immediately followed by an INSERT
--          into inventory (quantity_on_hand starts at 0 per IR-2).
--
--          Uses INSERT IGNORE on products so re-running is safe.
--          Inventory rows are inserted via INSERT IGNORE as well.
--
--          IMPORTANT: Run seed_categories.sql first so category_id values exist.
--
-- Depends: categories, products, inventory tables must exist
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

-- -----------------------------------------------------------------------------
-- Helper: resolve category IDs by name so this seed is not brittle
-- against auto-increment gaps.
-- -----------------------------------------------------------------------------
-- We use a single transaction so products and their inventory rows are
-- inserted atomically.
-- -----------------------------------------------------------------------------

START TRANSACTION;

-- -----------------------------------------------------------------------------
-- Guard: verify all 6 required categories exist before inserting products.
-- If any category is missing, this SELECT returns a non-empty result set.
-- The application / DBA should treat non-empty output as a hard stop.
-- (audit correction C-2)
-- -----------------------------------------------------------------------------
SELECT
    required.name AS missing_category,
    'ERROR: Category missing — run seed_categories.sql first, then retry.' AS action_required
FROM (
    SELECT 'Bread'    AS name UNION ALL
    SELECT 'Cake'            UNION ALL
    SELECT 'Pastry'          UNION ALL
    SELECT 'Cookie'          UNION ALL
    SELECT 'Beverage'        UNION ALL
    SELECT 'Other'
) AS required
LEFT JOIN categories c ON c.name = required.name
WHERE c.category_id IS NULL;

-- If the query above returned any rows, ROLLBACK and stop.
-- If it returned zero rows, all categories are present — proceed.

-- ---- BREAD (category_id resolved by subquery) --------------------------------

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Sourdough Loaf',
       'Classic long-fermented sourdough with a crisp crust and tangy crumb',
       120.00, 1
FROM   categories WHERE name = 'Bread';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Whole Wheat Bread',
       'Nutritious whole wheat loaf, soft and lightly sweetened',
       80.00, 1
FROM   categories WHERE name = 'Bread';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Dinner Rolls (6 pcs)',
       'Soft, pillowy dinner rolls perfect for meals',
       60.00, 1
FROM   categories WHERE name = 'Bread';

-- ---- CAKE -------------------------------------------------------------------

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Chocolate Truffle Cake',
       'Rich dark chocolate cake layered with truffle ganache',
       450.00, 1
FROM   categories WHERE name = 'Cake';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Vanilla Sponge Cake',
       'Light and airy vanilla sponge with fresh cream frosting',
       350.00, 1
FROM   categories WHERE name = 'Cake';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Red Velvet Cupcake',
       'Moist red velvet cupcake topped with cream cheese frosting',
       65.00, 1
FROM   categories WHERE name = 'Cake';

-- ---- PASTRY -----------------------------------------------------------------

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Butter Croissant',
       'Classic French-style croissant, flaky and buttery',
       50.00, 1
FROM   categories WHERE name = 'Pastry';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Almond Danish',
       'Flaky danish pastry filled with almond cream and topped with flaked almonds',
       70.00, 1
FROM   categories WHERE name = 'Pastry';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Cheese Puff',
       'Light choux puff filled with savoury cream cheese',
       40.00, 1
FROM   categories WHERE name = 'Pastry';

-- ---- COOKIE -----------------------------------------------------------------

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Chocolate Chip Cookie',
       'Chewy cookie loaded with dark chocolate chips',
       30.00, 1
FROM   categories WHERE name = 'Cookie';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Oatmeal Raisin Cookie',
       'Hearty oatmeal cookie with plump raisins and a hint of cinnamon',
       30.00, 1
FROM   categories WHERE name = 'Cookie';

-- ---- BEVERAGE ---------------------------------------------------------------

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Filter Coffee',
       'South Indian filter coffee served hot in a traditional tumbler',
       40.00, 1
FROM   categories WHERE name = 'Beverage';

INSERT IGNORE INTO products (category_id, name, description, unit_price, is_active)
SELECT category_id, 'Masala Chai',
       'Spiced milk tea brewed with ginger, cardamom, and cinnamon',
       35.00, 1
FROM   categories WHERE name = 'Beverage';

-- -----------------------------------------------------------------------------
-- Create inventory rows for every product that does not yet have one.
-- quantity_on_hand starts at 0 (IR-2).
-- reorder_level = 10, reorder_quantity = 50 (defaults).
-- -----------------------------------------------------------------------------
INSERT IGNORE INTO inventory (product_id, quantity_on_hand, reorder_level, reorder_quantity)
SELECT product_id, 0, 10, 50
FROM   products
WHERE  product_id NOT IN (SELECT product_id FROM inventory);

COMMIT;

-- Verify products
SELECT  p.product_id,
        c.name          AS category,
        p.name          AS product,
        p.unit_price,
        i.quantity_on_hand
FROM    products  p
JOIN    categories c USING (category_id)
JOIN    inventory  i USING (product_id)
ORDER   BY c.name, p.name;

-- =============================================================================
-- End of seed_products.sql
-- =============================================================================
