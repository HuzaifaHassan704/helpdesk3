from fastapi import APIRouter

from app.core.deps import DbSession, StaffUser
from app.schemas.dashboard import DashboardStats
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def stats(db: DbSession, _: StaffUser):
    return await dashboard_service.get_stats(db)
