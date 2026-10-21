import time
from hashlib import sha256
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import Settings

logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        await logger.ainfo(
            "request_complete",
            method=request.method,
            route=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response


class RequestProtectionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length", "0")
        try:
            request_bytes = int(content_length)
        except ValueError:
            request_bytes = 0
        if request_bytes > self.settings.max_request_bytes:
            return JSONResponse(
                {
                    "type": "about:blank",
                    "title": "Payload Too Large",
                    "status": 413,
                    "detail": "Request body exceeds the configured limit",
                },
                status_code=413,
                media_type="application/problem+json",
            )
        if self.settings.rate_limit_enabled and request.method in {"POST", "PATCH", "DELETE"}:
            client = request.client.host if request.client else "unknown"
            subject = request.headers.get("authorization", client)
            identity = sha256(subject.encode()).hexdigest()[:24]
            minute = int(time.time() // 60)
            key = f"oms:rate:{identity}:{request.url.path}:{minute}"
            limit = (
                self.settings.payment_rate_limit_per_minute
                if "/payments" in request.url.path
                else self.settings.rate_limit_requests_per_minute
            )
            try:
                count = await self.redis.incr(key)
                if count == 1:
                    await self.redis.expire(key, 70)
                if count > limit:
                    return JSONResponse(
                        {
                            "type": "about:blank",
                            "title": "Too Many Requests",
                            "status": 429,
                            "detail": "Rate limit exceeded",
                        },
                        status_code=429,
                        headers={"Retry-After": "60"},
                        media_type="application/problem+json",
                    )
            except RedisError:
                await logger.awarning("rate_limit_store_unavailable")
        return await call_next(request)


def register_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(RequestProtectionMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
