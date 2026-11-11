from tests.conftest import PASSWORD, auth

NEW = {"key": "support_email", "value": "help@example.com", "description": "Where users write"}


async def test_admin_crud(client, admin):
    h = auth(admin)
    r = await client.post("/admin/settings/", json=NEW, headers=h)
    assert r.status_code == 201 and r.json()["updated_by_id"] == admin.id
    assert (await client.post("/admin/settings/", json=NEW, headers=h)).status_code == 409
    assert any(s["key"] == "support_email" for s in (await client.get("/admin/settings/", headers=h)).json())
    assert (await client.get("/admin/settings/support_email", headers=h)).json()["value"] == "help@example.com"
    r = await client.patch("/admin/settings/support_email", json={"value": "new@example.com"}, headers=h)
    assert (
        r.status_code == 200
        and r.json()["value"] == "new@example.com"
        and r.json()["description"] == "Where users write"
    )
    assert (await client.delete("/admin/settings/support_email", headers=h)).status_code == 204
    assert (await client.get("/admin/settings/support_email", headers=h)).status_code == 404
    assert (await client.patch("/admin/settings/nope", json={"value": "x"}, headers=h)).status_code == 404
    assert (await client.delete("/admin/settings/nope", headers=h)).status_code == 404


async def test_only_admin_can_manage_settings(client, employee, agent):
    assert (await client.get("/admin/settings/")).status_code == 401
    for user in (employee, agent):
        h = auth(user)
        assert (await client.get("/admin/settings/", headers=h)).status_code == 403
        assert (await client.post("/admin/settings/", json=NEW, headers=h)).status_code == 403
        assert (await client.patch("/admin/settings/x", json={"value": "1"}, headers=h)).status_code == 403
        assert (await client.delete("/admin/settings/x", headers=h)).status_code == 403


async def test_setting_validation(client, admin):
    h = auth(admin)
    for bad in ({**NEW, "key": "Bad Key!"}, {**NEW, "key": ""}, {**NEW, "value": ""}, {**NEW, "value": "x" * 1001}):
        assert (await client.post("/admin/settings/", json=bad, headers=h)).status_code == 422
    await client.post("/admin/settings/", json=NEW, headers=h)
    assert (await client.patch("/admin/settings/support_email", json={"value": None}, headers=h)).status_code == 422


async def test_public_info_uses_defaults_and_settings(client, admin):
    assert (await client.get("/system/public")).json() == {"company_name": "Acme Helpdesk", "registration_open": True}
    h = auth(admin)
    await client.post("/admin/settings/", json={"key": "company_name", "value": "Globex Support"}, headers=h)
    assert (await client.get("/system/public")).json()["company_name"] == "Globex Support"


async def test_registration_can_be_closed(client, admin):
    h = auth(admin)
    await client.post("/admin/settings/", json={"key": "allow_employee_registration", "value": "false"}, headers=h)
    assert (await client.get("/system/public")).json()["registration_open"] is False
    body = {"email": "late@example.com", "full_name": "Late", "password": PASSWORD}
    r = await client.post("/auth/register", json=body)
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    assert (await client.post("/auth/register", json=body, headers=h)).status_code == 201  # admins can still add users


async def test_open_ticket_limit_is_enforced(client, admin, employee, make_ticket):
    await client.post(
        "/admin/settings/", json={"key": "max_open_tickets_per_employee", "value": "2"}, headers=auth(admin)
    )
    first = await make_ticket(employee, title="First ticket")
    await make_ticket(employee, title="Second ticket")
    r = await client.post("/tickets/", json={"title": "Third ticket", "description": "x"}, headers=auth(employee))
    assert r.status_code == 409 and "limit" in r.json()["detail"]
    await client.patch(f"/tickets/{first['id']}", json={"status": "closed"}, headers=auth(employee))
    assert (
        await client.post("/tickets/", json={"title": "Third ticket", "description": "x"}, headers=auth(employee))
    ).status_code == 201
    # admins are not limited
    for i in range(3):
        assert (
            await client.post("/tickets/", json={"title": f"Admin ticket {i}", "description": "x"}, headers=auth(admin))
        ).status_code == 201


async def test_bad_limit_value_falls_back_to_default(client, admin, employee, make_ticket):
    await client.post(
        "/admin/settings/", json={"key": "max_open_tickets_per_employee", "value": "lots"}, headers=auth(admin)
    )
    await make_ticket(employee)  # falls back to the default of 20, so this is allowed
