from tests.conftest import PASSWORD, auth

REG = {"email": "new@example.com", "full_name": "New User", "password": PASSWORD}


async def test_register_defaults_to_employee(client):
    r = await client.post("/auth/register", json=REG)
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "employee" and body["email"] == "new@example.com"
    assert "password" not in body and "hashed_password" not in body


async def test_register_duplicate_email(client):
    await client.post("/auth/register", json=REG)
    r = await client.post("/auth/register", json={**REG, "email": "NEW@example.com"})
    assert r.status_code == 409


async def test_register_validation(client):
    assert (await client.post("/auth/register", json={**REG, "password": "short"})).status_code == 422
    assert (await client.post("/auth/register", json={**REG, "email": "nope"})).status_code == 422


async def test_anonymous_cannot_register_privileged_roles(client):
    for role in ("agent", "admin"):
        r = await client.post("/auth/register", json={**REG, "role": role})
        assert r.status_code == 403


async def test_employee_and_agent_cannot_register_privileged_roles(client, employee, agent):
    for user in (employee, agent):
        r = await client.post("/auth/register", json={**REG, "role": "agent"}, headers=auth(user))
        assert r.status_code == 403


async def test_admin_can_register_agent_and_admin(client, admin):
    for i, role in enumerate(("agent", "admin")):
        r = await client.post(
            "/auth/register", json={**REG, "email": f"p{i}@example.com", "role": role}, headers=auth(admin)
        )
        assert r.status_code == 201 and r.json()["role"] == role


async def test_login_success_and_me(client):
    await client.post("/auth/register", json=REG)
    r = await client.post("/auth/login", data={"username": REG["email"], "password": PASSWORD})
    assert r.status_code == 200
    token = r.json()
    assert token["token_type"] == "bearer"
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == REG["email"]


async def test_login_wrong_password_and_unknown_user(client, employee):
    r = await client.post("/auth/login", data={"username": employee.email, "password": "wrong-password"})
    assert r.status_code == 401
    r = await client.post("/auth/login", data={"username": "ghost@example.com", "password": PASSWORD})
    assert r.status_code == 401


async def test_login_inactive_user(client, make_user):
    u = await make_user("off@example.com", is_active=False)
    r = await client.post("/auth/login", data={"username": u.email, "password": PASSWORD})
    assert r.status_code == 403


async def test_me_requires_valid_token(client, employee):
    assert (await client.get("/users/me")).status_code == 401
    assert (await client.get("/users/me", headers={"Authorization": "Bearer garbage"})).status_code == 401


async def test_deactivated_user_token_rejected(client, admin, employee):
    r = await client.patch(f"/users/{employee.id}", json={"is_active": False}, headers=auth(admin))
    assert r.status_code == 200
    assert (await client.get("/users/me", headers=auth(employee))).status_code == 401
