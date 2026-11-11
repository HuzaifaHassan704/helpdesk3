from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.rate_limit")

# Keyed by client IP. Behind a reverse proxy run uvicorn with --proxy-headers and set
# FORWARDED_ALLOW_IPS to the proxy's address so the real client IP is used.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    enabled=settings.RATE_LIMIT_ENABLED,
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    logger.warning("rate_limit_exceeded", limit=str(exc.detail))
    return JSONResponse(status_code=429, content={"detail": f"Rate limit exceeded: {exc.detail}"})
