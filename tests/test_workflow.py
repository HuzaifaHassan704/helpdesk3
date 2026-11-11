from tests.conftest import auth


async def move(client, user, ticket_id, status):
    return await client.patch(f"/tickets/{ticket_id}", json={"status": status}, headers=auth(user))


async def test_allowed_statuses_depend_on_role_and_state(client, employee, agent, admin, make_ticket):
    t = await make_ticket(employee)
    assert t["allowed_statuses"] == ["closed"]  # an employee can only cancel an open ticket
    view = lambda u: client.get(f"/tickets/{t['id']}", headers=auth(u))  # noqa: E731
    assert (await view(agent)).json()["allowed_statuses"] == ["in_progress", "closed"]
    await move(client, agent, t["id"], "in_progress")
    assert (await view(agent)).json()["allowed_statuses"] == ["open", "resolved", "closed"]
    await move(client, agent, t["id"], "resolved")
    assert (await view(employee)).json()["allowed_statuses"] == ["open", "closed"]
    await move(client, agent, t["id"], "closed")
    assert (await view(agent)).json()["allowed_statuses"] == []
    assert (await view(admin)).json()["allowed_statuses"] == ["open"]


async def test_happy_path_open_to_closed(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    for step in ("in_progress", "resolved", "closed"):
        r = await move(client, agent, t["id"], step)
        assert r.status_code == 200 and r.json()["status"] == step
    assert r.json()["resolved_at"] is not None


async def test_cannot_skip_in_progress(client, employee, agent, admin, make_ticket):
    t = await make_ticket(employee)
    for user in (agent, admin):
        r = await move(client, user, t["id"], "resolved")
        assert r.status_code == 409 and "open -> resolved" in r.json()["detail"]
    assert (await move(client, employee, t["id"], "resolved")).status_code == 403  # role rule is checked first


async def test_closed_is_final_except_admin_reopen(client, employee, agent, admin, make_ticket):
    t = await make_ticket(employee)
    await move(client, agent, t["id"], "closed")
    for user in (agent, employee):
        assert (await move(client, user, t["id"], "open")).status_code == 403
    r = await move(client, admin, t["id"], "open")
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["resolved_at"] is None
    assert (await move(client, admin, t["id"], "resolved")).status_code == 409


async def test_same_status_is_a_no_op(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    r = await move(client, agent, t["id"], "open")
    assert r.status_code == 200 and r.json()["status"] == "open"


async def test_list_items_include_allowed_statuses(client, employee, agent, make_ticket):
    await make_ticket(employee)
    item = (await client.get("/tickets/", headers=auth(agent))).json()["items"][0]
    assert item["allowed_statuses"] == ["in_progress", "closed"]
