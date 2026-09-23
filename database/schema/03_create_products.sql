-- =============================================================================
-- Meera Bakery Online
-- File   : 03_create_products.sql
-- Table  : products
-- Purpose: Bakery items available for sale.
--          unit_price must be >= 0 (SR-4).
--          Soft-deleted with is_active = 0; hard DELETE is blocked by FK-7
--          (order_items references products with ON DELETE RESTRICT).
-- Depends: categories
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

CREATE TABLE IF NOT EXISTS products (
    -- -------------------------------------------------------------------------
    -- Primary key
    -- -------------------------------------------------------------------------
    product_id    INT UNSIGNED        NOT NULL AUTO_INCREMENT,

    -- -------------------------------------------------------------------------
    -- Foreign key to categories
    -- ON DELETE RESTRICT : cannot delete a category that has products.
    -- ON UPDATE CASCADE  : if category_id changes, propagate automatically.
    -- -------------------------------------------------------------------------
    category_id   TINYINT UNSIGNED    NOT NULL,

    -- -------------------------------------------------------------------------
    -- Business columns
    -- -------------------------------------------------------------------------
    name          VARCHAR(150)        NOT NULL,
    description   TEXT                    NULL,

    -- Monetary value: DECIMAL(10,2), non-negative (SR-1, SR-4)
    unit_price    DECIMAL(10,2)       NOT NULL,

    -- -------------------------------------------------------------------------
    -- Soft delete  (1 = visible on storefront, 0 = hidden)
    -- -------------------------------------------------------------------------
    is_active     TINYINT(1)          NOT NULL DEFAULT 1,

    -- -------------------------------------------------------------------------
    -- Audit timestamps  (DATETIME, UTC convention)
    -- -------------------------------------------------------------------------
    created_at    DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP
                                               ON UPDATE CURRENT_TIMESTAMP,

    -- -------------------------------------------------------------------------
    -- Constraints
    -- -------------------------------------------------------------------------
    CONSTRAINT pk_products            PRIMARY KEY (product_id),
    CONSTRAINT uq_products_name       UNIQUE      (name),
    CONSTRAINT chk_products_price     CHECK       (unit_price >= 0),

    CONSTRAINT fk_products_category
        FOREIGN KEY (category_id)
        REFERENCES  categories (category_id)
        ON DELETE   RESTRICT
        ON UPDATE   CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Bakery products available for sale';

-- -------------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------------
-- The UNIQUE constraint on name already creates an index.
CREATE INDEX idx_prod_category
    ON products (category_id);

CREATE INDEX idx_prod_active
    ON products (is_active);

-- =============================================================================
-- End of 03_create_products.sql
-- =============================================================================
