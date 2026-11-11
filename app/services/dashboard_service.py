from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket, TicketPriority, TicketStatus
from app.models.base import utcnow
from app.schemas.dashboard import DashboardStats


async def get_stats(db: AsyncSession) -> DashboardStats:
    total = await db.scalar(select(func.count(Ticket.id))) or 0

    by_status = {s.value: 0 for s in TicketStatus}
    for st, count in (await db.execute(select(Ticket.status, func.count()).group_by(Ticket.status))).all():
        by_status[st.value] = count

    by_priority = {p.value: 0 for p in TicketPriority}
    for pr, count in (await db.execute(select(Ticket.priority, func.count()).group_by(Ticket.priority))).all():
        by_priority[pr.value] = count

    # Computed in Python so it behaves identically on SQLite and PostgreSQL.
    rows = (
        await db.execute(select(Ticket.created_at, Ticket.resolved_at).where(Ticket.resolved_at.is_not(None)))
    ).all()
    avg_hours = None
    if rows:
        avg_hours = round(sum((r - c).total_seconds() for c, r in rows) / len(rows) / 3600, 4)

    overdue = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.due_at < utcnow(), Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS])
        )
    )
    return DashboardStats(
        overdue_tickets=overdue or 0,
        total_tickets=total,
        by_status=by_status,
        by_priority=by_priority,
        resolved_tickets=len(rows),
        avg_resolution_hours=avg_hours,
    )
