async def test_web_ui_is_served(client):
    r = await client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert '<script src="/static/app.js">' in r.text
    # the UI may load only its own files: no inline scripts, no third-party hosts
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe" not in csp
    assert r.headers["x-frame-options"] == "DENY" and "x-request-id" in r.headers


async def test_static_assets(client):
    js = await client.get("/static/app.js")
    css = await client.get("/static/app.css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert (await client.get("/static/../app/main.py")).status_code == 404  # no path traversal
    assert (await client.get("/static/nope.js")).status_code == 404


async def test_api_docs_still_available(client):
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/openapi.json")).status_code == 200
