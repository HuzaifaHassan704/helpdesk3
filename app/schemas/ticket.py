from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TicketPriority, TicketStatus


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1)
    priority: TicketPriority = TicketPriority.MEDIUM


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None

    @field_validator("title", "description", "status", "priority")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v


class TicketAssign(BaseModel):
    # Omit to assign the ticket to yourself.
    assignee_id: int | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    creator_id: int
    assignee_id: int | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    allowed_statuses: list[TicketStatus] = []  # next statuses this user may set
    due_at: datetime | None = None
    is_overdue: bool = False


class TicketList(BaseModel):
    items: list[TicketOut]
    total: int  # all tickets matching the filters
    skip: int
    limit: int
    page: int | None  # 1-based; null in cursor mode
    pages: int  # total number of pages at this page size
    has_next: bool
    has_prev: bool
    next_cursor: str | None  # pass as ?cursor= to continue with keyset pagination


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    actor_id: int | None
    event: str
    detail: str | None
    created_at: datetime


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    is_internal: bool = False


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author_id: int
    body: str
    is_internal: bool
    created_at: datetime
