from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Ticket, TicketEvent, TicketPriority, TicketStatus, User, UserRole
from app.models.base import utcnow
from app.schemas.ticket import CommentCreate, TicketCreate, TicketUpdate
from app.services import notification_service, settings_service

# Which fields each role may modify through PATCH /tickets/{id}
AGENT_FIELDS = {"status", "priority"}

# Status workflow: Open -> In Progress -> Resolved -> Closed, with controlled ways back.
# Closed is final except that an admin may reopen it. Open -> Resolved must go through In Progress.
TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.IN_PROGRESS: {TicketStatus.OPEN, TicketStatus.RESOLVED, TicketStatus.CLOSED},
    TicketStatus.RESOLVED: {TicketStatus.IN_PROGRESS, TicketStatus.OPEN, TicketStatus.CLOSED},
    TicketStatus.CLOSED: {TicketStatus.OPEN},
}


def _log(db: AsyncSession, ticket_id: int, actor: User | None, event: str, detail: str | None = None) -> None:
    db.add(TicketEvent(ticket_id=ticket_id, actor_id=actor.id if actor else None, event=event, detail=detail))


def is_overdue(ticket: Ticket) -> bool:
    return (
        ticket.due_at is not None
        and ticket.status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS)
        and _as_utc(ticket.due_at) < utcnow()
    )


async def _sla_hours(db: AsyncSession, priority: TicketPriority) -> int:
    # clamped so a bad stored value can never overflow the date arithmetic
    hours = await settings_service.get_int(db, f"sla_hours_{priority.value}")
    return min(max(hours, 0), settings_service.SLA_MAX_HOURS)


async def _least_loaded_agent(db: AsyncSession) -> User | None:
    active = and_(Ticket.assignee_id == User.id, Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]))
    stmt = (
        select(User)
        .outerjoin(Ticket, active)
        .where(User.role == UserRole.AGENT, User.is_active.is_(True))
        .group_by(User.id)
        .order_by(func.count(Ticket.id), User.id)
        .limit(1)
    )
    return await db.scalar(stmt)


async def list_events(db: AsyncSession, ticket: Ticket) -> list[TicketEvent]:
    return list(
        await db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id).order_by(TicketEvent.id))
    )


def _employee_may(current: TicketStatus, new: TicketStatus) -> bool:
    return new == TicketStatus.CLOSED or (current == TicketStatus.RESOLVED and new == TicketStatus.OPEN)


def allowed_next_statuses(ticket: Ticket, user: User) -> list[TicketStatus]:
    """Statuses this user may move the ticket to right now (workflow + role rules)."""
    if ticket.status == TicketStatus.CLOSED and user.role != UserRole.ADMIN:
        return []
    nxt = TRANSITIONS[ticket.status]
    if user.role == UserRole.EMPLOYEE:
        nxt = {s for s in nxt if _employee_may(ticket.status, s)}
    return [s for s in TicketStatus if s in nxt]


def _forbidden(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, msg)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_ticket_or_404(db: AsyncSession, ticket_id: int, user: User) -> Ticket:
    ticket = await db.get(Ticket, ticket_id)
    # Employees get 404 (not 403) for other people's tickets so IDs don't leak.
    if ticket is None or (user.role == UserRole.EMPLOYEE and ticket.creator_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return ticket


async def create_ticket(db: AsyncSession, user: User, data: TicketCreate) -> Ticket:
    if user.role == UserRole.EMPLOYEE:
        limit = await settings_service.get_int(db, "max_open_tickets_per_employee")
        active = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.creator_id == user.id, Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS])
            )
        )
        if (active or 0) >= limit:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Open ticket limit reached ({limit}). Close or resolve one first."
            )
    due = utcnow() + timedelta(hours=await _sla_hours(db, data.priority))
    ticket = Ticket(
        title=data.title, description=data.description, priority=data.priority, creator_id=user.id, due_at=due
    )
    db.add(ticket)
    await db.flush()
    _log(db, ticket.id, user, "created", f"priority {data.priority.value}")
    agent = await _least_loaded_agent(db) if await settings_service.get_bool(db, "auto_assign_on_create") else None
    if agent:
        ticket.assignee_id, ticket.status = agent.id, TicketStatus.IN_PROGRESS
        _log(db, ticket.id, None, "auto_assigned", f"to #{agent.id}")
    await db.commit()
    await db.refresh(ticket)
    if agent:
        await notification_service.notify(agent.email, f"Ticket #{ticket.id} assigned to you", ticket.title)
    return ticket


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def list_tickets(
    db: AsyncSession,
    user: User,
    *,
    status_: TicketStatus | None,
    priority: TicketPriority | None,
    assignee_id: int | None,
    search: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    skip: int,
    limit: int,
    after_id: int | None = None,
) -> tuple[list[Ticket], int, bool]:
    """Returns (items, total matching filters, has_next). Newest first (id DESC).

    Offset mode uses `skip`; keyset mode uses `after_id` (items with id < after_id), which stays
    fast and stable on deep pages and while new tickets are being created.
    """
    conditions = []
    if user.role == UserRole.EMPLOYEE:
        conditions.append(Ticket.creator_id == user.id)
    if status_ is not None:
        conditions.append(Ticket.status == status_)
    if priority is not None:
        conditions.append(Ticket.priority == priority)
    if assignee_id is not None:
        conditions.append(Ticket.assignee_id == assignee_id)
    if created_from is not None:
        conditions.append(Ticket.created_at >= _as_utc(created_from))
    if created_to is not None:
        conditions.append(Ticket.created_at <= _as_utc(created_to))
    if search:
        pattern = f"%{_escape_like(search.strip())}%"
        conditions.append(or_(Ticket.title.ilike(pattern, escape="\\"), Ticket.description.ilike(pattern, escape="\\")))

    total = await db.scalar(select(func.count(Ticket.id)).where(*conditions)) or 0

    page_conditions = list(conditions)
    if after_id is not None:
        page_conditions.append(Ticket.id < after_id)
    stmt = select(Ticket).where(*page_conditions).order_by(Ticket.id.desc()).limit(limit + 1)  # +1 detects has_next
    if after_id is None:
        stmt = stmt.offset(skip)
    rows = list(await db.scalars(stmt))
    has_next = len(rows) > limit
    return rows[:limit], total, has_next


