"""Engine differences: paging syntax and identifier quoting.

Each test builds a single-database app (endpoints at the root) and gives
it a fake driver that reports a chosen DBMS name and quote character.
"""

import pyodbc
import pytest
from fastapi.testclient import TestClient

from api.config import load_databases
from api.dialect import paging_for
from app import create_app
from tests.fakes import FakeConnection


def serve(monkeypatch, dbms=None, quote=None, paging="auto", allow_delete=False):
    """Return (client, cursor) for an app whose driver reports `dbms`/`quote`."""
    connection = FakeConnection(rows=[(i,) for i in range(10)], dbms=dbms, quote=quote)
    monkeypatch.setattr(pyodbc, "connect", lambda *args, **kwargs: connection)
    databases = load_databases({"ODBC_DSN": "any", "ODBC_PAGING": paging})
    client = TestClient(create_app(databases=databases, allow_delete=allow_delete))
    return client, connection.cursor_obj


@pytest.mark.parametrize(
    "dbms,expected",
    [
        ("PostgreSQL", "limit"),
        ("MySQL", "limit"),
        ("SQLite", "limit"),
        ("Pervasive.SQL", "limit"),
        ("Microsoft SQL Server", "offset_fetch"),
        ("Oracle", "offset_fetch"),
        ("DB2/LINUXX8664", "offset_fetch"),
        ("Some Engine Nobody Has Heard Of", "client"),
        ("", "client"),
    ],
)
def test_paging_mode_is_chosen_from_the_dbms_name(dbms, expected):
    assert paging_for(dbms) == expected


def test_auto_paging_uses_limit_on_a_limit_engine(monkeypatch, auth_headers):
    client, cursor = serve(monkeypatch, dbms="PostgreSQL")
    resp = client.get("/tables/T?limit=3&offset=2", headers=auth_headers)
    assert resp.status_code == 200
    assert cursor.executed[-1] == "SELECT * FROM T LIMIT 3 OFFSET 2"


def test_auto_paging_uses_offset_fetch_when_ordered(monkeypatch, auth_headers):
    client, cursor = serve(monkeypatch, dbms="Microsoft SQL Server")
    resp = client.get("/tables/T?limit=3&offset=2&order_by=ID", headers=auth_headers)
    assert resp.status_code == 200
    assert cursor.executed[-1] == (
        "SELECT * FROM T ORDER BY ID ASC OFFSET 2 ROWS FETCH NEXT 3 ROWS ONLY"
    )


def test_offset_fetch_without_ordering_pages_in_the_cursor(monkeypatch, auth_headers):
    """OFFSET ... FETCH is invalid without ORDER BY, so fall back rather than fail."""
    client, cursor = serve(monkeypatch, dbms="Microsoft SQL Server")
    resp = client.get("/tables/T?limit=3&offset=2", headers=auth_headers)
    assert [r["ID"] for r in resp.json()["rows"]] == [2, 3, 4]
    assert cursor.executed[-1] == "SELECT * FROM T"


@pytest.mark.parametrize("dbms", ["Some Engine Nobody Has Heard Of", None])
def test_unknown_engine_pages_in_the_cursor(monkeypatch, auth_headers, dbms):
    client, cursor = serve(monkeypatch, dbms=dbms)
    resp = client.get("/tables/T?limit=3&offset=2", headers=auth_headers)
    assert [r["ID"] for r in resp.json()["rows"]] == [2, 3, 4]
    assert cursor.executed[-1] == "SELECT * FROM T"


def test_configured_paging_overrides_detection(monkeypatch, auth_headers):
    client, cursor = serve(monkeypatch, dbms="PostgreSQL", paging="client")
    client.get("/tables/T?limit=3", headers=auth_headers)
    assert cursor.executed[-1] == "SELECT * FROM T"


def test_schema_qualified_table_is_passed_through(monkeypatch, auth_headers):
    client, cursor = serve(monkeypatch, dbms="PostgreSQL", quote='"')
    assert client.get("/tables/sales.orders", headers=auth_headers).status_code == 200
    assert cursor.executed[0] == "SELECT COUNT(*) FROM sales.orders"


