-- =============================================================================
-- Meera Bakery Online
-- File   : 07_create_order_items.sql
-- Table  : order_items
-- Purpose: Individual line items within an order.
--          One row per product per order.
--
-- Price snapshot (SR-6):
--   unit_price_at_order is copied from products.unit_price at insert time
--   and NEVER updated. Historical price accuracy is preserved even when
--   the product price changes later.
--
-- Line total formula:
--   item_discount = MAX(item_discount_amount,
--                       unit_price_at_order × quantity × item_discount_percent / 100)
--   line_total    = (unit_price_at_order × quantity) − item_discount
--   (Only one discount mechanism applied per line; application enforces this.)
--
-- All monetary columns : DECIMAL(10,2), CHECK >= 0  (SR-1)
-- All percentage columns: DECIMAL(5,2),  CHECK 0–100 (SR-2)
-- quantity              : SMALLINT UNSIGNED, CHECK >= 1 (SR-3)
--
-- Depends: orders, products
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

CREATE TABLE IF NOT EXISTS order_items (
    -- -------------------------------------------------------------------------
    -- Primary key
    -- -------------------------------------------------------------------------
    order_item_id         INT UNSIGNED    NOT NULL AUTO_INCREMENT,

    -- -------------------------------------------------------------------------
    -- Foreign key to orders
    -- ON DELETE CASCADE : deleting an order removes all its line items.
    -- ON UPDATE CASCADE : propagate order_id changes automatically.
    -- -------------------------------------------------------------------------
    order_id              INT UNSIGNED    NOT NULL,

    -- -------------------------------------------------------------------------
    -- Foreign key to products
    -- ON DELETE RESTRICT : cannot delete a product referenced in order history.
    --                      Use products.is_active = 0 instead.
    -- ON UPDATE CASCADE  : propagate product_id changes automatically.
    -- -------------------------------------------------------------------------
    product_id            INT UNSIGNED    NOT NULL,

    -- -------------------------------------------------------------------------
    -- Quantity  (SR-3: must be >= 1, zero-quantity lines not permitted)
    -- -------------------------------------------------------------------------
    quantity              SMALLINT UNSIGNED NOT NULL
                          COMMENT 'Number of units ordered. Must be >= 1.',

    -- -------------------------------------------------------------------------
    -- Price snapshot (SR-6)
    -- Copied from products.unit_price at the moment the order is placed.
    -- This column is NEVER updated after insert.
    -- -------------------------------------------------------------------------
    unit_price_at_order   DECIMAL(10,2)   NOT NULL
                          COMMENT 'Price per unit at the time of order. Immutable snapshot.',

    -- -------------------------------------------------------------------------
    -- Item-level discount  (SR-1, SR-2)
    -- Only one discount mechanism is applied per line (app enforces).
    -- -------------------------------------------------------------------------
    item_discount_amount  DECIMAL(10,2)   NOT NULL DEFAULT 0.00
                          COMMENT 'Flat item-level discount amount',

    item_discount_percent DECIMAL(5,2)    NOT NULL DEFAULT 0.00
                          COMMENT 'Percentage item-level discount (0.00–100.00)',

    -- -------------------------------------------------------------------------
    -- Line total  (SR-1)
    -- Formula: (unit_price_at_order × quantity) − applied item discount
    -- Computed by application, stored for fast aggregation.
    -- -------------------------------------------------------------------------
    line_total            DECIMAL(10,2)   NOT NULL
                          COMMENT '(unit_price_at_order × quantity) minus item discount',

    -- -------------------------------------------------------------------------
    -- Audit timestamps  (DATETIME, UTC convention)
    -- -------------------------------------------------------------------------
    created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                   ON UPDATE CURRENT_TIMESTAMP,

    -- -------------------------------------------------------------------------
    -- Constraints
    -- -------------------------------------------------------------------------
    CONSTRAINT pk_order_items             PRIMARY KEY (order_item_id),

    -- One product line per order (prevents duplicate entries for same product)
    CONSTRAINT uq_order_items_order_product UNIQUE (order_id, product_id),

    -- Quantity must be at least 1 (SR-3)
    CONSTRAINT chk_oi_quantity            CHECK (quantity                >= 1),

    -- Monetary CHECK constraints (SR-1)
    CONSTRAINT chk_oi_unit_price          CHECK (unit_price_at_order     >= 0),
    CONSTRAINT chk_oi_discount_amount     CHECK (item_discount_amount    >= 0),
    CONSTRAINT chk_oi_line_total          CHECK (line_total              >= 0),

    -- Percentage CHECK constraint (SR-2)
    CONSTRAINT chk_oi_discount_percent    CHECK (item_discount_percent   >= 0
                                            AND  item_discount_percent   <= 100),

    -- Foreign keys
    CONSTRAINT fk_order_items_order
        FOREIGN KEY (order_id)
        REFERENCES  orders (order_id)
        ON DELETE   CASCADE
        ON UPDATE   CASCADE,

    CONSTRAINT fk_order_items_product
        FOREIGN KEY (product_id)
        REFERENCES  products (product_id)
        ON DELETE   RESTRICT
        ON UPDATE   CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Line items within an order. unit_price_at_order is an immutable snapshot.';

-- -------------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------------
-- The UNIQUE (order_id, product_id) constraint already creates a covering
-- index that serves most order-item lookups.

-- Separate index to support product-level sales reports
CREATE INDEX idx_oi_product
    ON order_items (product_id);

-- =============================================================================
-- End of 07_create_order_items.sql
-- =============================================================================
