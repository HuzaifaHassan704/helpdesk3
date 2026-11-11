import json
import logging
import re

from tests.conftest import auth

ORIGIN = "https://app.example.com"


async def test_request_id_generated(client):
    r = await client.get("/health/live")
    assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])


async def test_request_id_propagated(client):
    r = await client.get("/health/live", headers={"X-Request-ID": "trace-abc-12345"})
    assert r.headers["x-request-id"] == "trace-abc-12345"


async def test_unsafe_request_id_is_replaced(client):
    for bad in ("short", "has spaces in it!!", "x" * 200, "inject\\nnew-line"):
        r = await client.get("/health/live", headers={"X-Request-ID": bad})
        assert r.headers["x-request-id"] != bad
        assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])


async def test_request_id_present_on_errors(client):
    r = await client.get("/users/me")  # 401
    assert r.status_code == 401 and "x-request-id" in r.headers
    r = await client.get("/tickets/", headers={"Authorization": "Bearer junk"})
    assert "x-request-id" in r.headers


async def test_security_headers(client):
    h = (await client.get("/health/live")).headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert "strict-transport-security" not in h  # only sent when ENVIRONMENT=production


async def test_docs_page_not_blocked_by_csp(client):
    r = await client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_cors_allows_only_configured_origin(client):
    ok = await client.options(
        "/tickets/",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "DELETE" in ok.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in ok.headers

    evil = await client.options(
        "/tickets/", headers={"Origin": "https://evil.example.net", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in evil.headers

    simple = await client.get("/health/live", headers={"Origin": "https://evil.example.net"})
    assert "access-control-allow-origin" not in simple.headers
    exposed = await client.get("/health/live", headers={"Origin": ORIGIN})
    assert "x-request-id" in exposed.headers["access-control-expose-headers"].lower()


async def test_access_log_is_structured(client, employee, caplog):
    caplog.set_level(logging.INFO)
    r = await client.get("/users/me", headers={**auth(employee), "X-Request-ID": "log-test-request-1"})
    assert r.status_code == 200
    events = [rec.msg for rec in caplog.records if isinstance(rec.msg, dict)]
    done = next(e for e in events if e["event"] == "request_completed")
    assert done["request_id"] == "log-test-request-1"
    assert done["path"] == "/users/me" and done["method"] == "GET"
    assert done["status_code"] == 200 and done["duration_ms"] >= 0
    assert done["user_id"] == employee.id and done["user_role"] == "employee"


async def test_log_lines_render_as_json(client, caplog):
    caplog.set_level(logging.INFO)
    await client.get("/users/me")  # 401 -> logged as a warning
    record = next(r for r in caplog.records if isinstance(r.msg, dict) and r.msg["event"] == "request_completed")
    formatter = next(
        h.formatter for h in logging.getLogger().handlers if type(h.formatter).__name__ == "ProcessorFormatter"
    )
    line = json.loads(formatter.format(record))
    assert line["event"] == "request_completed" and line["level"] == "warning"
    assert line["status_code"] == 401 and "timestamp" in line and line["request_id"]


async def test_failed_login_does_not_log_credentials(client, employee, caplog):
    caplog.set_level(logging.INFO)
    await client.post("/auth/login", data={"username": employee.email, "password": "super-secret-wrong"})
    blob = json.dumps([r.msg for r in caplog.records if isinstance(r.msg, dict)], default=str)
    assert "super-secret-wrong" not in blob and employee.email not in blob
    assert "login_failed" in blob


async def test_health_endpoints(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/health/ready")).json() == {"status": "ok", "database": "up"}


async def test_unhandled_exception_is_logged_with_request_id(session_factory, caplog):
    from httpx import ASGITransport, AsyncClient

    from app.main import app as fastapi_app

    async def boom():
        raise RuntimeError("kaboom")

    fastapi_app.add_api_route("/__boom", boom)
    try:
        caplog.set_level(logging.INFO)
        transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/__boom", headers={"X-Request-ID": "boom-request-123"})
        assert r.status_code == 500
        failed = next(
            rec.msg for rec in caplog.records if isinstance(rec.msg, dict) and rec.msg["event"] == "request_failed"
        )
        assert failed["request_id"] == "boom-request-123" and failed["status_code"] == 500
    finally:
        fastapi_app.router.routes = [r for r in fastapi_app.router.routes if getattr(r, "path", "") != "/__boom"]


async def test_readiness_reports_database_outage(client):
    from app.core.database import get_db
    from app.main import app as fastapi_app

    class BrokenSession:
        async def execute(self, *a, **kw):
            raise ConnectionError("db down")

    async def broken_db():
        yield BrokenSession()

    previous = fastapi_app.dependency_overrides[get_db]
    fastapi_app.dependency_overrides[get_db] = broken_db
    try:
        r = await client.get("/health/ready")
        assert r.status_code == 503 and r.json()["database"] == "down"
        assert (await client.get("/health/live")).status_code == 200  # liveness is independent of the DB
    finally:
        fastapi_app.dependency_overrides[get_db] = previous
