from fastapi import APIRouter, Response, status

from app.core.deps import AdminUser, DbSession
from app.schemas.setting import PublicInfo, SettingCreate, SettingOut, SettingUpdate
from app.services import settings_service

router = APIRouter(prefix="/admin/settings", tags=["admin: system settings"])
public = APIRouter(prefix="/system", tags=["system"])


@router.get("/", response_model=list[SettingOut])
async def list_settings(db: DbSession, _: AdminUser):
    return await settings_service.list_settings(db)


@router.post("/", response_model=SettingOut, status_code=status.HTTP_201_CREATED)
async def create_setting(payload: SettingCreate, db: DbSession, admin: AdminUser):
    return await settings_service.create(db, payload, admin)


@router.get("/{key}", response_model=SettingOut)
async def get_setting(key: str, db: DbSession, _: AdminUser):
    return await settings_service.get_or_404(db, key)


@router.patch("/{key}", response_model=SettingOut)
async def update_setting(key: str, payload: SettingUpdate, db: DbSession, admin: AdminUser):
    row = await settings_service.get_or_404(db, key)
    return await settings_service.update(db, row, payload, admin)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting(key: str, db: DbSession, _: AdminUser):
    await settings_service.delete(db, await settings_service.get_or_404(db, key))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public.get("/public", response_model=PublicInfo)
async def public_info(db: DbSession):
    """Non-sensitive settings the login page needs before anyone is signed in."""
    return PublicInfo(
        company_name=await settings_service.get_value(db, "company_name"),
        registration_open=await settings_service.get_bool(db, "allow_employee_registration"),
    )
