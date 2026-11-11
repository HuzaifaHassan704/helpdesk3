from fastapi import APIRouter, Query, Request, Response, status

from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, DbSession
from app.core.rate_limit import limiter
from app.schemas.user import PasswordChange, UserList, UserOut, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def read_me(current_user: CurrentUser):
    return current_user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(lambda: settings.RATE_LIMIT_LOGIN)
async def change_password(request: Request, payload: PasswordChange, db: DbSession, current_user: CurrentUser):
    await user_service.change_password(db, current_user, payload.current_password, payload.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/", response_model=UserList)
async def list_users(
    db: DbSession,
    _: AdminUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    items, total = await user_service.list_users(db, skip, limit)
    return UserList(items=items, total=total, skip=skip, limit=limit)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, db: DbSession, _: AdminUser):
    return await user_service.get_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, payload: UserUpdate, db: DbSession, admin: AdminUser):
    user = await user_service.get_or_404(db, user_id)
    return await user_service.update_user(db, user, payload, admin)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, db: DbSession, admin: AdminUser):
    user = await user_service.get_or_404(db, user_id)
    await user_service.delete_user(db, user, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
