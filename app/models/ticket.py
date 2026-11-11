from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.enums import TicketPriority, TicketStatus

if TYPE_CHECKING:
    from app.models.comment import Comment
    from app.models.user import User


def _enum(cls, length: int = 20) -> Enum:
    # Stored as VARCHAR (native_enum=False): portable and easy to migrate.
    return Enum(cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e])


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        # dashboard group-bys and combined status/priority filters
        Index("ix_tickets_status_priority", "status", "priority"),
        # "my queue" (assignee + status) used by agents
        Index("ix_tickets_assignee_id_status", "assignee_id", "status"),
        # employee list view, newest first
        Index("ix_tickets_creator_id_created_at", "creator_id", "created_at"),
        # date-range filters and time-based reporting
        Index("ix_tickets_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))  # no btree index: ILIKE '%x%' cannot use it
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(_enum(TicketStatus), default=TicketStatus.OPEN, index=True)
    priority: Mapped[TicketPriority] = mapped_column(_enum(TicketPriority), default=TicketPriority.MEDIUM, index=True)

    # FK columns are indexed through the composite indexes below (creator_id/assignee_id are leading columns).
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Set when status moves to RESOLVED; powers "average resolution time" stats.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SLA deadline, derived from priority (settings sla_hours_*)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    creator: Mapped["User"] = relationship(back_populates="created_tickets", foreign_keys=[creator_id])
    assignee: Mapped["User | None"] = relationship(back_populates="assigned_tickets", foreign_keys=[assignee_id])
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="Comment.created_at"
    )

    def __repr__(self) -> str:
        return f"<Ticket {self.id} {self.status} {self.priority}>"
