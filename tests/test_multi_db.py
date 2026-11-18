"""Requests reach the right database.

`pyodbc.connect` is replaced with a fake, so these run without any ODBC
driver. The fake records which connection string each request opened.
"""

import pyodbc
import pytest

from tests.fakes import FakeConnection


@pytest.fixture
def odbc(monkeypatch):
    """Patch pyodbc.connect; returns the list of (conn_str, connection) opened."""
    opened = []

    def fake_connect(conn_str, **kwargs):
        conn = FakeConnection(rows=[(i,) for i in range(10)])
        opened.append((conn_str, conn))
        return conn

    monkeypatch.setattr(pyodbc, "connect", fake_connect)
    return opened


@pytest.mark.parametrize(
    "prefix,conn_str",
    [
        ("primary", "DSN=test-primary-dsn;"),
        ("legacy", "DSN=test-legacy-dsn;UID=test-user;PWD=test-secret;"),
    ],
)
def test_each_prefix_opens_its_own_connection(client, auth_headers, odbc, prefix, conn_str):
    assert client.get(f"/{prefix}/tables", headers=auth_headers).status_code == 200
    assert [c for c, _ in odbc] == [conn_str]
    assert odbc[0][1].closed


def test_unknown_prefix_is_404_and_never_connects(client, auth_headers, odbc):
    assert client.get("/nope/tables", headers=auth_headers).status_code == 404
    assert client.get("/tables", headers=auth_headers).status_code == 404
    assert odbc == []


def test_limit_paging_is_pushed_to_the_engine(client, auth_headers, odbc):
    resp = client.get("/primary/tables/T?limit=3&offset=2", headers=auth_headers)
    assert resp.status_code == 200
    assert odbc[0][1].cursor_obj.executed[-1] == "SELECT * FROM T LIMIT 3 OFFSET 2"


def test_client_paging_never_sends_limit_to_the_engine(client, auth_headers, odbc):
    resp = client.get("/legacy/tables/T?limit=3&offset=2", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [r["ID"] for r in body["rows"]] == [2, 3, 4]
    assert body["total"] == 10
    assert all("LIMIT" not in sql for sql in odbc[0][1].cursor_obj.executed)


def test_client_paging_past_the_end_returns_no_rows(client, auth_headers, odbc):
    resp = client.get("/legacy/tables/T?offset=50", headers=auth_headers)
    assert resp.json()["rows"] == []


def test_health_db_reports_every_database(client, odbc):
    resp = client.get("/health/db")
    assert resp.status_code == 200
    assert resp.json()["databases"] == {"primary": {"status": "ok"}, "legacy": {"status": "ok"}}
    # primary runs its SELECT 1 probe; legacy is connect-only.
    executed = {c: conn.cursor_obj.executed for c, conn in odbc}
    assert executed["DSN=test-primary-dsn;"] == ["SELECT 1"]
    assert executed["DSN=test-legacy-dsn;UID=test-user;PWD=test-secret;"] == []


def test_one_database_down_is_503_without_hiding_the_other(client, monkeypatch):
    def fake_connect(conn_str, **kwargs):
        if "legacy" in conn_str:
            raise pyodbc.Error("08001", f"login failed for {conn_str}")
        return FakeConnection(rows=[])

    monkeypatch.setattr(pyodbc, "connect", fake_connect)

    resp = client.get("/health/db")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["databases"]["primary"] == {"status": "ok"}
    assert body["databases"]["legacy"]["status"] == "unreachable"
    # The password must never leak through a driver error message.
    assert "test-secret" not in resp.text

    assert client.get("/primary/health").status_code == 200
    down = client.get("/legacy/health")
    assert down.status_code == 503
    assert "test-secret" not in down.text
