import csv
import io
from datetime import UTC, datetime

import pytest

from app.services import notification_service
from tests.conftest import PASSWORD, auth


async def setting(client, admin, key, value):
    r = await client.post("/admin/settings/", json={"key": key, "value": value}, headers=auth(admin))
    assert r.status_code == 201


def hours_from_now(iso: str) -> float:
    due = datetime.fromisoformat(iso)
    due = due if due.tzinfo else due.replace(tzinfo=UTC)
    return (due - datetime.now(UTC)).total_seconds() / 3600


# ---------- history ----------
async def test_history_records_every_change(client, employee, agent, make_ticket):
    t = await make_ticket(employee)
    tid = t["id"]
    await client.post(f"/tickets/{tid}/assign", json={}, headers=auth(agent))
    await client.patch(f"/tickets/{tid}", json={"priority": "urgent"}, headers=auth(agent))
    await client.patch(f"/tickets/{tid}", json={"status": "resolved"}, headers=auth(agent))
    await client.post(f"/tickets/{tid}/comments", json={"body": "done"}, headers=auth(agent))
    await client.post(f"/tickets/{tid}/comments", json={"body": "secret", "is_internal": True}, headers=auth(agent))
    events = (await client.get(f"/tickets/{tid}/history", headers=auth(employee))).json()
    assert [e["event"] for e in events] == ["created", "assigned", "priority_changed", "status_changed", "commented"]
    assert events[2]["detail"] == "medium -> urgent" and events[3]["detail"] == "in_progress -> resolved"
    assert events[1]["actor_id"] == agent.id


async def test_history_visibility(client, employee, employee2, make_ticket):
    t = await make_ticket(employee)
    assert (await client.get(f"/tickets/{t['id']}/history", headers=auth(employee2))).status_code == 404
    assert (await client.get(f"/tickets/{t['id']}/history")).status_code == 401


# ---------- SLA ----------
async def test_due_date_follows_priority_and_updates(client, employee, agent, make_ticket):
    t = await make_ticket(employee, priority="urgent")
    assert 3.9 < hours_from_now(t["due_at"]) < 4.1 and t["is_overdue"] is False
    r = await client.patch(f"/tickets/{t['id']}", json={"priority": "low"}, headers=auth(agent))
    assert 71.9 < hours_from_now(r.json()["due_at"]) < 72.1


async def test_overdue_flag_and_dashboard(client, admin, employee, agent, make_ticket):
    await setting(client, admin, "sla_hours_high", "0")
    t = await make_ticket(employee, priority="high")
    assert (await client.get(f"/tickets/{t['id']}", headers=auth(agent))).json()["is_overdue"] is True
    assert (await client.get("/dashboard/stats", headers=auth(agent))).json()["overdue_tickets"] == 1
    for step in ("in_progress", "resolved"):
        await client.patch(f"/tickets/{t['id']}", json={"status": step}, headers=auth(agent))
    assert (await client.get(f"/tickets/{t['id']}", headers=auth(agent))).json()["is_overdue"] is False
    assert (await client.get("/dashboard/stats", headers=auth(agent))).json()["overdue_tickets"] == 0


# ---------- auto-assign ----------
async def test_auto_assign_balances_load(client, admin, employee, agent, agent2, make_ticket):
    await setting(client, admin, "auto_assign_on_create", "true")
    first = await make_ticket(employee, title="First one")
    second = await make_ticket(employee, title="Second one")
    assert {first["assignee_id"], second["assignee_id"]} == {agent.id, agent2.id}
    assert first["status"] == "in_progress"
    events = (await client.get(f"/tickets/{first['id']}/history", headers=auth(admin))).json()
    assert [e["event"] for e in events] == ["created", "auto_assigned"] and events[1]["actor_id"] is None


async def test_auto_assign_off_by_default_and_without_agents(client, admin, employee, agent, make_ticket):
    assert (await make_ticket(employee))["assignee_id"] is None
    await setting(client, admin, "auto_assign_on_create", "true")
    await client.patch(f"/users/{agent.id}", json={"is_active": False}, headers=auth(admin))
    assert (await make_ticket(employee, title="No agents left"))["assignee_id"] is None


