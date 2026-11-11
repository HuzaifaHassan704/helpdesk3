import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, DbSession, StaffUser, require_roles
from app.core.pagination import decode_cursor, encode_cursor, total_pages
from app.core.rate_limit import limiter
from app.models import TicketPriority, TicketStatus, User, UserRole
from app.schemas.ticket import (
    CommentCreate,
    CommentOut,
    EventOut,
    TicketAssign,
    TicketCreate,
    TicketList,
    TicketOut,
    TicketUpdate,
)
from app.services import ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])

# Per spec: only Employees and Admins open tickets.
TicketCreator = Annotated[User, Depends(require_roles(UserRole.EMPLOYEE, UserRole.ADMIN))]


def _out(ticket, user: User) -> TicketOut:
    out = TicketOut.model_validate(ticket)
    out.allowed_statuses = ticket_service.allowed_next_statuses(ticket, user)
    out.is_overdue = ticket_service.is_overdue(ticket)
    return out


@router.post("/", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: settings.RATE_LIMIT_CREATE_TICKET)
async def create_ticket(request: Request, payload: TicketCreate, db: DbSession, user: TicketCreator):
    return _out(await ticket_service.create_ticket(db, user, payload), user)


@router.get("/", response_model=TicketList)
async def list_tickets(
    response: Response,
    db: DbSession,
    user: CurrentUser,
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: TicketPriority | None = None,
    assignee_id: int | None = None,
    search: Annotated[
        str | None, Query(min_length=1, max_length=100, description="Matches title or description")
    ] = None,
    created_from: Annotated[datetime | None, Query(description="Created at or after (ISO 8601)")] = None,
    created_to: Annotated[datetime | None, Query(description="Created at or before (ISO 8601)")] = None,
    skip: Annotated[int, Query(ge=0, description="Offset pagination")] = 0,
    page: Annotated[int | None, Query(ge=1, description="1-based page number (overrides skip)")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size")] = 20,
    cursor: Annotated[
        str | None, Query(description="Keyset pagination: `next_cursor` from a previous response")
    ] = None,
):
    """Newest tickets first. Use `skip`/`page` for offset pagination or `cursor` for keyset pagination."""
    if cursor is not None and (skip or page):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use either cursor or skip/page, not both")
    after_id = decode_cursor(cursor) if cursor is not None else None
    if page is not None:
        skip = (page - 1) * limit

    items, total, has_next = await ticket_service.list_tickets(
        db,
        user,
        status_=status_filter,
        priority=priority,
        assignee_id=assignee_id,
        search=search,
        created_from=created_from,
        created_to=created_to,
        skip=skip,
        limit=limit,
        after_id=after_id,
    )
    response.headers["X-Total-Count"] = str(total)
    keyset = after_id is not None
    return TicketList(
        items=[_out(t, user) for t in items],
        total=total,
        skip=0 if keyset else skip,
        limit=limit,
        page=None if keyset else skip // limit + 1,
        pages=total_pages(total, limit),
        has_next=has_next,
        has_prev=True if keyset else skip > 0,
        next_cursor=encode_cursor(items[-1].id) if has_next and items else None,
    )


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text  # blocks spreadsheet formula injection


@router.get("/export.csv")
async def export_tickets(
    db: DbSession,
    user: StaffUser,
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: TicketPriority | None = None,
    assignee_id: int | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
):
    """CSV of the filtered tickets (newest first, max 10,000 rows). Agents and admins only."""
    items, _, _ = await ticket_service.list_tickets(
        db, user, status_=status_filter, priority=priority, assignee_id=assignee_id, search=search,
        created_from=created_from, created_to=created_to, skip=0, limit=10_000,
    )  # fmt: skip
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "creator_id",
            "assignee_id",
            "created_at",
            "due_at",
            "resolved_at",
            "overdue",
        ]
    )
    for t in items:
        row = [
            t.id,
            t.title,
            t.description,
            t.status.value,
            t.priority.value,
            t.creator_id,
            t.assignee_id,
            t.created_at,
            t.due_at,
            t.resolved_at,
            ticket_service.is_overdue(t),
        ]
        writer.writerow([_csv_safe(v) for v in row])
    return Response(
        buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="tickets.csv"'}
    )


@router.get("/{ticket_id}/history", response_model=list[EventOut])
async def ticket_history(ticket_id: int, db: DbSession, user: CurrentUser):
    ticket = await ticket_service.get_ticket_or_404(db, ticket_id, user)
    return await ticket_service.list_events(db, ticket)


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: int, db: DbSession, user: CurrentUser):
    return _out(await ticket_service.get_ticket_or_404(db, ticket_id, user), user)


@router.patch("/{ticket_id}", response_model=TicketOut)
async def update_ticket(ticket_id: int, payload: TicketUpdate, db: DbSession, user: CurrentUser):
    ticket = await ticket_service.get_ticket_or_404(db, ticket_id, user)
    return _out(await ticket_service.update_ticket(db, ticket, user, payload), user)


@router.post("/{ticket_id}/assign", response_model=TicketOut)
async def assign_ticket(ticket_id: int, payload: TicketAssign, db: DbSession, user: StaffUser):
    """Agents/Admins assign a ticket to themselves (empty body) or to another agent/admin."""
    ticket = await ticket_service.get_ticket_or_404(db, ticket_id, user)
    return _out(await ticket_service.assign_ticket(db, ticket, user, payload.assignee_id), user)


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(ticket_id: int, db: DbSession, user: AdminUser):
    ticket = await ticket_service.get_ticket_or_404(db, ticket_id, user)
    await ticket_service.delete_ticket(db, ticket)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{ticket_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(ticket_id: int, payload: CommentCreate, db: DbSession, user: CurrentUser):
    ticket = await ticket_service.get_ticket_or_404(db, ticket_id, user)
    return await ticket_service.add_comment(db, ticket, user, payload)


@router.get("/{ticket_id}/comments", response_model=list[CommentOut])
async def list_comments(ticket_id: int, db: DbSession, user: CurrentUser):
    ticket = await ticket_service.get_ticket_or_404(db, ticket_id, user)
    return await ticket_service.list_comments(db, ticket, user)
