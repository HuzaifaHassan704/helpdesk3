import os

# Must be set before the app is imported.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"  # the app's own engine is unused: get_db is overridden
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key-1234"
os.environ["AUTO_CREATE_TABLES"] = "false"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # enabled explicitly in tests/test_rate_limit.py
os.environ["CORS_ORIGINS"] = "https://app.example.com"
os.environ["LOG_JSON"] = "true"

# Set TEST_DATABASE_URL=postgresql+asyncpg://... to run the whole suite against PostgreSQL (CI does).
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://")
IS_SQLITE = TEST_DB_URL.startswith("sqlite")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

import app.models  # noqa: F401
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app as fastapi_app
from app.models import User, UserRole

PASSWORD = "Password123!"


@pytest_asyncio.fixture
async def session_factory():
    """Fresh schema for every test: in-memory SQLite by default, PostgreSQL if TEST_DATABASE_URL is set."""
    if IS_SQLITE:
        engine = create_async_engine(TEST_DB_URL, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        if not IS_SQLITE:
            await conn.run_sync(Base.metadata.drop_all)  # clear leftovers from an aborted run
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    if not IS_SQLITE:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_user(session_factory):
    async def _make(email: str, role: UserRole = UserRole.EMPLOYEE, **kwargs) -> User:
        async with session_factory() as s:
            user = User(
                email=email,
                full_name=kwargs.pop("full_name", email.split("@")[0]),
                hashed_password=hash_password(kwargs.pop("password", PASSWORD)),
                role=role,
                **kwargs,
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
            return user

    return _make


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest_asyncio.fixture
async def employee(make_user):
    return await make_user("emp1@example.com", UserRole.EMPLOYEE)


@pytest_asyncio.fixture
async def employee2(make_user):
    return await make_user("emp2@example.com", UserRole.EMPLOYEE)


@pytest_asyncio.fixture
async def agent(make_user):
    return await make_user("agent1@example.com", UserRole.AGENT)


@pytest_asyncio.fixture
async def agent2(make_user):
    return await make_user("agent2@example.com", UserRole.AGENT)


@pytest_asyncio.fixture
async def admin(make_user):
    return await make_user("admin@example.com", UserRole.ADMIN)


@pytest_asyncio.fixture
async def make_ticket(client):
    async def _make(user: User, title="Printer is broken", description="It jams constantly", **extra) -> dict:
        r = await client.post(
            "/tickets/", json={"title": title, "description": description, **extra}, headers=auth(user)
        )
        assert r.status_code == 201, r.text
        return r.json()

    return _make
