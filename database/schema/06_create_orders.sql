-- =============================================================================
-- Meera Bakery Online
-- File   : 06_create_orders.sql
-- Table  : orders
-- Purpose: Purchase transaction header. One row per customer order.
--
-- Financial calculation order (SR-6):
--   subtotal        = SUM(order_items.line_total)
--   discount_amount = MAX(flat discount, subtotal × discount_percent / 100)
--                     (only one discount mechanism applied per order)
--   taxable_amount  = subtotal − discount_amount
--   tax_amount      = taxable_amount × tax_percent / 100
--   total_amount    = taxable_amount + tax_amount
--
-- All monetary columns: DECIMAL(10,2), CHECK >= 0  (SR-1)
-- All percentage columns: DECIMAL(5,2), CHECK 0–100 (SR-2)
--
-- shipping_address_snapshot (SR-7):
--   Full address text written ONCE at order creation. Never updated.
--   Preserves delivery address even if addresses record is later changed.
--
-- address_id (SR-8):
--   Nullable FK. ON DELETE SET NULL — snapshot guarantees no data loss.
--
-- Depends: customers, addresses
-- MySQL  : 8.4
-- =============================================================================

USE meera_bakery;

CREATE TABLE IF NOT EXISTS orders (
    -- -------------------------------------------------------------------------
    -- Primary key
    -- -------------------------------------------------------------------------
    order_id          INT UNSIGNED        NOT NULL AUTO_INCREMENT,

    -- -------------------------------------------------------------------------
    -- Foreign key to customers
    -- ON DELETE RESTRICT : customer with orders cannot be hard-deleted.
    -- ON UPDATE CASCADE  : propagate customer_id changes automatically.
    -- -------------------------------------------------------------------------
    customer_id       INT UNSIGNED        NOT NULL,

    -- -------------------------------------------------------------------------
    -- Foreign key to addresses (SR-8 — nullable)
    -- ON DELETE SET NULL : if address is hard-deleted, FK becomes NULL.
    --                      shipping_address_snapshot still holds the full text.
    -- ON UPDATE CASCADE  : propagate address_id changes automatically.
    -- -------------------------------------------------------------------------
    address_id        INT UNSIGNED            NULL,

    -- -------------------------------------------------------------------------
    -- Address snapshot (SR-7)
    -- Written once at order creation from addresses record. Never modified.
    -- -------------------------------------------------------------------------
    shipping_address_snapshot TEXT           NOT NULL
                  COMMENT 'Full address text captured at order creation. Immutable.',

    -- -------------------------------------------------------------------------
    -- Order status lifecycle
    -- Valid transitions enforced by application layer:
    --   pending → confirmed → preparing → shipped → delivered
    --   any pre-delivered stage → cancelled
    -- -------------------------------------------------------------------------
    status            ENUM(
                        'pending',
                        'confirmed',
                        'preparing',
                        'shipped',
                        'delivered',
                        'cancelled'
                      )                    NOT NULL DEFAULT 'pending',

    -- -------------------------------------------------------------------------
    -- Financial columns  (SR-1: DECIMAL(10,2); SR-2: DECIMAL(5,2))
    --
    -- Calculation order:
    --   1. subtotal        = SUM(order_items.line_total)
    --   2. discount_amount = flat OR (subtotal × discount_percent / 100)
    --   3. taxable_amount  = subtotal − discount_amount
    --   4. tax_amount      = taxable_amount × tax_percent / 100
    --   5. total_amount    = taxable_amount + tax_amount
    -- -------------------------------------------------------------------------

    -- Step 1
    subtotal          DECIMAL(10,2)       NOT NULL
                      COMMENT 'Sum of all order_items.line_total before order-level discount',

    -- Step 2a — flat discount (mutually exclusive with percent; app enforces)
    discount_amount   DECIMAL(10,2)       NOT NULL DEFAULT 0.00
                      COMMENT 'Flat order-level discount amount',

    -- Step 2b — percentage discount (mutually exclusive with flat; app enforces)
    discount_percent  DECIMAL(5,2)        NOT NULL DEFAULT 0.00
                      COMMENT 'Percentage order-level discount (0.00–100.00)',

    -- Step 3
    taxable_amount    DECIMAL(10,2)       NOT NULL
                      COMMENT 'subtotal minus applied discount; tax is calculated on this amount',

    -- Step 4a — tax rate (e.g. GST 18.00)
    tax_percent       DECIMAL(5,2)        NOT NULL DEFAULT 0.00
                      COMMENT 'Tax rate applied to taxable_amount (0.00–100.00)',

    -- Step 4b — stored for audit trail
    tax_amount        DECIMAL(10,2)       NOT NULL DEFAULT 0.00
                      COMMENT 'taxable_amount × tax_percent / 100; stored immutably for audit',

    -- Step 5
    total_amount      DECIMAL(10,2)       NOT NULL
                      COMMENT 'taxable_amount + tax_amount; final amount payable by customer',

    -- -------------------------------------------------------------------------
    -- Optional fields
    -- -------------------------------------------------------------------------
    notes             TEXT                    NULL
                      COMMENT 'Customer delivery instructions or special requests',

    -- Business event timestamp (when the customer placed the order)
    ordered_at        DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- -------------------------------------------------------------------------
    -- Audit timestamps  (DATETIME, UTC convention)
    -- -------------------------------------------------------------------------
    created_at        DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                   ON UPDATE CURRENT_TIMESTAMP,

    -- -------------------------------------------------------------------------
    -- Constraints
    -- -------------------------------------------------------------------------
    CONSTRAINT pk_orders              PRIMARY KEY (order_id),

    -- Monetary CHECK constraints (SR-1)
    CONSTRAINT chk_orders_subtotal         CHECK (subtotal        >= 0),
    CONSTRAINT chk_orders_discount_amount  CHECK (discount_amount >= 0),
    CONSTRAINT chk_orders_taxable_amount   CHECK (taxable_amount  >= 0),
    CONSTRAINT chk_orders_tax_amount       CHECK (tax_amount      >= 0),
    CONSTRAINT chk_orders_total_amount     CHECK (total_amount    >= 0),

    -- Percentage CHECK constraints (SR-2)
    CONSTRAINT chk_orders_discount_percent CHECK (discount_percent >= 0 AND discount_percent <= 100),
    CONSTRAINT chk_orders_tax_percent      CHECK (tax_percent      >= 0 AND tax_percent      <= 100),

    -- Foreign keys
    CONSTRAINT fk_orders_customer
        FOREIGN KEY (customer_id)
        REFERENCES  customers (customer_id)
        ON DELETE   RESTRICT
        ON UPDATE   CASCADE,

    CONSTRAINT fk_orders_address
        FOREIGN KEY (address_id)
        REFERENCES  addresses (address_id)
        ON DELETE   SET NULL
        ON UPDATE   CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Order header. Financial totals computed by app, stored here for fast reads.';

-- -------------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------------
-- Customer order history
CREATE INDEX idx_ord_customer
    ON orders (customer_id);

-- Admin order management queue filtered by status
CREATE INDEX idx_ord_status
    ON orders (status);

-- Date-range revenue reports
CREATE INDEX idx_ord_ordered_at
    ON orders (ordered_at);

-- FK-5 column: address_id is a nullable FK used in JOINs and constraint checks.
-- InnoDB does not auto-create an index on nullable FK columns; explicit index
-- avoids full table scans during FK enforcement and admin queries. (audit C-3)
CREATE INDEX idx_ord_address
    ON orders (address_id);

-- =============================================================================
-- End of 06_create_orders.sql
-- =============================================================================
