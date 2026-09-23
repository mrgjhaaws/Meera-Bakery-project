"""
utils/exceptions.py
===================
Custom exception classes and FastAPI exception handlers for the Meera Bakery API.

Design rules
------------
- Raw MySQL error messages are NEVER returned to the client (they may contain
  table/column names, query fragments, or other internal details).
- Every exception maps to a consistent JSON response shape:
      { "error": "ERROR_CODE", "message": "Human-readable text.", "detail": null }
- Service and repository layers raise these custom exceptions; the handlers
  registered in main.py convert them to HTTPResponses.

Exception hierarchy
-------------------
    MeeraBakeryError          (base — all custom exceptions inherit from this)
    ├── NotFoundError         → HTTP 404
    ├── ConflictError         → HTTP 409  (duplicate unique key, FK violation)
    ├── BusinessRuleError     → HTTP 409  (invalid status transition, bad discount)
    ├── InsufficientStockError→ HTTP 409  (stock check failed before order confirm)
    └── DatabaseError         → HTTP 500  (unexpected DB failure, logged internally)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# =============================================================================
# Exception classes
# =============================================================================

class MeeraBakeryError(Exception):
    """Base class for all application-level exceptions."""

    def __init__(
        self,
        error_code: str,
        message: str,
        detail: Any = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.detail = detail
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }


class NotFoundError(MeeraBakeryError):
    """Raised when a requested resource does not exist.

    Maps to HTTP 404.

    Example
    -------
        raise NotFoundError("product", 99)
        # → {"error": "RESOURCE_NOT_FOUND", "message": "product with id 99 not found."}
    """

    def __init__(self, resource: str, identifier: Any) -> None:
        super().__init__(
            error_code="RESOURCE_NOT_FOUND",
            message=f"{resource} with id {identifier} not found.",
        )


class ConflictError(MeeraBakeryError):
    """Raised for unique-key violations or FK conflicts.

    Maps to HTTP 409.

    Example
    -------
        raise ConflictError("email", "meera@example.com already registered.")
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(
            error_code="CONFLICT",
            message=message,
            detail={"field": field},
        )


class BusinessRuleError(MeeraBakeryError):
    """Raised when application business logic rejects an operation.

    Maps to HTTP 409.

    Examples
    --------
        raise BusinessRuleError(
            "INVALID_STATUS_TRANSITION",
            "Cannot move order from 'delivered' to 'confirmed'.",
            detail={"current_status": "delivered", "requested_status": "confirmed"},
        )

        raise BusinessRuleError(
            "INVALID_DISCOUNT",
            "Cannot apply both flat and percentage discount simultaneously.",
        )
    """

    def __init__(self, error_code: str, message: str, detail: Any = None) -> None:
        super().__init__(error_code=error_code, message=message, detail=detail)


class InsufficientStockError(MeeraBakeryError):
    """Raised when an order confirmation would push stock below zero.

    Maps to HTTP 409.

    Example
    -------
        raise InsufficientStockError(
            product_id=7,
            product_name="Butter Croissant",
            requested=5,
            available=3,
        )
    """

    def __init__(
        self,
        product_id: int,
        product_name: str,
        requested: int,
        available: int,
    ) -> None:
        super().__init__(
            error_code="INSUFFICIENT_STOCK",
            message=(
                f"Not enough stock for '{product_name}' (id={product_id}). "
                f"Requested: {requested}, available: {available}."
            ),
            detail={
                "product_id": product_id,
                "product_name": product_name,
                "requested": requested,
                "available": available,
            },
        )


class DatabaseError(MeeraBakeryError):
    """Raised when an unexpected database error occurs.

    Maps to HTTP 500. The raw MySQL error is logged internally but a
    sanitised message is returned to the client.

    Example
    -------
        except MySQLError as exc:
            raise DatabaseError(internal_detail=str(exc)) from exc
    """

    def __init__(self, internal_detail: str = "") -> None:
        # Log the raw detail internally; never expose it to the caller
        if internal_detail:
            logger.error("Internal database error: %s", internal_detail)
        super().__init__(
            error_code="DATABASE_ERROR",
            message="An unexpected database error occurred. Please try again later.",
        )


# =============================================================================
# FastAPI exception handlers
# =============================================================================

def _json_error(status_code: int, exc: MeeraBakeryError) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=exc.to_dict())


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI application.

    Call this once in main.py after creating the FastAPI instance.
    """

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return _json_error(404, exc)

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return _json_error(409, exc)

    @app.exception_handler(BusinessRuleError)
    async def business_rule_handler(
        request: Request, exc: BusinessRuleError
    ) -> JSONResponse:
        return _json_error(409, exc)

    @app.exception_handler(InsufficientStockError)
    async def insufficient_stock_handler(
        request: Request, exc: InsufficientStockError
    ) -> JSONResponse:
        return _json_error(409, exc)

    @app.exception_handler(DatabaseError)
    async def database_error_handler(
        request: Request, exc: DatabaseError
    ) -> JSONResponse:
        return _json_error(500, exc)

    @app.exception_handler(MeeraBakeryError)
    async def generic_app_error_handler(
        request: Request, exc: MeeraBakeryError
    ) -> JSONResponse:
        # Catch-all for any subclass not handled above
        logger.error(
            "Unhandled MeeraBakeryError: code=%s msg=%s",
            exc.error_code,
            exc.message,
        )
        return _json_error(500, exc)
