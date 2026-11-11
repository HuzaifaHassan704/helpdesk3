from datetime import UTC, datetime, timedelta

from tests.conftest import auth


async def _seed(make_ticket, employee, n=7):
    return [await make_ticket(employee, title=f"Ticket number {i}") for i in range(n)]


async def test_page_param_and_metadata(client, employee, agent, make_ticket):
    await _seed(make_ticket, employee, 7)
    h = auth(agent)
    r = (await client.get("/tickets/?page=2&limit=3", headers=h)).json()
    assert (r["page"], r["pages"], r["total"], r["skip"], r["limit"]) == (2, 3, 7, 3, 3)
    assert r["has_next"] and r["has_prev"] and len(r["items"]) == 3
    last = (await client.get("/tickets/?page=3&limit=3", headers=h)).json()
    assert len(last["items"]) == 1 and not last["has_next"] and last["next_cursor"] is None
    beyond = (await client.get("/tickets/?page=9&limit=3", headers=h)).json()
    assert beyond["items"] == [] and beyond["total"] == 7 and not beyond["has_next"]


async def test_empty_result_metadata(client, agent):
    r = (await client.get("/tickets/", headers=auth(agent))).json()
    assert (r["total"], r["pages"], r["has_next"], r["has_prev"]) == (0, 0, False, False)


async def test_results_are_newest_first(client, employee, agent, make_ticket):
    created = await _seed(make_ticket, employee, 4)
    ids = [t["id"] for t in (await client.get("/tickets/", headers=auth(agent))).json()["items"]]
    assert ids == sorted((t["id"] for t in created), reverse=True)


async def test_cursor_walks_every_ticket_exactly_once(client, employee, agent, make_ticket):
    created = await _seed(make_ticket, employee, 7)
    h = auth(agent)
    seen, cursor, pages = [], None, 0
    while True:
        url = "/tickets/?limit=3" + (f"&cursor={cursor}" if cursor else "")
        body = (await client.get(url, headers=h)).json()
        seen += [t["id"] for t in body["items"]]
        pages += 1
        assert body["total"] == 7
        if not body["has_next"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
        assert cursor
    assert pages == 3
    assert sorted(seen) == sorted(t["id"] for t in created) and len(seen) == len(set(seen))


async def test_cursor_is_stable_when_new_tickets_arrive(client, employee, agent, make_ticket):
    await _seed(make_ticket, employee, 5)
    h = auth(agent)
    first = (await client.get("/tickets/?limit=3", headers=h)).json()
    await make_ticket(employee, title="Arrived mid-pagination")  # would shift offset pages, not keyset pages
    second = (await client.get(f"/tickets/?limit=3&cursor={first['next_cursor']}", headers=h)).json()
    assert {t["id"] for t in first["items"]}.isdisjoint(t["id"] for t in second["items"])
    assert len(second["items"]) == 2


async def test_cursor_validation(client, agent):
    h = auth(agent)
    assert (await client.get("/tickets/?cursor=not-a-cursor", headers=h)).status_code == 400
    assert (await client.get("/tickets/?cursor=aWQ6NQ&skip=5", headers=h)).status_code == 400  # cursor = id:5
    assert (await client.get("/tickets/?cursor=aWQ6NQ&page=2", headers=h)).status_code == 400
    assert (await client.get("/tickets/?cursor=aWQ6NQ", headers=h)).status_code == 200
    assert (await client.get("/tickets/?page=0", headers=h)).status_code == 422


async def test_cursor_respects_employee_visibility(client, employee, employee2, make_ticket):
    await _seed(make_ticket, employee, 3)
    await make_ticket(employee2, title="Not yours at all")
    body = (await client.get("/tickets/?limit=2", headers=auth(employee))).json()
    assert body["total"] == 3 and len(body["items"]) == 2
    nxt = (await client.get(f"/tickets/?limit=2&cursor={body['next_cursor']}", headers=auth(employee))).json()
    assert len(nxt["items"]) == 1 and all(t["creator_id"] == employee.id for t in nxt["items"])


async def test_created_date_range_filter(client, employee, agent, make_ticket):
    await _seed(make_ticket, employee, 3)
    h = auth(agent)
    now = datetime.now(UTC)
    inside = {
        "created_from": (now - timedelta(hours=1)).isoformat(),
        "created_to": (now + timedelta(hours=1)).isoformat(),
    }
    assert (await client.get("/tickets/", params=inside, headers=h)).json()["total"] == 3
    future = {"created_from": (now + timedelta(days=1)).isoformat()}
    assert (await client.get("/tickets/", params=future, headers=h)).json()["total"] == 0
    past = {"created_to": (now - timedelta(days=1)).isoformat()}
    assert (await client.get("/tickets/", params=past, headers=h)).json()["total"] == 0
    # timezone offsets are normalised to UTC (a naive value is treated as UTC)
    naive = {"created_from": (now - timedelta(hours=1)).replace(tzinfo=None).isoformat()}
    assert (await client.get("/tickets/", params=naive, headers=h)).json()["total"] == 3