# ---------- notifications ----------
@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def fake(to, subject, body):
        calls.append((to, subject))

    monkeypatch.setattr(notification_service, "notify", fake)
    return calls


async def test_assignment_and_status_notifications(client, employee, agent, agent2, make_ticket, sent):
    t = await make_ticket(employee)
    await client.post(f"/tickets/{t['id']}/assign", json={"assignee_id": agent2.id}, headers=auth(agent))
    assert sent == [(agent2.email, f"Ticket #{t['id']} assigned to you")]
    await client.post(f"/tickets/{t['id']}/assign", json={}, headers=auth(agent))  # self-assign: no email
    assert len(sent) == 1
    await client.patch(f"/tickets/{t['id']}", json={"status": "resolved"}, headers=auth(agent))
    assert sent[-1] == (employee.email, f"Ticket #{t['id']} is now resolved")
    await client.patch(f"/tickets/{t['id']}", json={"status": "closed"}, headers=auth(employee))  # own change: no email
    assert len(sent) == 2


async def test_notify_without_smtp_only_logs_and_cleans_headers():
    await notification_service.notify("a@example.com", "Hi\r\nBcc: x@example.com", "body")  # must not raise
    assert "\n" not in notification_service._clean("a\r\nb") and "\r" not in notification_service._clean("a\r\nb")


# ---------- lockout & password ----------
async def login(client, email, password):
    return await client.post("/auth/login", data={"username": email, "password": password})


async def test_account_locks_after_repeated_failures_and_admin_can_unlock(client, employee, admin):
    for _ in range(5):
        assert (await login(client, employee.email, "wrong-password")).status_code == 401
    locked = await login(client, employee.email, PASSWORD)  # even the right password is refused
    assert locked.status_code == 423 and "locked" in locked.json()["detail"]
    assert (await client.patch(f"/users/{employee.id}", json={"unlock": True}, headers=auth(admin))).status_code == 200
    assert (await login(client, employee.email, PASSWORD)).status_code == 200


async def test_failure_counter_resets_after_success(client, employee):
    for _ in range(3):
        await login(client, employee.email, "wrong-password")
    assert (await login(client, employee.email, PASSWORD)).status_code == 200
    for _ in range(3):
        assert (await login(client, employee.email, "wrong-password")).status_code == 401  # not locked


async def test_change_password(client, employee):
    url, h = "/users/me/password", auth(employee)
    assert (
        await client.post(url, json={"current_password": "nope", "new_password": "NewPassword1"}, headers=h)
    ).status_code == 400
    assert (
        await client.post(url, json={"current_password": PASSWORD, "new_password": PASSWORD}, headers=h)
    ).status_code == 400
    assert (
        await client.post(url, json={"current_password": PASSWORD, "new_password": "short"}, headers=h)
    ).status_code == 422
    assert (
        await client.post(url, json={"current_password": PASSWORD, "new_password": "NewPassword1"})
    ).status_code == 401
    assert (
        await client.post(url, json={"current_password": PASSWORD, "new_password": "NewPassword1"}, headers=h)
    ).status_code == 204
    assert (await login(client, employee.email, PASSWORD)).status_code == 401
    assert (await login(client, employee.email, "NewPassword1")).status_code == 200


# ---------- CSV export ----------
async def test_csv_export(client, employee, agent, make_ticket):
    await make_ticket(employee, title="=HYPERLINK(1)", description="line one, with comma")
    await make_ticket(employee, title="Normal ticket")
    assert (await client.get("/tickets/export.csv", headers=auth(employee))).status_code == 403
    assert (await client.get("/tickets/export.csv")).status_code == 401
    r = await client.get("/tickets/export.csv", headers=auth(agent))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["id", "title", "description", "status"] and len(rows) == 3
    titles = {row[1] for row in rows[1:]}
    assert "'=HYPERLINK(1)" in titles and "Normal ticket" in titles  # formula neutralised
    assert [row[2] for row in rows[1:] if row[1].startswith("'")] == ["line one, with comma"]
    only_closed = list(
        csv.reader(io.StringIO((await client.get("/tickets/export.csv?status=closed", headers=auth(agent))).text))
    )
    assert len(only_closed) == 1  # header only
