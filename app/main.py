from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.core.config import settings
from app.core.database import Base, engine, get_db
from app.core.logging import configure_logging, get_logger
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.routers import auth, dashboard, tickets, users
from app.routers import settings as settings_routes

configure_logging()
logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.AUTO_CREATE_TABLES:
        logger.warning("auto_create_tables_enabled", hint="use `alembic upgrade head` outside local dev")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    logger.info("startup", environment=settings.ENVIRONMENT, docs_enabled=settings.ENABLE_DOCS)
    yield
    await engine.dispose()
    logger.info("shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version="2.2.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Middleware order: the LAST one added is the OUTERMOST, so it sees every request first.
if settings.allowed_hosts_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)
if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,  # we use Bearer tokens, not cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "X-Total-Count"],
        max_age=600,
    )
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tickets.router)
app.include_router(dashboard.router)
app.include_router(settings_routes.router)
app.include_router(settings_routes.public)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def web_ui() -> FileResponse:
    """The web interface (single-page app in app/static)."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["system"], include_in_schema=False)
@app.get("/health/live", tags=["system"])
async def live() -> dict[str, str]:
    """Liveness: the process is up (used by Docker/Kubernetes health checks)."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["system"])
async def ready(db: AsyncSession = Depends(get_db)):
    """Readiness: the database is reachable."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness_check_failed")
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    return {"status": "ok", "database": "up"}
