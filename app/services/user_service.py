import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.models import Comment, LoginAttempt, Ticket, TicketEvent, TicketStatus, User, UserRole
from app.models.base import utcnow
from app.schemas.user import UserCreate, UserUpdate


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.lower()))


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    if await get_by_email(db, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=data.email.lower(),
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


logger = get_logger("app.users")

# One generic failure for every way a login can go wrong (unknown email, wrong password, throttled),
# so the response never reveals which accounts exist.
INVALID_LOGIN = "Incorrect email or password"


ALL_IPS = "*"  # pseudo-IP of the per-account row that counts failures from every address together


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


@lru_cache
def _dummy_hash() -> str:
    return hash_password("not-a-real-password")


async def clear_login_failures(db: AsyncSession, email: str) -> None:
    """Forget every failed attempt for this email (all IPs). Does not commit."""
    await db.execute(
        delete(LoginAttempt).where(LoginAttempt.email_hash == _email_hash(email)),
        execution_options={"synchronize_session": False},
    )


def _account_window() -> timedelta:
    return timedelta(minutes=settings.ACCOUNT_FAILURE_WINDOW_MINUTES)


async def _account_row(db: AsyncSession, key: str) -> LoginAttempt | None:
    return await db.get(LoginAttempt, (key, ALL_IPS))


async def _count_account_failure(db: AsyncSession, key: str, now: datetime) -> None:
    """Counts failures for this email from every IP. It never locks the account (that would let anyone lock the
    owner out); it only raises an alert and slows later attempts, see authenticate()."""
    if settings.ACCOUNT_FAILURE_ALERT <= 0:
        return
    row = await _account_row(db, key)
    if row is None:
        row = LoginAttempt(email_hash=key, ip_address=ALL_IPS, failures=0)
        db.add(row)
    elif _aware(row.updated_at) < now - _account_window():
        row.failures = 0
    row.failures += 1
    row.updated_at = now
    if row.failures == settings.ACCOUNT_FAILURE_ALERT:  # once per window, not on every later failure
        logger.warning("account_under_attack", email_hash=key[:12], failures=row.failures)


async def _record_failure(db: AsyncSession, attempt: LoginAttempt | None, key: str, ip: str, now: datetime) -> None:
    window = timedelta(minutes=settings.LOCKOUT_MINUTES)
    if attempt is None:
        attempt = LoginAttempt(email_hash=key, ip_address=ip, failures=0)
        db.add(attempt)
    elif _aware(attempt.updated_at) < now - window:
        attempt.failures, attempt.locked_until = 0, None  # old failures no longer count
    attempt.failures += 1
    attempt.updated_at = now
    if attempt.failures >= settings.LOGIN_MAX_ATTEMPTS:
        attempt.locked_until, attempt.failures = now + window, 0
        logger.warning("login_throttled", minutes=settings.LOCKOUT_MINUTES)
    await _count_account_failure(db, key, now)
    await db.flush()
    # prune rows whose window has passed (their lock, if any, has expired too) so the table cannot grow unbounded
    per_ip_expired = (LoginAttempt.ip_address != ALL_IPS) & (LoginAttempt.updated_at < now - window)
    account_expired = (LoginAttempt.ip_address == ALL_IPS) & (LoginAttempt.updated_at < now - _account_window())
    await db.execute(
        delete(LoginAttempt).where(per_ip_expired | account_expired), execution_options={"synchronize_session": False}
    )
    await db.commit()


async def authenticate(db: AsyncSession, email: str, password: str, ip: str) -> User | None:
    """Returns the user, or None for any failure (unknown email, wrong password or throttled).

    After LOGIN_MAX_ATTEMPTS failures from one IP against one email, that pair is refused for LOCKOUT_MINUTES.
    Other IPs (including the real owner) are unaffected, and unknown emails are throttled the same way.
    """
    key, now = _email_hash(email), utcnow()
    attempt = await db.get(LoginAttempt, (key, ip))
    if attempt and attempt.locked_until and _aware(attempt.locked_until) > now:
        return None
    account = await _account_row(db, key) if settings.ACCOUNT_FAILURE_ALERT > 0 else None
    if (
        account
        and account.failures >= settings.ACCOUNT_FAILURE_ALERT
        and _aware(account.updated_at) >= now - _account_window()
    ):
        await asyncio.sleep(settings.ACCOUNT_FAILURE_DELAY_SECONDS)  # slows guessing spread over many IPs
    user = await get_by_email(db, email)
    # Always run bcrypt, even for unknown emails, so response time does not reveal which accounts exist.
    password_ok = verify_password(password, user.hashed_password if user else _dummy_hash())
    if user is None or not password_ok:
        await _record_failure(db, attempt, key, ip, now)
        return None
    if attempt:
        await db.delete(attempt)
        await db.commit()
    return user


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if current == new:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the current one")
    user.hashed_password = hash_password(new)
    user.token_version += 1  # signs out every other session
    await clear_login_failures(db, user.email)
    await db.commit()
    logger.info("password_changed", user_id=user.id)


async def list_users(db: AsyncSession, skip: int, limit: int) -> tuple[list[User], int]:
    total = await db.scalar(select(func.count(User.id))) or 0
    rows = await db.scalars(select(User).order_by(User.id).offset(skip).limit(limit))
    return list(rows), total


async def get_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def release_tickets(db: AsyncSession, user: User, acting: User, reason: str) -> int:
    """Unassign the user's Open / In Progress tickets (In Progress ones go back to Open). Does not commit.

    Resolved and Closed tickets keep their assignee as a record of who handled them.
    """
    tickets = await db.scalars(
        select(Ticket).where(
            Ticket.assignee_id == user.id, Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS])
        )
    )
    count = 0
    for ticket in tickets:
        ticket.assignee_id = None
        if ticket.status == TicketStatus.IN_PROGRESS:
            ticket.status = TicketStatus.OPEN
        db.add(TicketEvent(ticket_id=ticket.id, actor_id=acting.id, event="unassigned", detail=reason))
        count += 1
    return count


async def update_user(db: AsyncSession, user: User, data: UserUpdate, acting: User) -> User:
    changes = data.model_dump(exclude_unset=True)
    if changes.pop("unlock", None):
        await clear_login_failures(db, user.email)
    if user.id == acting.id and ({"role", "is_active"} & changes.keys()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admins cannot change their own role or active state")
    if "password" in changes:
        user.hashed_password = hash_password(changes.pop("password"))
        user.token_version += 1
    if changes.get("role") == UserRole.EMPLOYEE and user.role != UserRole.EMPLOYEE:
        # an employee can neither open nor work on tickets assigned to them, so hand those back to the queue
        await release_tickets(db, user, acting, "assignee is no longer an agent")
    if changes.get("is_active") is False and user.is_active:
        # a deactivated account cannot sign in, so its open work would otherwise sit untouched
        await release_tickets(db, user, acting, "assignee account was deactivated")
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User, acting: User) -> None:
    if user.id == acting.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete yourself")
    created = await db.scalar(select(func.count(Ticket.id)).where(Ticket.creator_id == user.id))
    commented = await db.scalar(select(func.count(Comment.id)).where(Comment.author_id == user.id))
    if created or commented:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "User has tickets or comments; deactivate the account instead (PATCH is_active=false)",
        )
    await release_tickets(db, user, acting, "assignee account was deleted")
    await db.execute(update(Ticket).where(Ticket.assignee_id == user.id).values(assignee_id=None))  # resolved/closed
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
