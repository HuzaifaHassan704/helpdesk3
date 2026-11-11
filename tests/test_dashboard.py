from tests.conftest import auth


async def test_stats_empty(client, agent):
    body = (await client.get("/dashboard/stats", headers=auth(agent))).json()
    assert body["total_tickets"] == 0
    assert body["by_status"] == {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0}
    assert body["by_priority"] == {"low": 0, "medium": 0, "high": 0, "urgent": 0}
    assert body["avg_resolution_hours"] is None and body["resolved_tickets"] == 0


async def test_stats_counts_and_avg_resolution(client, employee, agent, make_ticket):
    t1 = await make_ticket(employee, priority="low")
    t2 = await make_ticket(employee, priority="high")
    t3 = await make_ticket(employee, priority="high")
    await make_ticket(employee, priority="urgent")
    h = auth(agent)
    for step in ("in_progress", "resolved"):
        await client.patch(f"/tickets/{t1['id']}", json={"status": step}, headers=h)
    await client.patch(f"/tickets/{t2['id']}", json={"status": "in_progress"}, headers=h)
    await client.patch(f"/tickets/{t3['id']}", json={"status": "closed"}, headers=h)

    body = (await client.get("/dashboard/stats", headers=h)).json()
    assert body["total_tickets"] == 4
    assert body["by_status"] == {"open": 1, "in_progress": 1, "resolved": 1, "closed": 1}
    assert body["by_priority"] == {"low": 1, "medium": 0, "high": 2, "urgent": 1}
    assert body["resolved_tickets"] == 2
    assert body["avg_resolution_hours"] is not None and body["avg_resolution_hours"] >= 0
