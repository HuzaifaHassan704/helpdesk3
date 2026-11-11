from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.ticket import Ticket
    from app.models.user import User


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    body: Mapped[str] = mapped_column(Text)
    # Agent-only notes hidden from the employee who opened the ticket.
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship()
