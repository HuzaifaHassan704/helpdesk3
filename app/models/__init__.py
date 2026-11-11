# Import every model so Base.metadata (and Alembic) sees all tables.
from app.models.comment import Comment
from app.models.enums import TicketPriority, TicketStatus, UserRole
from app.models.setting import SystemSetting
from app.models.ticket import Ticket
from app.models.ticket_event import TicketEvent
from app.models.user import User

__all__ = ["TicketEvent", "SystemSetting", "Comment", "Ticket", "User", "UserRole", "TicketStatus", "TicketPriority"]
