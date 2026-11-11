import pytest

from app.core.rate_limit import limiter
from tests.conftest import PASSWORD, auth


@pytest.fixture
def rate_limiting():
    """Rate limiting is off for the rest of the suite; switch it on for these tests only."""
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


async def test_login_is_rate_limited(client, employee, rate_limiting):
    bad = {"username": employee.email, "password": "wrong-password"}
    codes = [(await client.post("/auth/login", data=bad)).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5  # limit is 5/minute
    assert codes[5:] == [429, 429]
    # even the correct password is refused while limited
    good = await client.post("/auth/login", data={"username": employee.email, "password": PASSWORD})
    assert good.status_code == 429
    assert "Rate limit exceeded" in good.json()["detail"]
    assert "x-request-id" in good.headers and good.headers["x-content-type-options"] == "nosniff"


async def test_register_is_rate_limited(client, rate_limiting):
    codes = []
    for i in range(12):
        payload = {"email": f"user{i}@example.com", "full_name": "U", "password": PASSWORD}
        codes.append((await client.post("/auth/register", json=payload)).status_code)
    assert codes[:10] == [201] * 10  # limit is 10/hour
    assert codes[10:] == [429, 429]


async def test_ticket_creation_is_rate_limited(client, admin, rate_limiting):
    body = {"title": "Spam ticket", "description": "x"}
    codes = [(await client.post("/tickets/", json=body, headers=auth(admin))).status_code for _ in range(32)]
    assert codes[:30] == [201] * 30  # limit is 30/minute
    assert codes[30:] == [429, 429]


async def test_other_endpoints_not_limited(client, employee, rate_limiting):
    for _ in range(40):
        assert (await client.get("/users/me", headers=auth(employee))).status_code == 200


async def test_limiter_disabled_by_default(client, employee):
    bad = {"username": employee.email, "password": "wrong-password"}
    codes = {(await client.post("/auth/login", data=bad)).status_code for _ in range(8)}
    assert 429 not in codes  # (after 5 failures the account lockout answers 423 instead)
