-- =============================================================================
-- Meera Bakery Online
-- File   : 04_create_inventory.sql
-- Table  : inventory
-- Purpose: Stock levels and reorder thresholds — one row per product (1-to-1).
--          quantity_on_hand is INT UNSIGNED: the UNSIGNED type prevents negative
--          values at the engine level (SR-5). No additional CHECK needed.
--          Inventory is decremented when an order is CONFIRMED and
--          incremented back when an order is CANCELLED (IR-4, IR-5).
--          All decrement/increment operations must run inside a transaction.
-- Depends: products
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

CREATE TABLE IF NOT EXISTS inventory (
    -- -------------------------------------------------------------------------
    -- Primary key
    -- -------------------------------------------------------------------------
    inventory_id      INT UNSIGNED    NOT NULL AUTO_INCREMENT,

    -- -------------------------------------------------------------------------
    -- Foreign key to products (1-to-1 enforced by UNIQUE)
    -- ON DELETE CASCADE : deleting a product removes its inventory row.
    -- ON UPDATE CASCADE : propagate product_id changes automatically.
    -- -------------------------------------------------------------------------
    product_id        INT UNSIGNED    NOT NULL,

    -- -------------------------------------------------------------------------
    -- Stock columns
    -- All are INT UNSIGNED — cannot be negative (SR-5, SR-3).
    -- -------------------------------------------------------------------------
    quantity_on_hand  INT UNSIGNED    NOT NULL DEFAULT 0
                      COMMENT 'Current stock. UNSIGNED prevents negative values.',

    reorder_level     INT UNSIGNED    NOT NULL DEFAULT 10
                      COMMENT 'Alert threshold: raise low-stock alert when quantity_on_hand <= reorder_level',

    reorder_quantity  INT UNSIGNED    NOT NULL DEFAULT 50
                      COMMENT 'Suggested quantity to restock when reorder_level is reached',

    last_restocked_at DATETIME            NULL
                      COMMENT 'Timestamp of the most recent stock replenishment',

    -- -------------------------------------------------------------------------
    -- Audit timestamps  (DATETIME, UTC convention)
    -- -------------------------------------------------------------------------
    created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                               ON UPDATE CURRENT_TIMESTAMP,

    -- -------------------------------------------------------------------------
    -- Constraints
    -- -------------------------------------------------------------------------
    CONSTRAINT pk_inventory           PRIMARY KEY (inventory_id),

    -- UNIQUE enforces the 1-to-1 relationship with products
    CONSTRAINT uq_inventory_product   UNIQUE      (product_id),

    CONSTRAINT fk_inventory_product
        FOREIGN KEY (product_id)
        REFERENCES  products (product_id)
        ON DELETE   CASCADE
        ON UPDATE   CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = '1-to-1 stock record per product. UNSIGNED columns prevent negative quantities.';

-- -------------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------------
-- The UNIQUE constraint on product_id already creates an index for lookups.
-- Additional index to support low-stock alert queries efficiently.
CREATE INDEX idx_inv_low_stock
    ON inventory (quantity_on_hand);

-- =============================================================================
-- End of 04_create_inventory.sql
-- =============================================================================
