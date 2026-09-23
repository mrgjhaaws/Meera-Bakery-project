"""
main.py
=======
FastAPI application factory for the Meera Bakery API.

Responsibilities
----------------
- Create the FastAPI app with metadata (title, version, docs URLs).
- Register the lifespan context manager (pool init on startup,
  pool release on shutdown).
- Register all custom exception handlers.
- Register CORS middleware.
- Mount all API routers (Phase 1: health only; phases 2–6 add more).
- Expose the /health endpoint for ALB health checks.

Running locally
---------------
    cd C:\\MeeraBakery\\app
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Interactive docs
----------------
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""

from __future__ import annotations

import logging
import logging.config
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from db.connection import close_pool, init_pool
from utils.exceptions import register_exception_handlers


# =============================================================================
# Logging setup
# =============================================================================

def _configure_logging() -> None:
    """Configure application logging.

    - Local  : human-readable text to stdout (easier to read in terminal)
    - Production: same format but level controlled by LOG_LEVEL env var
    """
    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        if settings.is_local
        else "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Quieten noisy libraries
    logging.getLogger("mysql.connector").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


_configure_logging()
logger = logging.getLogger(__name__)


# =============================================================================
# Lifespan — startup / shutdown
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan events.

    Startup  : initialise the database connection pool.
    Shutdown : release all pooled connections cleanly.
    """
    # --- Startup -------------------------------------------------------------
    logger.info(
        "Meera Bakery API starting. env=%s log_level=%s",
        settings.app_env,
        settings.log_level,
    )
    init_pool()
    logger.info("Startup complete.")

    yield  # application runs here

    # --- Shutdown ------------------------------------------------------------
    logger.info("Meera Bakery API shutting down.")
    close_pool()
    logger.info("Shutdown complete.")


# =============================================================================
# Application factory
# =============================================================================

def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""

    app = FastAPI(
        title="Meera Bakery Online API",
        description=(
            "Backend API for the Meera Bakery Online learning project. "
            "Manages products, customers, orders, inventory, and reporting."
        ),
        version="1.0.0",
        # Docs available in all environments for this learning project.
        # In a real production system you might disable these:
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # --- CORS middleware ------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # --- Request timing middleware --------------------------------------------
    @app.middleware("http")
    async def add_request_timing(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Response-Time-Ms"] = str(duration_ms)
        logger.info(
            "%s %s → %d  (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # --- Exception handlers --------------------------------------------------
    register_exception_handlers(app)

    # --- Routers -------------------------------------------------------------
    # Phase 1: health (no prefix — ALB hits /health directly)
    app.include_router(_health_router(), prefix="")

    # Phase 2: read-only categories and products
    from routers import categories as categories_router
    from routers import products as products_router

    app.include_router(categories_router.router, prefix="/api/v1")
    app.include_router(products_router.router, prefix="/api/v1")

    # Phase 3: read-only customers and addresses
    from routers.customers import addresses_router, customers_router

    app.include_router(customers_router, prefix="/api/v1")
    app.include_router(addresses_router, prefix="/api/v1")

    # Phase 4: orders (with inventory side effects) and reporting
    from routers import orders as orders_router
    from routers import reports as reports_router

    app.include_router(orders_router.router, prefix="/api/v1")
    app.include_router(reports_router.router, prefix="/api/v1")

    return app


def _health_router():  # type: ignore[return]
    """Build and return the /health router.

    Kept inline in main.py because it is a single endpoint with no
    repository or service dependencies.
    """
    from fastapi import APIRouter  # local import to avoid circular issues

    router = APIRouter(tags=["Health"])

    @router.get(
        "/health",
        summary="Health check",
        description=(
            "Returns 200 OK when the application is running. "
            "Used by the AWS Application Load Balancer health check."
        ),
        response_description="Service status and metadata",
    )
    async def health_check() -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": "meera-bakery-api",
                "version": "1.0.0",
                "environment": settings.app_env,
            },
        )

    return router


# =============================================================================
# Application instance
# =============================================================================

# Uvicorn and other ASGI servers import `app` from this module.
app: FastAPI = create_app()