def _apply_status(ticket: Ticket, new_status: TicketStatus) -> None:
    ticket.status = new_status
    if new_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        ticket.resolved_at = ticket.resolved_at or utcnow()
    else:  # reopened / back in progress
        ticket.resolved_at = None


async def update_ticket(db: AsyncSession, ticket: Ticket, user: User, data: TicketUpdate) -> Ticket:
    changes = data.model_dump(exclude_unset=True)

    if user.role == UserRole.EMPLOYEE:
        if ticket.creator_id != user.id:  # defensive; get_ticket_or_404 already hides these
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        if ticket.status == TicketStatus.CLOSED:
            raise _forbidden("Closed tickets cannot be modified")
    elif user.role == UserRole.AGENT:
        extra = changes.keys() - AGENT_FIELDS
        if extra:
            raise _forbidden(f"Agents may only update: {', '.join(sorted(AGENT_FIELDS))}")
    # Admin: unrestricted fields, but status changes still follow the workflow

    new_status = changes.pop("status", None)
    old_status, old_priority = ticket.status, ticket.priority
    if new_status is not None and new_status != old_status:
        if user.role == UserRole.EMPLOYEE and not _employee_may(old_status, new_status):
            raise _forbidden("Employees may only close their ticket or reopen a resolved one")
        if old_status == TicketStatus.CLOSED and user.role != UserRole.ADMIN:
            raise _forbidden("Only an admin can reopen a closed ticket")
        if new_status not in TRANSITIONS[old_status]:
            allowed = ", ".join(sorted(x.value for x in TRANSITIONS[old_status]))
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid status change {old_status.value} -> {new_status.value}. Allowed: {allowed}",
            )

    text_fields = [f for f in ("title", "description") if f in changes and changes[f] != getattr(ticket, f)]
    for field, value in changes.items():
        setattr(ticket, field, value)
    if text_fields:
        _log(db, ticket.id, user, "edited", ", ".join(text_fields))
    if ticket.priority != old_priority:
        _log(db, ticket.id, user, "priority_changed", f"{old_priority.value} -> {ticket.priority.value}")
        if ticket.status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS):  # re-base the SLA on the new priority
            ticket.due_at = _as_utc(ticket.created_at) + timedelta(hours=await _sla_hours(db, ticket.priority))
    status_changed = new_status is not None and new_status != old_status
    if status_changed:
        _apply_status(ticket, new_status)
        _log(db, ticket.id, user, "status_changed", f"{old_status.value} -> {new_status.value}")

    await db.commit()
    await db.refresh(ticket)
    if status_changed and user.id != ticket.creator_id:
        creator = await db.get(User, ticket.creator_id)
        if creator:
            await notification_service.notify(
                creator.email, f"Ticket #{ticket.id} is now {ticket.status.value}", ticket.title
            )
    return ticket


async def assign_ticket(db: AsyncSession, ticket: Ticket, acting: User, assignee_id: int | None) -> Ticket:
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot assign a closed ticket")
    target = acting if assignee_id is None else await db.get(User, assignee_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignee not found")
    if not target.is_active or target.role not in (UserRole.AGENT, UserRole.ADMIN):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Assignee must be an active agent or admin")
    ticket.assignee_id = target.id
    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.IN_PROGRESS
    _log(db, ticket.id, acting, "assigned", f"to #{target.id}")
    await db.commit()
    await db.refresh(ticket)
    if target.id != acting.id:
        await notification_service.notify(target.email, f"Ticket #{ticket.id} assigned to you", ticket.title)
    return ticket


async def delete_ticket(db: AsyncSession, ticket: Ticket) -> None:
    await db.execute(delete(Comment).where(Comment.ticket_id == ticket.id))
    await db.execute(delete(TicketEvent).where(TicketEvent.ticket_id == ticket.id))
    await db.execute(delete(Ticket).where(Ticket.id == ticket.id))
    await db.commit()


async def add_comment(db: AsyncSession, ticket: Ticket, user: User, data: CommentCreate) -> Comment:
    if user.role == UserRole.EMPLOYEE:
        if data.is_internal:
            raise _forbidden("Employees cannot post internal notes")
        if ticket.status == TicketStatus.CLOSED:
            raise _forbidden("Cannot comment on a closed ticket")
    comment = Comment(ticket_id=ticket.id, author_id=user.id, body=data.body, is_internal=data.is_internal)
    db.add(comment)
    if not data.is_internal:
        _log(db, ticket.id, user, "commented")
    await db.commit()
    await db.refresh(comment)
    return comment


async def list_comments(db: AsyncSession, ticket: Ticket, user: User) -> list[Comment]:
    stmt = select(Comment).where(Comment.ticket_id == ticket.id).order_by(Comment.created_at, Comment.id)
    if user.role == UserRole.EMPLOYEE:
        stmt = stmt.where(Comment.is_internal.is_(False))
    return list(await db.scalars(stmt))
