"""Create an admin account (run `alembic upgrade head` first):

    python -m scripts.create_admin admin@example.com "Admin Name" "StrongPass123"
    python -m scripts.create_admin admin@example.com "Admin Name" "StrongPass123" --if-none

--if-none: do nothing when an admin already exists (used by start.py on first run).
Exit codes: 0 created, 1 rejected (e.g. email taken), 2 database not migrated, 3 skipped (--if-none).
"""

import asyncio
import sys

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.database import AsyncSessionLocal, engine
from app.models import User, UserRole
from app.schemas.user import UserCreate
from app.services import user_service


async def main(email: str, name: str, password: str, if_none: bool = False) -> int:
    try:
        async with AsyncSessionLocal() as db:
            if if_none:
                admins = await db.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
                if admins:
                    print("An admin account already exists.")
                    return 3
            user = await user_service.create_user(
                db, UserCreate(email=email, full_name=name, password=password, role=UserRole.ADMIN)
            )
            print(f"Created admin #{user.id} <{user.email}>")
        return 0
    except HTTPException as exc:
        print(f"Not created: {exc.detail}")
        return 1
    except (OperationalError, ProgrammingError):
        print("Database is not ready. Run `alembic upgrade head` first.")
        return 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--if-none"]
    if len(args) != 3:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(*args, if_none="--if-none" in sys.argv)))
