from tests.conftest import auth


async def test_create_ticket_defaults(client, employee):
    r = await client.post(
        "/tickets/", json={"title": "VPN down", "description": "Cannot connect"}, headers=auth(employee)
    )
    assert r.status_code == 201
    t = r.json()
    assert t["status"] == "open" and t["priority"] == "medium"
    assert t["creator_id"] == employee.id and t["assignee_id"] is None
    assert t["created_at"] and t["updated_at"] and t["resolved_at"] is None


async def test_create_ticket_validation(client, employee):
    h = auth(employee)
    assert (await client.post("/tickets/", json={"title": "ab", "description": "x"}, headers=h)).status_code == 422
    assert (await client.post("/tickets/", json={"title": "Valid title"}, headers=h)).status_code == 422
    r = await client.post(
        "/tickets/", json={"title": "Valid title", "description": "x", "priority": "bogus"}, headers=h
    )
    assert r.status_code == 422
    assert (await client.post("/tickets/", json={"title": "Valid title", "description": "x"})).status_code == 401


async def test_list_visibility_by_role(client, employee, employee2, agent, admin, make_ticket):
    await make_ticket(employee, title="Mine one")
    await make_ticket(employee, title="Mine two")
    await make_ticket(employee2, title="Theirs")
    assert (await client.get("/tickets/", headers=auth(employee))).json()["total"] == 2
    assert (await client.get("/tickets/", headers=auth(employee2))).json()["total"] == 1
    assert (await client.get("/tickets/", headers=auth(agent))).json()["total"] == 3
    assert (await client.get("/tickets/", headers=auth(admin))).json()["total"] == 3


