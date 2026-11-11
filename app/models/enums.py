from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    AGENT = "agent"
    EMPLOYEE = "employee"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
