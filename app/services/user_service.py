from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.models import Ticket, User
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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """Returns the user, None on bad credentials, or raises 423 while the account is locked."""
    user = await get_by_email(db, email)
    if user is None:
        return None
    now = utcnow()
    if user.locked_until and _aware(user.locked_until) > now:
        raise HTTPException(status.HTTP_423_LOCKED, "Account temporarily locked after too many failed attempts")
    if not verify_password(password, user.hashed_password):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
            user.failed_login_count = 0
            logger.warning("account_locked", user_id=user.id, minutes=settings.LOCKOUT_MINUTES)
        await db.commit()
        return None
    if user.failed_login_count or user.locked_until:
        user.failed_login_count, user.locked_until = 0, None
        await db.commit()
    return user


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if current == new:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the current one")
    user.hashed_password = hash_password(new)
    user.failed_login_count, user.locked_until = 0, None
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
        user.failed_login_count, user.locked_until = 0, None
    if user.id == acting.id and ({"role", "is_active"} & changes.keys()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admins cannot change their own role or active state")
    if "password" in changes:
        user.hashed_password = hash_password(changes.pop("password"))
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User, acting: User) -> None:
    if user.id == acting.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete yourself")
    created = await db.scalar(select(func.count(Ticket.id)).where(Ticket.creator_id == user.id))
    if created:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "User owns tickets; deactivate the account instead (PATCH is_active=false)",
        )
    await db.execute(update(Ticket).where(Ticket.assignee_id == user.id).values(assignee_id=None))
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
