import hashlib
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.models import Comment, LoginAttempt, Ticket, User
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
    await db.flush()
    # prune rows whose window has passed (their lock, if any, has expired too) so the table cannot grow unbounded
    await db.execute(
        delete(LoginAttempt).where(LoginAttempt.updated_at < now - window),
        execution_options={"synchronize_session": False},
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


async def update_user(db: AsyncSession, user: User, data: UserUpdate, acting: User) -> User:
    changes = data.model_dump(exclude_unset=True)
    if changes.pop("unlock", None):
        await clear_login_failures(db, user.email)
    if user.id == acting.id and ({"role", "is_active"} & changes.keys()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admins cannot change their own role or active state")
    if "password" in changes:
        user.hashed_password = hash_password(changes.pop("password"))
        user.token_version += 1
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
    await db.execute(update(Ticket).where(Ticket.assignee_id == user.id).values(assignee_id=None))
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
