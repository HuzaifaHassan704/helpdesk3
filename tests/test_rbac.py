from tests.conftest import IS_SQLITE, auth


async def test_employee_and_agent_blocked_from_admin_user_routes(client, employee, agent, admin):
    for user in (employee, agent):
        h = auth(user)
        assert (await client.get("/users/", headers=h)).status_code == 403
        assert (await client.get(f"/users/{admin.id}", headers=h)).status_code == 403
        assert (await client.patch(f"/users/{admin.id}", json={"role": "employee"}, headers=h)).status_code == 403
        assert (await client.delete(f"/users/{admin.id}", headers=h)).status_code == 403
    assert (await client.get("/users/", headers=auth(admin))).status_code == 200


async def test_admin_user_crud(client, admin, employee):
    h = auth(admin)
    r = await client.patch(f"/users/{employee.id}", json={"role": "agent", "full_name": "Promoted"}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "agent"
    assert (await client.get(f"/users/{employee.id}", headers=h)).json()["full_name"] == "Promoted"
    assert (await client.delete(f"/users/{employee.id}", headers=h)).status_code == 204
    assert (await client.get(f"/users/{employee.id}", headers=h)).status_code == 404


async def test_admin_cannot_demote_or_delete_self(client, admin):
    h = auth(admin)
    assert (await client.patch(f"/users/{admin.id}", json={"role": "employee"}, headers=h)).status_code == 400
    assert (await client.delete(f"/users/{admin.id}", headers=h)).status_code == 400


async def test_cannot_delete_user_who_owns_tickets(client, admin, employee, make_ticket):
    await make_ticket(employee)
    r = await client.delete(f"/users/{employee.id}", headers=auth(admin))
    assert r.status_code == 409


async def test_dashboard_restricted_to_staff(client, employee, agent, admin):
    assert (await client.get("/dashboard/stats")).status_code == 401
    assert (await client.get("/dashboard/stats", headers=auth(employee))).status_code == 403
    assert (await client.get("/dashboard/stats", headers=auth(agent))).status_code == 200
    assert (await client.get("/dashboard/stats", headers=auth(admin))).status_code == 200


async def test_employee_cannot_assign_or_reassign(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    r = await client.post(f"/tickets/{t['id']}/assign", json={"assignee_id": agent.id}, headers=auth(employee))
    assert r.status_code == 403
    await client.post(f"/tickets/{t['id']}/assign", json={}, headers=auth(agent))
    r = await client.post(f"/tickets/{t['id']}/assign", json={}, headers=auth(employee))
    assert r.status_code == 403


async def test_agent_cannot_create_tickets(client, agent):
    r = await client.post("/tickets/", json={"title": "Hello there", "description": "x"}, headers=auth(agent))
    assert r.status_code == 403


async def test_admin_can_create_tickets(client, admin):
    r = await client.post("/tickets/", json={"title": "From admin", "description": "x"}, headers=auth(admin))
    assert r.status_code == 201


async def test_employee_cannot_see_others_tickets(client, employee, employee2, make_ticket):
    t = await make_ticket(employee)
    h = auth(employee2)
    assert (await client.get(f"/tickets/{t['id']}", headers=h)).status_code == 404
    assert (await client.patch(f"/tickets/{t['id']}", json={"title": "Hijacked"}, headers=h)).status_code == 404
    assert (await client.post(f"/tickets/{t['id']}/comments", json={"body": "hi"}, headers=h)).status_code == 404
    assert (await client.get("/tickets/", headers=h)).json()["total"] == 0


async def test_employee_patch_rules(client, employee, make_ticket):
    h = auth(employee)
    t = await make_ticket(employee)
    tid = t["id"]
    r = await client.patch(f"/tickets/{tid}", json={"title": "Updated title", "priority": "high"}, headers=h)
    assert r.status_code == 200 and r.json()["priority"] == "high"
    # employees cannot move a ticket into agent-only states
    assert (await client.patch(f"/tickets/{tid}", json={"status": "in_progress"}, headers=h)).status_code == 403
    assert (await client.patch(f"/tickets/{tid}", json={"status": "resolved"}, headers=h)).status_code == 403
    # ...but may close their own ticket, after which it is read-only
    assert (await client.patch(f"/tickets/{tid}", json={"status": "closed"}, headers=h)).status_code == 200
    assert (await client.patch(f"/tickets/{tid}", json={"title": "Too late"}, headers=h)).status_code == 403


async def test_employee_can_reopen_resolved_ticket(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    for step in ("in_progress", "resolved"):
        await client.patch(f"/tickets/{t['id']}", json={"status": step}, headers=auth(agent))
    r = await client.patch(f"/tickets/{t['id']}", json={"status": "open"}, headers=auth(employee))
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["resolved_at"] is None


async def test_agent_can_only_update_status_and_priority(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    h = auth(agent)
    assert (await client.patch(f"/tickets/{t['id']}", json={"title": "Rewritten"}, headers=h)).status_code == 403
    r = await client.patch(f"/tickets/{t['id']}", json={"status": "in_progress", "priority": "urgent"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


async def test_admin_can_edit_everything(client, employee, admin, make_ticket):
    t = await make_ticket(employee)
    r = await client.patch(f"/tickets/{t['id']}", json={"title": "Admin edit", "status": "closed"}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["title"] == "Admin edit"


async def test_only_admin_can_delete_ticket(client, employee, agent, admin, make_ticket):
    t = await make_ticket(employee)
    await client.post(f"/tickets/{t['id']}/comments", json={"body": "c"}, headers=auth(employee))
    for u in (employee, agent):
        assert (await client.delete(f"/tickets/{t['id']}", headers=auth(u))).status_code == 403
    assert (await client.delete(f"/tickets/{t['id']}", headers=auth(admin))).status_code == 204
    assert (await client.get(f"/tickets/{t['id']}", headers=auth(admin))).status_code == 404


async def test_comments_and_internal_notes(client, employee, employee2, agent, make_ticket):
    t = await make_ticket(employee)
    url = f"/tickets/{t['id']}/comments"
    assert (await client.post(url, json={"body": "Any update?"}, headers=auth(employee))).status_code == 201
    assert (
        await client.post(url, json={"body": "secret", "is_internal": True}, headers=auth(employee))
    ).status_code == 403
    assert (
        await client.post(url, json={"body": "Looking", "is_internal": False}, headers=auth(agent))
    ).status_code == 201
    assert (
        await client.post(url, json={"body": "Note to self", "is_internal": True}, headers=auth(agent))
    ).status_code == 201

    assert len((await client.get(url, headers=auth(employee))).json()) == 2  # internal hidden
    assert len((await client.get(url, headers=auth(agent))).json()) == 3
    assert (await client.get(url, headers=auth(employee2))).status_code == 404


async def test_cannot_delete_user_who_only_commented(client, admin, employee, agent, make_ticket):
    t = await make_ticket(employee)
    r = await client.post(f"/tickets/{t['id']}/comments", json={"body": "looking into it"}, headers=auth(agent))
    assert r.status_code == 201
    r = await client.delete(f"/users/{agent.id}", headers=auth(admin))
    assert r.status_code == 409 and "deactivate" in r.json()["detail"]
    assert (await client.get(f"/users/{agent.id}", headers=auth(admin))).status_code == 200


async def test_sqlite_foreign_keys_are_enforced(session_factory):
    """The test engine (and the app engine) turn on PRAGMA foreign_keys, so ondelete rules apply locally."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.models import Comment

    if not IS_SQLITE:
        pytest.skip("SQLite-specific check")
    async with session_factory() as s:
        s.add(Comment(ticket_id=999, author_id=999, body="orphan"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_demoting_an_agent_returns_their_tickets_to_the_queue(client, admin, employee, agent, make_ticket):
    h = auth(admin)
    t, done = await make_ticket(employee, title="Active one"), await make_ticket(employee, title="Finished one")
    for ticket in (t, done):
        await client.post(f"/tickets/{ticket['id']}/assign", json={"assignee_id": agent.id}, headers=h)
    await client.patch(f"/tickets/{done['id']}", json={"status": "resolved"}, headers=h)

    assert (await client.patch(f"/users/{agent.id}", json={"role": "employee"}, headers=h)).status_code == 200

    active = (await client.get(f"/tickets/{t['id']}", headers=h)).json()
    assert active["assignee_id"] is None and active["status"] == "open"
    events = (await client.get(f"/tickets/{t['id']}/history", headers=h)).json()
    assert events[-1]["event"] == "unassigned" and events[-1]["actor_id"] == admin.id
    kept = (await client.get(f"/tickets/{done['id']}", headers=h)).json()
    assert kept["assignee_id"] == agent.id and kept["status"] == "resolved"  # history of who handled it stays


async def test_deleting_an_agent_reopens_their_in_progress_tickets(client, admin, employee, agent, make_ticket):
    h = auth(admin)
    t = await make_ticket(employee)
    await client.post(f"/tickets/{t['id']}/assign", json={"assignee_id": agent.id}, headers=h)
    assert (await client.delete(f"/users/{agent.id}", headers=h)).status_code == 204
    after = (await client.get(f"/tickets/{t['id']}", headers=h)).json()
    assert after["assignee_id"] is None and after["status"] == "open"


async def test_deactivating_an_agent_releases_their_open_tickets(client, admin, employee, agent, make_ticket):
    h = auth(admin)
    t = await make_ticket(employee)
    await client.post(f"/tickets/{t['id']}/assign", json={"assignee_id": agent.id}, headers=h)
    assert (await client.patch(f"/users/{agent.id}", json={"is_active": False}, headers=h)).status_code == 200
    after = (await client.get(f"/tickets/{t['id']}", headers=h)).json()
    assert after["assignee_id"] is None and after["status"] == "open"
    events = (await client.get(f"/tickets/{t['id']}/history", headers=h)).json()
    assert events[-1]["event"] == "unassigned" and "deactivated" in events[-1]["detail"]
    # re-activating later does not fire the release again
    assert (await client.patch(f"/users/{agent.id}", json={"is_active": True}, headers=h)).status_code == 200
