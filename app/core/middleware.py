"""Pure-ASGI middleware (no BaseHTTPMiddleware: keeps contextvars intact and streams correctly)."""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")
_QUIET_PATHS = {"/health", "/health/live", "/health/ready"}

logger = structlog.get_logger("app.access")


class RequestContextMiddleware:
    """Generates/propagates X-Request-ID, binds it to every log line, and logs one summary per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        # Never trust the raw header: it ends up in logs and response headers.
        request_id = incoming if incoming and _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        client = scope.get("client")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope["method"],
            path=scope["path"],
            client_ip=client[0] if client else None,
        )
        scope.setdefault("state", {})["request_id"] = request_id

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error("request_failed", status_code=500, duration_ms=duration_ms, exc_info=True)
            raise
        else:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            if scope["path"] in _QUIET_PATHS:
                log = logger.debug
            elif status_code >= 500:
                log = logger.error
            elif status_code >= 400:
                log = logger.warning
            else:
                log = logger.info
            log("request_completed", status_code=status_code, duration_ms=duration_ms)
        finally:
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware:
    """Adds baseline security headers to every response (never overrides ones the app set)."""

    _DOC_PATHS = ("/docs", "/redoc")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.hsts = settings.ENVIRONMENT == "production"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_docs = scope["path"].startswith(self._DOC_PATHS)
        is_ui = scope["path"] == "/" or scope["path"].startswith("/static")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h.setdefault("X-Content-Type-Options", "nosniff")
                h.setdefault("X-Frame-Options", "DENY")
                h.setdefault("Referrer-Policy", "no-referrer")
                h.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
                h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                if self.hsts:
                    h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
                if is_ui:
                    # The web UI loads only its own files: no inline scripts, no third-party hosts.
                    h.setdefault(
                        "Content-Security-Policy",
                        "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
                    )
                elif not is_docs:
                    # Swagger UI loads scripts from a CDN, so the strict API policy skips the docs pages.
                    h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                    h.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_wrapper)
