"""API-key enforcement on protected routers.

These tests do NOT hit the database. The `verify_key` dependency fires
before `get_db`, so a 401 short-circuits the request before any ODBC
connection is attempted. Tests therefore run in CI without a live DSN.
"""

import pytest

_DATA_ENDPOINTS = [
    ("GET", "/tables"),
    ("GET", "/tables/ANY/schema"),
    ("GET", "/tables/ANY"),
    ("GET", "/tables/ANY/1"),
    ("POST", "/tables/ANY"),
    ("PUT", "/tables/ANY/1"),
    ("PATCH", "/tables/ANY/1"),
    ("POST", "/query"),
]

PROTECTED_ENDPOINTS = [
    (method, prefix + path)
    for prefix in ("/primary", "/legacy")
    for (method, path) in _DATA_ENDPOINTS
]


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_missing_api_key_is_rejected(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401, f"{method} {path} should require API key"


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_wrong_api_key_is_rejected(client, method, path):
    resp = client.request(method, path, headers={"X-Api-Key": "definitely-wrong"})
    assert resp.status_code == 401, f"{method} {path} should reject wrong key"


def test_health_endpoints_do_not_require_key(client):
    """Liveness/readiness endpoints must remain reachable without auth."""
    # /health/db will likely fail (no real DSN in tests) — but it must NOT
    # fail with 401. Anything else (200 or 503) proves auth wasn't required.
    for path in ("/health/db", "/primary/health", "/legacy/health"):
        resp = client.get(path)
        assert resp.status_code != 401, path
