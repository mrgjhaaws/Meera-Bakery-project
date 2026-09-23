-- =============================================================================
-- Meera Bakery Online
-- File   : 01_create_categories.sql
-- Table  : categories
-- Purpose: Product category lookup table.
--          Replaces a hard-coded ENUM so categories can be added or retired
--          without a schema migration.
-- Depends: none
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

CREATE TABLE IF NOT EXISTS categories (
    -- -------------------------------------------------------------------------
    -- Primary key
    -- -------------------------------------------------------------------------
    category_id   TINYINT UNSIGNED    NOT NULL AUTO_INCREMENT,

    -- -------------------------------------------------------------------------
    -- Business columns
    -- -------------------------------------------------------------------------
    name          VARCHAR(80)         NOT NULL,
    description   VARCHAR(255)            NULL,

    -- -------------------------------------------------------------------------
    -- Soft delete  (1 = active, 0 = hidden from storefront)
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
    CONSTRAINT pk_categories        PRIMARY KEY (category_id),
    CONSTRAINT uq_categories_name   UNIQUE      (name)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Bakery product categories (e.g. Bread, Cake, Pastry)';

-- -------------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------------
CREATE INDEX idx_cat_active
    ON categories (is_active);

-- =============================================================================
-- End of 01_create_categories.sql
-- =============================================================================
