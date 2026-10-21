
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import register_middleware
from app.core.telemetry import configure_telemetry
from app.database.connection import engine, get_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        description="Multi-warehouse order, inventory, payment, and fulfillment API.",
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    register_middleware(application, settings)
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_prefix)
    configure_telemetry(application, engine, settings)

    @application.get("/", tags=["General"])
    def root() -> dict[str, str]:
        return {"message": settings.app_name, "version": settings.app_version}

    @application.get("/live", tags=["Health"])
    def live() -> dict[str, str]:
        return {"status": "healthy"}

    @application.get("/health", tags=["Health"], include_in_schema=False)
    def health_compatibility() -> dict[str, str]:
        return {"status": "healthy"}

    @application.get("/ready", tags=["Health"])
    def ready(db: Session = Depends(get_db)) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
            if settings.rate_limit_enabled:
                Redis.from_url(settings.redis_url).ping()
        except Exception as exc:
            raise HTTPException(503, "A required dependency is unavailable") from exc
        return {"status": "ready", "database": "connected", "redis": "connected"}

    @application.get("/health/database", tags=["Health"], include_in_schema=False)
    def database_health_check(db: Session = Depends(get_db)) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
            return {"database": "connected"}
        except Exception as exc:
            raise HTTPException(503, "Database connection failed") from exc

    @application.get("/metrics", tags=["Operations"], include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return application


app = create_app()