async def test_get_ticket_and_404(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    assert (await client.get(f"/tickets/{t['id']}", headers=auth(employee))).json()["id"] == t["id"]
    assert (await client.get(f"/tickets/{t['id']}", headers=auth(agent))).status_code == 200
    assert (await client.get("/tickets/9999", headers=auth(agent))).status_code == 404


async def test_filter_by_status_priority_assignee(client, employee, agent, agent2, make_ticket):
    a = await make_ticket(employee, title="Alpha ticket", priority="low")
    b = await make_ticket(employee, title="Bravo ticket", priority="high")
    c = await make_ticket(employee, title="Charlie ticket", priority="high")
    await client.post(f"/tickets/{b['id']}/assign", json={}, headers=auth(agent))  # -> in_progress
    await client.post(f"/tickets/{c['id']}/assign", json={"assignee_id": agent2.id}, headers=auth(agent))
    await client.patch(f"/tickets/{c['id']}", json={"status": "resolved"}, headers=auth(agent))
    h = auth(agent)

    def ids(r):
        return {t["id"] for t in r.json()["items"]}

    assert ids(await client.get("/tickets/?status=open", headers=h)) == {a["id"]}
    assert ids(await client.get("/tickets/?status=in_progress", headers=h)) == {b["id"]}
    assert ids(await client.get("/tickets/?priority=high", headers=h)) == {b["id"], c["id"]}
    assert ids(await client.get(f"/tickets/?assignee_id={agent2.id}", headers=h)) == {c["id"]}
    assert ids(await client.get("/tickets/?priority=high&status=resolved", headers=h)) == {c["id"]}
    assert (await client.get("/tickets/?status=nonsense", headers=h)).status_code == 422


async def test_search_title_and_description(client, employee, agent, make_ticket):
    a = await make_ticket(employee, title="Laptop battery", description="Drains in an hour")
    b = await make_ticket(employee, title="Email issue", description="Outlook crashes on LAPTOP restart")
    await make_ticket(employee, title="Badge access", description="Door reader offline")
    r = await client.get("/tickets/?search=laptop", headers=auth(agent))  # case-insensitive
    assert {t["id"] for t in r.json()["items"]} == {a["id"], b["id"]}
    assert (await client.get("/tickets/?search=zzzz", headers=auth(agent))).json()["total"] == 0


async def test_search_treats_wildcards_literally(client, employee, make_ticket):
    await make_ticket(employee, title="Disk 100% full", description="urgent cleanup")
    await make_ticket(employee, title="Normal ticket", description="nothing special")
    h = auth(employee)
    assert (await client.get("/tickets/?search=%25", headers=h)).json()["total"] == 1  # literal '%'
    assert (await client.get("/tickets/?search=_", headers=h)).json()["total"] == 0


async def test_employee_search_scoped_to_own_tickets(client, employee, employee2, make_ticket):
    await make_ticket(employee, title="Shared keyword one")
    await make_ticket(employee2, title="Shared keyword two")
    r = await client.get("/tickets/?search=keyword", headers=auth(employee))
    assert r.json()["total"] == 1


async def test_pagination_and_total_header(client, employee, agent, make_ticket):
    for i in range(5):
        await make_ticket(employee, title=f"Ticket number {i}")
    h = auth(agent)
    r = await client.get("/tickets/?skip=0&limit=2", headers=h)
    body = r.json()
    assert r.headers["X-Total-Count"] == "5"
    assert body["total"] == 5 and len(body["items"]) == 2 and body["skip"] == 0 and body["limit"] == 2
    page2 = (await client.get("/tickets/?skip=2&limit=2", headers=h)).json()
    page3 = (await client.get("/tickets/?skip=4&limit=2", headers=h)).json()
    assert len(page2["items"]) == 2 and len(page3["items"]) == 1
    assert (body["page"], body["pages"], body["has_next"], body["has_prev"]) == (1, 3, True, False)
    assert (page2["page"], page2["has_next"], page2["has_prev"]) == (2, True, True)
    assert (page3["page"], page3["has_next"], page3["has_prev"]) == (3, False, True)
    all_ids = [t["id"] for t in body["items"] + page2["items"] + page3["items"]]
    assert len(set(all_ids)) == 5  # no overlaps between pages
    assert (await client.get("/tickets/?limit=0", headers=h)).status_code == 422
    assert (await client.get("/tickets/?limit=101", headers=h)).status_code == 422
    assert (await client.get("/tickets/?skip=-1", headers=h)).status_code == 422


async def test_patch_status_workflow_sets_resolved_at(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    h = auth(agent)
    await client.patch(f"/tickets/{t['id']}", json={"status": "in_progress"}, headers=h)
    r = await client.patch(f"/tickets/{t['id']}", json={"status": "resolved"}, headers=h)
    assert r.json()["resolved_at"] is not None
    r = await client.patch(f"/tickets/{t['id']}", json={"status": "in_progress"}, headers=h)
    assert r.json()["resolved_at"] is None


async def test_patch_rejects_null_and_empty(client, employee, make_ticket):
    t = await make_ticket(employee)
    r = await client.patch(f"/tickets/{t['id']}", json={"title": None}, headers=auth(employee))
    assert r.status_code == 422


async def test_assign_self_moves_open_to_in_progress(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    r = await client.post(f"/tickets/{t['id']}/assign", json={}, headers=auth(agent))
    assert r.status_code == 200
    assert r.json()["assignee_id"] == agent.id and r.json()["status"] == "in_progress"


async def test_assign_to_other_agent_and_reassign(client, employee, agent, agent2, admin, make_ticket):
    t = await make_ticket(employee)
    r = await client.post(f"/tickets/{t['id']}/assign", json={"assignee_id": agent2.id}, headers=auth(agent))
    assert r.json()["assignee_id"] == agent2.id
    r = await client.post(f"/tickets/{t['id']}/assign", json={"assignee_id": agent.id}, headers=auth(admin))
    assert r.json()["assignee_id"] == agent.id


async def test_assign_validation(client, employee, agent, make_user, make_ticket):
    t = await make_ticket(employee)
    h = auth(agent)
    url = f"/tickets/{t['id']}/assign"
    assert (await client.post(url, json={"assignee_id": employee.id}, headers=h)).status_code == 400
    assert (await client.post(url, json={"assignee_id": 9999}, headers=h)).status_code == 404
    inactive = await make_user("gone@example.com", role=agent.role, is_active=False)
    assert (await client.post(url, json={"assignee_id": inactive.id}, headers=h)).status_code == 400
    assert (await client.post("/tickets/9999/assign", json={}, headers=h)).status_code == 404
    await client.patch(f"/tickets/{t['id']}", json={"status": "closed"}, headers=h)
    assert (await client.post(url, json={}, headers=h)).status_code == 409


async def test_description_has_a_maximum_length(client, employee, make_ticket):
    h = auth(employee)
    ok = await client.post("/tickets/", json={"title": "Long one", "description": "x" * 5000}, headers=h)
    assert ok.status_code == 201
    assert (
        await client.post("/tickets/", json={"title": "Too long", "description": "x" * 5001}, headers=h)
    ).status_code == 422
    r = await client.patch(f"/tickets/{ok.json()['id']}", json={"description": "y" * 5001}, headers=h)
    assert r.status_code == 422
