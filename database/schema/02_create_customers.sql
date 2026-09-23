-- =============================================================================
-- Meera Bakery Online
-- File   : 02_create_customers.sql
-- Table  : customers
-- Purpose: Registered buyers.
--          Authentication is handled externally (e.g. AWS Cognito).
--          No password or password_hash column is stored here. (SR-9)
-- Depends: none
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

CREATE TABLE IF NOT EXISTS customers (
    -- -------------------------------------------------------------------------
    -- Primary key
    -- -------------------------------------------------------------------------
    customer_id   INT UNSIGNED        NOT NULL AUTO_INCREMENT,

    -- -------------------------------------------------------------------------
    -- Business columns
    -- -------------------------------------------------------------------------
    first_name    VARCHAR(80)         NOT NULL,
    last_name     VARCHAR(80)         NOT NULL,

    -- email is the unique business identifier used for account lookup.
    -- Max length 254 per RFC 5321.
    -- Authentication (password handling) is performed by an external service.
    email         VARCHAR(254)        NOT NULL,

    phone         VARCHAR(20)             NULL
                  COMMENT 'E.164 format recommended, e.g. +919876543210',

    -- -------------------------------------------------------------------------
    -- Soft delete  (1 = active, 0 = deactivated)
    -- Customers with orders must NOT be hard-deleted (FK-4 RESTRICT).
    -- Set is_active = 0 instead.
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
    CONSTRAINT pk_customers           PRIMARY KEY (customer_id),
    CONSTRAINT uq_customers_email     UNIQUE      (email)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Registered bakery customers. No credentials stored here.';

-- -------------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------------
-- The UNIQUE constraint on email already creates an index for login lookups.
-- Additional index to filter active customers efficiently.
CREATE INDEX idx_cust_active
    ON customers (is_active);

-- =============================================================================
-- End of 02_create_customers.sql
-- =============================================================================
