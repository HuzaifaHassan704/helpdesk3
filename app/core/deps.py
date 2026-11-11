from typing import Annotated

import jwt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def _user_from_token(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _credentials_error from None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_error
    structlog.contextvars.bind_contextvars(user_id=user.id, user_role=user.role.value)
    return user


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DbSession) -> User:
    return await _user_from_token(token, db)


async def get_optional_user(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)], db: DbSession
) -> User | None:
    if token is None:
        return None
    return await _user_from_token(token, db)


def require_roles(*roles: UserRole):
    """Dependency factory: allow only the given roles."""

    async def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
StaffUser = Annotated[User, Depends(require_roles(UserRole.AGENT, UserRole.ADMIN))]
