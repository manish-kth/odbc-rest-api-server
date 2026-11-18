"""Liveness endpoint must always answer 200 — no DB, no auth, no surprises."""


def test_root_returns_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["databases"] == ["primary", "legacy"]
    assert "version" in body


def test_root_does_not_require_api_key(client):
    """Monitors / load balancers must reach `/` without holding the key."""
    resp = client.get("/")
    assert resp.status_code == 200
