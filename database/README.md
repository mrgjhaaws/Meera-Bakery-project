# Meera Bakery Online — Database

> **AWS Region:** ap-south-1  
> **RDS Identifier:** database-1  
> **Database name:** `meera_bakery`  
> **MySQL version:** 8.4  
> **RDS access:** Private only — never publicly accessible.

---

## Security Rules

| Rule | Detail |
|------|--------|
| RDS is private | The RDS instance is not publicly accessible. Access is allowed only from EC2 instances in the `meera-bakery-sg` security group. |
| No credentials in code | No passwords, connection strings, or secrets are stored in any file in this project. Use **AWS Secrets Manager** to manage the RDS password. |
| No auth columns | The `customers` table has no `password` or `password_hash` column. Authentication is handled externally (e.g. AWS Cognito). |

---

## Table Overview

| # | Table | Purpose |
|---|-------|---------|
| 1 | `categories` | Product category lookup |
| 2 | `customers` | Registered buyers (no credentials) |
| 3 | `products` | Bakery items for sale |
| 4 | `inventory` | Stock levels — 1-to-1 with products |
| 5 | `addresses` | Customer address book |
| 6 | `orders` | Order header with financial totals |
| 7 | `order_items` | Line items within each order |

---

## Folder Structure

```
database/
├── schema/                  # DDL — run in order
│   ├── 01_create_categories.sql
│   ├── 02_create_customers.sql
│   ├── 03_create_products.sql
│   ├── 04_create_inventory.sql
│   ├── 05_create_addresses.sql
│   ├── 06_create_orders.sql
│   └── 07_create_order_items.sql
├── seeds/                   # Initial data — run after schema
│   ├── seed_categories.sql
│   └── seed_products.sql
├── queries/                 # Reusable business queries
│   ├── low_stock_report.sql
│   ├── customer_order_history.sql
│   └── daily_revenue.sql
└── README.md
```

---

## Schema Creation Order

Tables must be created in this order due to foreign key dependencies:

```
1. categories      — no dependencies
2. customers       — no dependencies
3. products        — FK → categories
4. inventory       — FK → products
5. addresses       — FK → customers
6. orders          — FK → customers, FK → addresses
7. order_items     — FK → orders, FK → products
```

To drop all tables (teardown), reverse the order:
`order_items → orders → addresses → inventory → products → customers → categories`

---

## How to Apply the Schema

Connect to the RDS instance from an EC2 instance inside the VPC:

```bash
mysql -h <rds-endpoint> -u <admin-user> -p
```

> The RDS endpoint is found in the AWS Console under RDS → Databases → database-1 → Connectivity.  
> Use AWS Secrets Manager to retrieve the password — do not type it into scripts.

Then run each schema file in order:

```sql
CREATE DATABASE IF NOT EXISTS meera_bakery
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

SOURCE database/schema/01_create_categories.sql;
SOURCE database/schema/02_create_customers.sql;
SOURCE database/schema/03_create_products.sql;
SOURCE database/schema/04_create_inventory.sql;
SOURCE database/schema/05_create_addresses.sql;
SOURCE database/schema/06_create_orders.sql;
SOURCE database/schema/07_create_order_items.sql;
```

Then seed initial data:

```sql
SOURCE database/seeds/seed_categories.sql;
SOURCE database/seeds/seed_products.sql;
```

---

## Financial Calculation Order

Every order's financials are calculated by the application in this sequence
and stored on the `orders` row for fast reads:

```
subtotal        = SUM(order_items.line_total)
discount_amount = flat discount OR (subtotal × discount_percent / 100)
taxable_amount  = subtotal − discount_amount
tax_amount      = taxable_amount × tax_percent / 100
total_amount    = taxable_amount + tax_amount
```

Tax is always calculated on the **post-discount** amount.

---

## Order Status Lifecycle

```
pending → confirmed → preparing → shipped → delivered
   └─────────────────────────────────────────→ cancelled
```

| Status | Inventory action |
|--------|-----------------|
| `confirmed` | Decrement `quantity_on_hand` per line item (in a transaction) |
| `cancelled` (before shipped) | Increment `quantity_on_hand` back (in a transaction) |

---

## Key Design Decisions

| Decision | Choice |
|----------|--------|
| Monetary types | `DECIMAL(10,2)` — no floating-point rounding errors |
| Percentage types | `DECIMAL(5,2)` with `CHECK (0–100)` |
| Inventory negative prevention | `INT UNSIGNED` — engine-level guarantee |
| Price history | `unit_price_at_order` snapshot on `order_items` — immutable |
| Address history | `shipping_address_snapshot` TEXT on `orders` — immutable |
| Soft deletes | `is_active` flag on `categories`, `products`, `customers`, `addresses` |
| Category extensibility | Separate `categories` table (not ENUM) |
| Authentication | External only — no credentials in this database |
| Timestamps | `DATETIME` (no 2038 issue), UTC convention |
