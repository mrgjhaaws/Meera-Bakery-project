"""
repositories/inventory_repository.py
=====================================
Direct SQL queries for the inventory table — stock adjustment operations
used exclusively by order_service during order status transitions.

Business rules (from database/schema/04_create_inventory.sql and
utils/financial.py)
--------------------------------------------------------------------------
- Inventory is decremented when an order transitions to 'confirmed'.
- Inventory is incremented back when a 'confirmed'/'preparing'/'shipped'
  order transitions to 'cancelled' (no reversal from 'pending', since
  nothing was decremented yet).
- quantity_on_hand is INT UNSIGNED — the column itself cannot go negative,
  but we still check availability explicitly so a clean InsufficientStockError
  is raised instead of a raw MySQL integrity error.

Locking strategy
-----------------
decrement_stock() and increment_stock() both use SELECT ... FOR UPDATE to
take a row-level lock on the inventory row before reading quantity_on_hand.
This prevents a race condition where two concurrent requests both read the
same stock level and both decide there is enough stock to proceed. The lock
is held until the caller commits or rolls back the enclosing transaction
(conn.commit() / rollback happen in order_service, not here).

Rules (consistent with Phases 2-4 repositories)
--------------------------------------------------
- All SQL is parameterised.
- Cursors always use dictionary=True.
- Raw MySQLError is caught and re-raised as DatabaseError.
- This repository never calls conn.commit() — the service layer owns the
  transaction boundary (it also has to update the order status row in the
  same transaction).

Public interface
----------------
    decrement_stock(conn, product_id, product_name, quantity) -> None
        Raises InsufficientStockError if not enough stock.
        Raises NotFoundError if the product has no inventory row.

    increment_stock(conn, product_id, quantity) -> None
        Raises NotFoundError if the product has no inventory row.
"""

from __future__ import annotations

import logging

from mysql.connector import Error as MySQLError
from mysql.connector.pooling import PooledMySQLConnection

from utils.exceptions import DatabaseError, InsufficientStockError, NotFoundError

logger = logging.getLogger(__name__)


def decrement_stock(
    conn: PooledMySQLConnection,
    product_id: int,
    product_name: str,
    quantity: int,
) -> None:
    """Decrement quantity_on_hand for one product, failing safely on shortage.

    Parameters
    ----------
    conn          : Pooled connection — must be part of an open transaction
                    (autocommit=False). Caller commits after all items succeed.
    product_id    : FK to products / inventory.
    product_name  : Used only to build a clear InsufficientStockError message.
    quantity      : Units to remove from stock (> 0).

    Raises
    ------
    NotFoundError          : No inventory row exists for this product.
    InsufficientStockError : quantity_on_hand < quantity requested.
    DatabaseError           : Unexpected MySQL error.
    """
    select_sql = """
        SELECT quantity_on_hand
        FROM inventory
        WHERE product_id = %s
        FOR UPDATE
    """
    update_sql = """
        UPDATE inventory
        SET    quantity_on_hand = quantity_on_hand - %s
        WHERE  product_id = %s
    """

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(select_sql, (product_id,))
        row: dict | None = cursor.fetchone()

        if row is None:
            cursor.close()
            raise NotFoundError("inventory", product_id)

        available: int = row["quantity_on_hand"]
        if available < quantity:
            cursor.close()
            raise InsufficientStockError(
                product_id=product_id,
                product_name=product_name,
                requested=quantity,
                available=available,
            )

        cursor.execute(update_sql, (quantity, product_id))
        cursor.close()

        logger.debug(
            "inventory_repository.decrement_stock: product_id=%d -%d (was %d)",
            product_id, quantity, available,
        )

    except (NotFoundError, InsufficientStockError):
        raise
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"inventory_repository.decrement_stock "
                f"product_id={product_id} quantity={quantity}: {exc}"
            )
        ) from exc


def increment_stock(
    conn: PooledMySQLConnection,
    product_id: int,
    quantity: int,
) -> None:
    """Increment quantity_on_hand for one product (order cancellation reversal).

    Parameters
    ----------
    conn       : Pooled connection — part of an open transaction.
    product_id : FK to products / inventory.
    quantity   : Units to add back to stock (> 0).

    Raises
    ------
    NotFoundError : No inventory row exists for this product.
    DatabaseError : Unexpected MySQL error.
    """
    sql = """
        UPDATE inventory
        SET    quantity_on_hand = quantity_on_hand + %s
        WHERE  product_id = %s
    """

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (quantity, product_id))
        rows_affected: int = cursor.rowcount
        cursor.close()
    except MySQLError as exc:
        raise DatabaseError(
            internal_detail=(
                f"inventory_repository.increment_stock "
                f"product_id={product_id} quantity={quantity}: {exc}"
            )
        ) from exc

    if rows_affected == 0:
        raise NotFoundError("inventory", product_id)

    logger.debug(
        "inventory_repository.increment_stock: product_id=%d +%d",
        product_id, quantity,
    )
