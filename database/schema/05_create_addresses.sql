-- =============================================================================
-- Meera Bakery Online
-- File   : 05_create_addresses.sql
-- Table  : addresses
-- Purpose: Normalized customer address book.
--          A customer can have multiple addresses (Home, Office, etc.).
--          At order creation the chosen address is copied into
--          orders.shipping_address_snapshot so the delivery address is
--          preserved even if this record is later modified or soft-deleted.
--          is_default: the application ensures only one default per customer.
-- Depends: customers
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

CREATE TABLE IF NOT EXISTS addresses (
    -- -------------------------------------------------------------------------
    -- Primary key
    -- -------------------------------------------------------------------------
    address_id    INT UNSIGNED        NOT NULL AUTO_INCREMENT,

    -- -------------------------------------------------------------------------
    -- Foreign key to customers
    -- ON DELETE RESTRICT : customer with addresses cannot be hard-deleted.
    --                      Use customers.is_active = 0 instead.
    -- ON UPDATE CASCADE  : propagate customer_id changes automatically.
    -- -------------------------------------------------------------------------
    customer_id   INT UNSIGNED        NOT NULL,

    -- -------------------------------------------------------------------------
    -- Address columns
    -- -------------------------------------------------------------------------
    label         VARCHAR(50)         NOT NULL DEFAULT 'Home'
                  COMMENT 'User-defined label e.g. Home, Office, Other',

    address_line1 VARCHAR(255)        NOT NULL
                  COMMENT 'Street number, flat, building name',

    address_line2 VARCHAR(255)            NULL
                  COMMENT 'Landmark, area, floor — optional',

    city          VARCHAR(100)        NOT NULL,
    state         VARCHAR(100)        NOT NULL,
    postal_code   VARCHAR(20)         NOT NULL,
    country       VARCHAR(60)         NOT NULL DEFAULT 'India',

    -- -------------------------------------------------------------------------
    -- Default flag
    -- Only one address per customer should have is_default = 1.
    -- This rule is enforced by the application layer, not the DB.
    -- -------------------------------------------------------------------------
    is_default    TINYINT(1)          NOT NULL DEFAULT 0,

    -- -------------------------------------------------------------------------
    -- Soft delete  (1 = active, 0 = hidden)
    -- Prefer soft-delete over hard DELETE to protect order history.
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
    CONSTRAINT pk_addresses           PRIMARY KEY (address_id),

    CONSTRAINT fk_addresses_customer
        FOREIGN KEY (customer_id)
        REFERENCES  customers (customer_id)
        ON DELETE   RESTRICT
        ON UPDATE   CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Customer address book. Snapshot is copied to orders at checkout.';

-- -------------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------------
-- All addresses belonging to a customer
CREATE INDEX idx_addr_customer
    ON addresses (customer_id);

-- Fast lookup of the default address for a given customer
CREATE INDEX idx_addr_default
    ON addresses (customer_id, is_default);

-- =============================================================================
-- End of 05_create_addresses.sql
-- =============================================================================
