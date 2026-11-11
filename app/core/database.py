from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Deterministic constraint/index names: required for reliable Alembic autogenerate & downgrades.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all ORM models (SQLAlchemy 2.0 style)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine_kwargs: dict = {"echo": settings.DEBUG}
if settings.DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

# expire_on_commit=False avoids lazy-load (MissingGreenlet) errors in async code
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
