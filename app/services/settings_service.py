from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import SystemSetting, User
from app.schemas.setting import SettingCreate, SettingUpdate

logger = get_logger("app.settings")

# Used when a key has not been stored (or was deleted), so the app always behaves sensibly.
DEFAULTS: dict[str, str] = {
    "company_name": "Acme Helpdesk",
    "max_open_tickets_per_employee": "20",
    "allow_employee_registration": "true",
    "auto_assign_on_create": "false",  # give new tickets to the least-loaded active agent
    "sla_hours_urgent": "4",
    "sla_hours_high": "8",
    "sla_hours_medium": "24",
    "sla_hours_low": "72",
}


async def get_value(db: AsyncSession, key: str) -> str:
    row = await db.get(SystemSetting, key)
    return row.value if row else DEFAULTS[key]


async def get_bool(db: AsyncSession, key: str) -> bool:
    return (await get_value(db, key)).strip().lower() in {"1", "true", "yes", "on"}


async def get_int(db: AsyncSession, key: str) -> int:
    try:
        return int((await get_value(db, key)).strip())
    except ValueError:
        return int(DEFAULTS[key])


async def list_settings(db: AsyncSession) -> list[SystemSetting]:
    return list(await db.scalars(select(SystemSetting).order_by(SystemSetting.key)))


async def get_or_404(db: AsyncSession, key: str) -> SystemSetting:
    row = await db.get(SystemSetting, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Setting not found")
    return row


async def create(db: AsyncSession, data: SettingCreate, admin: User) -> SystemSetting:
    if await db.get(SystemSetting, data.key):
        raise HTTPException(status.HTTP_409_CONFLICT, "Setting already exists")
    row = SystemSetting(key=data.key, value=data.value, description=data.description, updated_by_id=admin.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("setting_created", key=row.key, value=row.value)
    return row


async def update(db: AsyncSession, row: SystemSetting, data: SettingUpdate, admin: User) -> SystemSetting:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by_id = admin.id
    await db.commit()
    await db.refresh(row)
    logger.info("setting_updated", key=row.key, value=row.value)
    return row


async def delete(db: AsyncSession, row: SystemSetting) -> None:
    key = row.key
    await db.delete(row)
    await db.commit()
    logger.info("setting_deleted", key=key)
