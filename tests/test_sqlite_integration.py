"""End-to-end run against a real ODBC driver (SQLite).

Everything else in the suite uses a fake driver. This module opens real
ODBC connections to a throwaway SQLite file, so it proves the statements
the API builds are accepted by an actual engine. It is skipped when the
SQLite ODBC driver is not installed:

    Debian/Ubuntu:  sudo apt-get install unixodbc libsqliteodbc
    macOS:          brew install sqliteodbc   (then register it in odbcinst.ini)
"""

import sqlite3

import pyodbc
import pytest
from fastapi.testclient import TestClient

from api.config import load_databases
from app import create_app

# Captured at import time, before conftest's per-test block replaces it.
REAL_CONNECT = pyodbc.connect

DRIVER = next((d for d in pyodbc.drivers() if "sqlite3" in d.lower()), None)

pytestmark = pytest.mark.skipif(DRIVER is None, reason="SQLite ODBC driver is not installed")


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    path = tmp_path / "shop.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        INSERT INTO customers VALUES
            (1, 'Ada', 'London'), (2, 'Grace', 'New York'), (3, 'Linus', 'Helsinki'),
            (4, 'Margaret', 'Boston'), (5, 'Dennis', 'New York');
        CREATE TABLE "Order Details" ("Order ID" INTEGER PRIMARY KEY, qty INTEGER);
        INSERT INTO "Order Details" VALUES (10, 3);
        """
    )
    db.commit()
    db.close()
    monkeypatch.setattr(pyodbc, "connect", REAL_CONNECT)

    def build(paging="auto"):
        env = {"ODBC_CONN": f"Driver={{{DRIVER}}};Database={path};", "ODBC_PAGING": paging}
        return TestClient(create_app(databases=load_databases(env), allow_delete=True))

    return build


def test_health_and_discovery(make_client, auth_headers):
    client = make_client()
    assert client.get("/health/db").status_code == 200
    tables = client.get("/tables", headers=auth_headers).json()["tables"]
    assert {"customers", "Order Details"} <= set(tables)
    schema = client.get("/tables/customers/schema", headers=auth_headers).json()
    assert [c["name"] for c in schema["columns"]] == ["id", "name", "city"]


@pytest.mark.parametrize("paging", ["auto", "limit", "client"])
def test_ordered_paging_returns_the_same_page_in_every_mode(make_client, auth_headers, paging):
    client = make_client(paging)
    resp = client.get("/tables/customers?order_by=id&limit=2&offset=1", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert [r["id"] for r in body["rows"]] == [2, 3]


def test_filter_and_query_with_the_read_key(make_client, auth_headers):
    client = make_client()
    rows = client.get(
        "/tables/customers", params={"filter": "city='New York'"}, headers=auth_headers
    ).json()
    assert rows["total"] == 2
    resp = client.post(
        "/query",
        headers=auth_headers,
        json={"sql": "SELECT name FROM customers WHERE id = ?", "params": [3]},
    )
    assert resp.json() == {"rows": [{"name": "Linus"}], "count": 1}


def test_create_read_update_delete(make_client, auth_headers, write_auth_headers):
    client = make_client()
    created = client.post(
        "/tables/customers",
        headers=write_auth_headers,
        json={"data": {"id": 6, "name": "Barbara", "city": "Boston"}},
    )
    assert created.status_code == 201, created.text

    row = client.get("/tables/customers/6?pk_col=id", headers=auth_headers).json()["row"]
    assert row == {"id": 6, "name": "Barbara", "city": "Boston"}

    patched = client.patch(
        "/tables/customers/6?pk_col=id", headers=write_auth_headers, json={"data": {"city": "MIT"}}
    )
    assert patched.status_code == 200, patched.text
    row = client.get("/tables/customers/6?pk_col=id", headers=auth_headers).json()["row"]
    assert row["city"] == "MIT"

    assert client.delete("/tables/customers/6?pk_col=id", headers=auth_headers).status_code == 403
    deleted = client.delete("/tables/customers/6?pk_col=id", headers=write_auth_headers)
    assert deleted.status_code == 200, deleted.text
    assert client.get("/tables/customers/6?pk_col=id", headers=auth_headers).status_code == 404
    assert (
        client.patch(
            "/tables/customers/6?pk_col=id",
            headers=write_auth_headers,
            json={"data": {"city": "x"}},
        ).status_code
        == 404
    )


def test_names_with_spaces_are_quoted(make_client, auth_headers):
    client = make_client()
    resp = client.get("/tables/Order Details/10?pk_col=Order ID", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["row"] == {"Order ID": 10, "qty": 3}