@pytest.mark.parametrize("quote,expected", [('"', '"Order Details"'), ("`", "`Order Details`")])
def test_name_with_a_space_uses_the_drivers_quote_character(
    monkeypatch, auth_headers, quote, expected
):
    client, cursor = serve(monkeypatch, dbms="PostgreSQL", quote=quote)
    resp = client.get("/tables/Order Details/7?pk_col=Order ID", headers=auth_headers)
    assert resp.status_code == 200
    assert cursor.executed[-1] == f"SELECT * FROM {expected} WHERE {quote}Order ID{quote} = ?"


def test_name_needing_quotes_is_refused_when_the_driver_has_none(monkeypatch, auth_headers):
    client, cursor = serve(monkeypatch, quote=" ")
    assert client.get("/tables/Order Details", headers=auth_headers).status_code == 400
    assert cursor.executed == []


@pytest.mark.parametrize(
    "table",
    ['T"; DROP TABLE U; --', "T; DROP TABLE U", "T`", "T]", "T'", "a.b.c.d", "T.", " T", "T(1)"],
)
def test_unsafe_table_names_never_reach_the_database(monkeypatch, auth_headers, table):
    client, cursor = serve(monkeypatch, quote='"')
    resp = client.get(f"/tables/{table}", headers=auth_headers, params={"limit": 1})
    assert resp.status_code == 400
    assert cursor.executed == []


def test_unsafe_column_names_in_a_body_are_refused(monkeypatch, write_auth_headers):
    client, cursor = serve(monkeypatch, quote='"')
    resp = client.post(
        "/tables/T", headers=write_auth_headers, json={"data": {"A) VALUES (1); --": 1}}
    )
    assert resp.status_code == 400
    assert cursor.executed == []


def test_write_statements_use_parameters_and_rendered_names(monkeypatch, write_auth_headers):
    client, cursor = serve(monkeypatch, quote='"')
    resp = client.post(
        "/tables/T", headers=write_auth_headers, json={"data": {"NAME": "x", "Unit Price": 2}}
    )
    assert resp.status_code == 201
    assert cursor.executed[-1] == 'INSERT INTO T (NAME, "Unit Price") VALUES (?, ?)'
    assert cursor.params[-1] == (["x", 2],)

    resp = client.patch(
        "/tables/T/5?pk_col=ID", headers=write_auth_headers, json={"data": {"NAME": "y"}}
    )
    assert resp.status_code == 200
    assert cursor.executed[-1] == "UPDATE T SET NAME = ? WHERE ID = ?"
    assert cursor.params[-1] == (["y", "5"],)


def test_delete_needs_the_setting_and_the_write_key(monkeypatch, auth_headers, write_auth_headers):
    client, cursor = serve(monkeypatch)
    off = client.delete("/tables/T/5?pk_col=ID", headers=write_auth_headers)
    assert off.status_code == 405
    assert cursor.executed == []

    client, cursor = serve(monkeypatch, allow_delete=True)
    assert client.delete("/tables/T/5?pk_col=ID").status_code == 401
    assert client.delete("/tables/T/5?pk_col=ID", headers=auth_headers).status_code == 403
    assert cursor.executed == []

    resp = client.delete("/tables/T/5?pk_col=ID", headers=write_auth_headers)
    assert resp.status_code == 200
    assert cursor.executed[-1] == "DELETE FROM T WHERE ID = ?"
    assert cursor.params[-1] == ("5",)


def test_database_errors_never_echo_a_password(monkeypatch, auth_headers):
    client, cursor = serve(monkeypatch)

    def fail(sql, *params):
        raise pyodbc.Error("42000", "syntax error near PWD=hunter2;")

    cursor.execute = fail
    resp = client.get("/tables/T", headers=auth_headers)
    assert resp.status_code == 400
    assert "hunter2" not in resp.text
