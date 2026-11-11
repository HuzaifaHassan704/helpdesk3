from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import utcnow


class LoginAttempt(Base):
    """Failed-login counter for one (email, client IP) pair.

    Keyed per IP so a stranger cannot lock the real owner out of an account from their own address, and kept for
    unknown emails too so a locked account looks exactly like one that does not exist. The email is stored only
    as a SHA-256 hash.
    """

    __tablename__ = "login_attempts"

    email_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    ip_address: Mapped[str] = mapped_column(String(45), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
