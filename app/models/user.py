from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]),
        default=UserRole.EMPLOYEE,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on every password change/reset; access tokens carry it, so older tokens stop working at once.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    created_tickets: Mapped[list["Ticket"]] = relationship(back_populates="creator", foreign_keys="Ticket.creator_id")
    assigned_tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="assignee", foreign_keys="Ticket.assignee_id"
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} {self.role}>"
