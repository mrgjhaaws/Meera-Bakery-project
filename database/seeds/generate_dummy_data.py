"""
database/seeds/generate_dummy_data.py
=======================================
Generates a realistic, constraint-valid dummy dataset for the meera_bakery
database — customers, addresses, orders, and order_items — sized and
distributed for data science practice (RFM / customer segmentation,
revenue trend analysis, cohort analysis, category performance, and so on).

WHAT THIS DOES NOT TOUCH
-------------------------
- categories / products / inventory are left as-is. Run
  seed_categories.sql and seed_products.sql first if you haven't already
  (this script reads active products from the DB rather than hardcoding
  them, so it stays correct even if you've edited the catalog).
- inventory.quantity_on_hand is NOT adjusted to reconcile with the orders
  generated here — a deliberate simplification, since the goal is
  customer/order/revenue analytics, not stock accuracy. Say so if you'd
  like a version that also keeps inventory consistent.

WHAT IT GENERATES
-------------------
- --customers customers (unique emails, Indian names/cities), each with
  1-2 addresses.
- A skewed number of orders per customer — most customers order once or
  twice, a smaller "loyal" segment orders many times (11-18). Good for
  RFM / customer-segmentation practice.
- Orders spread over the last --range-days days, weighted toward more
  recent months (a gentle growth trend). Good for time-series / revenue-
  trend practice.
- Order status realistic by age: orders older than 5 days are mostly
  'delivered' or 'cancelled'; orders from the last 5 days are spread
  across the full pipeline (pending -> ... -> delivered).
- 1-4 line items per order, with product selection weighted so cheaper
  items (cookies, pastries, beverages) sell more often than cakes — good
  for category / Pareto analysis.
- Financial totals computed with the exact same subtotal -> discount ->
  taxable_amount -> tax_amount -> total_amount sequence the FastAPI app
  uses (see app/utils/financial.py), so the data is internally consistent
  and every row would pass the schema's CHECK constraints.

USAGE
------
    pip install faker mysql-connector-python
    # (or: pip install -r database/seeds/requirements.txt)

    python generate_dummy_data.py                    # defaults: 80 customers, 270-day range
    python generate_dummy_data.py --customers 150 --seed 42
    python generate_dummy_data.py --reset             # TRUNCATEs orders/order_items/addresses/customers first

Reads DB connection settings from environment variables (same names as
app/.env): DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD — defaults to
127.0.0.1:3306/meera_bakery/root/(empty) if unset, which is convenient for
a local MySQL/MariaDB dev instance. To point it at your app's real .env:

    cd database/seeds
    export $(grep -v '^#' ../../app/.env | xargs)
    python generate_dummy_data.py

This script INSERTS DIRECTLY over a MySQL connection using its own cursor
and transaction — it does not go through the FastAPI app at all. Point it
at a dev/local database, not production, unless you're sure that's what
you want.
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import mysql.connector
from faker import Faker

fake = Faker("en_IN")
TWO_PLACES = Decimal("0.01")

INDIAN_CITIES = [
    ("Bengaluru", "Karnataka"), ("Mysuru", "Karnataka"),
    ("Chennai", "Tamil Nadu"), ("Coimbatore", "Tamil Nadu"),
    ("Hyderabad", "Telangana"), ("Pune", "Maharashtra"),
    ("Mumbai", "Maharashtra"), ("Kochi", "Kerala"),
]


def money(x) -> Decimal:
    """Round to 2 decimal places, matching the schema's DECIMAL(10,2) columns."""
    return Decimal(str(x)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def get_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", 3306)),
        database=os.environ.get("DB_NAME", "meera_bakery"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def reset_data(cursor) -> None:
    print("--reset: truncating order_items, orders, addresses, customers...")
    cursor.execute("SET FOREIGN_KEY_CHECKS=0")
    for table in ("order_items", "orders", "addresses", "customers"):
        cursor.execute(f"TRUNCATE TABLE {table}")
    cursor.execute("SET FOREIGN_KEY_CHECKS=1")


def load_active_products(cursor) -> list[dict]:
    cursor.execute(
        "SELECT product_id, name, unit_price FROM products WHERE is_active = 1"
    )
    return cursor.fetchall()


def weight_products_by_price(products: list[dict]) -> list[tuple[dict, float]]:
    """Cheaper categories (cookies/pastries/beverages) sell more often than cakes."""
    weighted = []
    for p in products:
        price = float(p["unit_price"])
        weight = 3.0 if price < 60 else (1.6 if price < 150 else 0.6)
        weighted.append((p, weight))
    return weighted


# =============================================================================
# Customers & addresses
# =============================================================================

def create_customers(cursor, n: int) -> list[int]:
    customer_ids = []
    for _ in range(n):
        first, last = fake.first_name(), fake.last_name()
        email = f"{first.lower()}.{last.lower()}{random.randint(1, 9999)}@example.com"
        phone = f"+91{random.randint(7000000000, 9999999999)}"
        created = fake.date_time_between(start_date="-1y", end_date="-9M")
        cursor.execute(
            """INSERT INTO customers
               (first_name, last_name, email, phone, is_active, created_at, updated_at)
               VALUES (%s, %s, %s, %s, 1, %s, %s)""",
            (first, last, email, phone, created, created),
        )
        customer_ids.append(cursor.lastrowid)
    return customer_ids


def create_addresses(cursor, customer_ids: list[int]) -> dict[int, list[int]]:
    address_map: dict[int, list[int]] = {}
    for cid in customer_ids:
        n_addr = random.choices([1, 2], weights=[0.8, 0.2])[0]
        ids = []
        for i in range(n_addr):
            city, state = random.choice(INDIAN_CITIES)
            line2 = random.choice([
                None, None,
                f"Flat {random.randint(1, 20)}{random.choice('ABC')}",
                f"Near {fake.street_name()}",
            ])
            cursor.execute(
                """INSERT INTO addresses
                   (customer_id, label, address_line1, address_line2, city, state,
                    postal_code, country, is_default, is_active, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'India', %s, 1, NOW(), NOW())""",
                (
                    cid, "Home" if i == 0 else "Work",
                    fake.street_address(), line2,
                    city, state, fake.postcode(),
                    1 if i == 0 else 0,
                ),
            )
            ids.append(cursor.lastrowid)
        address_map[cid] = ids
    return address_map


# =============================================================================
# Orders & order_items
# =============================================================================

def orders_for_customer() -> int:
    """Skewed order-count per customer — a loyal-customer tail for segmentation practice."""
    r = random.random()
    if r < 0.40:
        return 1
    if r < 0.75:
        return random.randint(2, 4)
    if r < 0.95:
        return random.randint(5, 10)
    return random.randint(11, 18)


def pick_status(order_age_days: int) -> str:
    if order_age_days > 5:
        return random.choices(
            ["delivered", "cancelled", "shipped"], weights=[0.85, 0.10, 0.05]
        )[0]
    return random.choices(
        ["pending", "confirmed", "preparing", "shipped", "delivered", "cancelled"],
        weights=[0.15, 0.15, 0.15, 0.15, 0.30, 0.10],
    )[0]


def biased_order_date(range_days: int) -> datetime:
    """Weighted toward more recent days — a gentle growth-over-time trend.

    Uses days_ago = range_days * u**k with k > 1 (u ~ Uniform(0,1)): for
    k > 1 this is stochastically smaller than a uniform draw, so most mass
    concentrates near days_ago = 0 (recent) with a long tail back to
    range_days (older). k < 1 would skew the wrong way (mass toward the
    oldest dates) — that was a bug caught during testing.
    """
    u = random.random()
    days_ago = int((u ** 2) * range_days)
    return datetime.now() - timedelta(
        days=days_ago, hours=random.randint(7, 20), minutes=random.randint(0, 59)
    )


def pick_order_items(weighted_products: list[tuple[dict, float]]) -> list[dict]:
    products, weights = zip(*weighted_products)
    n_items = random.choices([1, 2, 3, 4], weights=[0.35, 0.35, 0.20, 0.10])[0]
    chosen, seen = [], set()
    attempts = 0
    while len(chosen) < min(n_items, len(products)) and attempts < 20:
        p = random.choices(products, weights=weights, k=1)[0]
        attempts += 1
        if p["product_id"] in seen:
            continue
        seen.add(p["product_id"])
        chosen.append(p)
    return chosen


def build_order(cursor, customer_id: int, address_id: int,
                 weighted_products: list[tuple[dict, float]], range_days: int) -> int:
    ordered_at = biased_order_date(range_days)
    age_days = (datetime.now() - ordered_at).days
    status = pick_status(age_days)

    # ---- Line items ----
    line_items = []
    subtotal = Decimal("0.00")
    for p in pick_order_items(weighted_products):
        qty = random.choices([1, 2, 3, 4], weights=[0.45, 0.30, 0.15, 0.10])[0]
        unit_price = money(p["unit_price"])

        item_discount_percent = Decimal(random.choice([5, 10])) if random.random() < 0.10 else Decimal("0.00")
        gross = unit_price * qty
        item_discount_amount = money(gross * item_discount_percent / 100)
        line_total = money(gross - item_discount_amount)

        subtotal += line_total
        line_items.append({
            "product_id": p["product_id"],
            "quantity": qty,
            "unit_price_at_order": unit_price,
            "item_discount_amount": item_discount_amount,
            "item_discount_percent": item_discount_percent,
            "line_total": line_total,
        })
    subtotal = money(subtotal)

    # ---- Order-level discount (mutually exclusive: flat OR percent, matching
    #      order_service's rule) ----
    discount_amount = Decimal("0.00")
    discount_percent = Decimal("0.00")
    roll = random.random()
    if roll < 0.15:
        discount_percent = Decimal(random.choice([5, 10, 15]))
        discount_amount = money(subtotal * discount_percent / 100)
    elif roll < 0.25:
        discount_amount = min(money(random.choice([20, 30, 50])), subtotal)

    # ---- Mandated calculation sequence (matches utils/financial.py) ----
    taxable_amount = money(subtotal - discount_amount)
    tax_percent = Decimal("5.00")
    tax_amount = money(taxable_amount * tax_percent / 100)
    total_amount = money(taxable_amount + tax_amount)

    notes = random.choice([None, None, None, "Leave at the door", "Please call on arrival", "Ring the bell twice"])

    cursor.execute(
        """INSERT INTO orders
           (customer_id, address_id, shipping_address_snapshot, status,
            subtotal, discount_amount, discount_percent, taxable_amount,
            tax_percent, tax_amount, total_amount, notes,
            ordered_at, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            customer_id, address_id, "Snapshot generated by dummy data script",
            status, subtotal, discount_amount, discount_percent, taxable_amount,
            tax_percent, tax_amount, total_amount, notes,
            ordered_at, ordered_at, ordered_at,
        ),
    )
    order_id = cursor.lastrowid

    for item in line_items:
        cursor.execute(
            """INSERT INTO order_items
               (order_id, product_id, quantity, unit_price_at_order,
                item_discount_amount, item_discount_percent, line_total,
                created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                order_id, item["product_id"], item["quantity"], item["unit_price_at_order"],
                item["item_discount_amount"], item["item_discount_percent"], item["line_total"],
                ordered_at, ordered_at,
            ),
        )
    return order_id


# =============================================================================
# Summary (sanity-check output after generation)
# =============================================================================

def print_summary(cursor) -> None:
    cursor.execute("SELECT COUNT(*) AS n FROM customers")
    n_customers = cursor.fetchone()["n"]
    cursor.execute("SELECT COUNT(*) AS n FROM orders")
    n_orders = cursor.fetchone()["n"]
    cursor.execute("SELECT MIN(ordered_at) AS lo, MAX(ordered_at) AS hi FROM orders")
    date_range = cursor.fetchone()
    cursor.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC")
    by_status = cursor.fetchall()
    cursor.execute("SELECT SUM(total_amount) AS revenue FROM orders WHERE status = 'delivered'")
    revenue = cursor.fetchone()["revenue"]

    print("\n--- Summary -----------------------------------------")
    print(f"Customers:        {n_customers}")
    print(f"Orders:           {n_orders}")
    print(f"Date range:       {date_range['lo']}  to  {date_range['hi']}")
    print(f"Delivered revenue: ₹{revenue}")
    print("Orders by status:")
    for row in by_status:
        print(f"  {row['status']:<10} {row['n']}")
    print("-------------------------------------------------------")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dummy data for meera_bakery")
    parser.add_argument("--customers", type=int, default=80, help="Number of customers to create")
    parser.add_argument("--range-days", type=int, default=270, help="How far back orders are spread (days)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible data")
    parser.add_argument("--reset", action="store_true",
                         help="TRUNCATE order_items/orders/addresses/customers before generating")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    conn = get_connection()
    conn.autocommit = False
    cursor = conn.cursor(dictionary=True)

    try:
        if args.reset:
            reset_data(cursor)

        products = load_active_products(cursor)
        if not products:
            raise SystemExit(
                "No active products found — run seed_categories.sql and "
                "seed_products.sql first."
            )
        weighted_products = weight_products_by_price(products)

        print(f"Creating {args.customers} customers...")
        customer_ids = create_customers(cursor, args.customers)

        print("Creating addresses...")
        address_map = create_addresses(cursor, customer_ids)

        print("Creating orders...")
        total_orders = 0
        for cid in customer_ids:
            addr_ids = address_map[cid]
            for _ in range(orders_for_customer()):
                address_id = random.choice(addr_ids)
                build_order(cursor, cid, address_id, weighted_products, args.range_days)
                total_orders += 1

        conn.commit()
        print(f"\nCommitted: {len(customer_ids)} customers, {total_orders} orders.")
        print_summary(cursor)

    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
