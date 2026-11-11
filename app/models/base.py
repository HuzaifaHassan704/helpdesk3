from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    """created_at / updated_at maintained application-side (same behaviour on SQLite & PostgreSQL)."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
