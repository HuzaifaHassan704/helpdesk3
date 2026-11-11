from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.deps import DbSession, OptionalUser
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.models import UserRole
from app.schemas.user import Token, UserCreate, UserOut
from app.services import settings_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("app.auth")


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: settings.RATE_LIMIT_REGISTER)
async def register(request: Request, payload: UserCreate, db: DbSession, current_user: OptionalUser):
    """Public sign-up creates an Employee. Only an authenticated Admin may create Agents/Admins."""
    if payload.role != UserRole.EMPLOYEE and (current_user is None or current_user.role != UserRole.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can create agent or admin accounts")
    is_admin = current_user is not None and current_user.role == UserRole.ADMIN
    if not is_admin and not await settings_service.get_bool(db, "allow_employee_registration"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is currently closed")
    user = await user_service.create_user(db, payload)
    logger.info("user_registered", new_user_id=user.id, role=user.role.value)
    return user


@router.post("/login", response_model=Token)
@limiter.limit(lambda: settings.RATE_LIMIT_LOGIN)
async def login(request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    """OAuth2 password flow: send `username` (the email) and `password` as form data."""
    user = await user_service.authenticate(db, form.username, form.password, get_remote_address(request)[:45])
    if user is None:
        logger.warning("login_failed")  # never log the submitted email/password
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, user_service.INVALID_LOGIN, headers={"WWW-Authenticate": "Bearer"}
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    logger.info("login_succeeded", user_id=user.id)
    return Token(access_token=create_access_token(user.id))
