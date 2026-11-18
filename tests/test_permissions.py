"""Permission boundaries use a fake driver, including all write paths."""

from unittest.mock import MagicMock

import pyodbc
import pytest

from api import security


@pytest.fixture
def database(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.tables.return_value = []
    cursor.description = [("ID",)]
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [(1,)]
    cursor.fetchmany.return_value = [(1,)]
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(pyodbc, "connect", connect)
    return connect, cursor


WRITE_REQUESTS = [
    ("POST", "/tables/T", {"data": {"ID": 1}}),
    ("PUT", "/tables/T/1?pk_col=ID", {"data": {"ID": 1}}),
    ("PATCH", "/tables/T/1?pk_col=ID", {"data": {"ID": 1}}),
    ("POST", "/query", {"sql": "UPDATE T SET ID=1", "params": []}),
    ("POST", "/query", {"sql": "SELECT 1; DELETE FROM T", "params": []}),
]


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize("method,path,body", WRITE_REQUESTS)
def test_read_key_cannot_reach_write_capable_handlers(
    client, auth_headers, database, prefix, method, path, body
):
    response = client.request(method, f"/{prefix}{path}", headers=auth_headers, json=body)
    assert response.status_code == 403
    database[0].assert_not_called()


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize(
    "filter_sql",
    [
        "1=1; DELETE FROM T",
        "ID=1 -- '\n; DELETE FROM T -- '",
        "ID IN (SELECT ID INTO U FROM T)",
        "ID=1 /* x */",
    ],
)
def test_read_key_cannot_inject_sql_through_filter(
    client, auth_headers, database, prefix, filter_sql
):
    response = client.get(
        f"/{prefix}/tables/T", params={"filter": filter_sql}, headers=auth_headers
    )
    assert response.status_code == 403
    database[0].assert_not_called()


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize("headers_fixture", ["auth_headers", "write_auth_headers"])
@pytest.mark.parametrize(
    "path",
    [
        "/tables",
        "/tables/T",
        "/tables/T?filter=",
        "/tables/T?filter=ID%3D1",
        "/tables/T?filter=NAME%3D'DELETE; me' AND QINACTIVE%3D'N'",
        "/tables/T/1?pk_col=ID",
    ],
)
def test_both_keys_can_read(client, request, database, prefix, headers_fixture, path):
    response = client.get(f"/{prefix}{path}", headers=request.getfixturevalue(headers_fixture))
    assert response.status_code == 200
    assert database[0].called


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize(
    "method,path,body,sql_prefix,status",
    [
        ("POST", "/tables/T", {"data": {"ID": 1}}, "INSERT", 201),
        ("PUT", "/tables/T/1?pk_col=ID", {"data": {"ID": 1}}, "UPDATE", 200),
        ("PATCH", "/tables/T/1?pk_col=ID", {"data": {"ID": 1}}, "UPDATE", 200),
        ("POST", "/query", {"sql": "UPDATE T SET ID=1"}, "UPDATE", 200),
        ("POST", "/query", {"sql": "SELECT ID FROM T"}, "SELECT", 200),
        ("GET", "/tables/T?filter=ID%3D1", None, "SELECT", 200),
    ],
)
def test_write_key_allows_operations_using_only_a_fake_driver(
    client, write_auth_headers, database, prefix, method, path, body, sql_prefix, status
):
    response = client.request(method, f"/{prefix}{path}", headers=write_auth_headers, json=body)
    assert response.status_code == status
    assert database[1].execute.call_args.args[0].startswith(sql_prefix)


@pytest.mark.parametrize("header", [None, "", "unknown-key", "test-write-api-key"])
def test_unset_write_key_does_not_grant_write_access(client, monkeypatch, database, header):
    monkeypatch.setattr(security, "WRITE_API_KEY", "")
    headers = {"X-Api-Key": header} if header is not None else {}
    response = client.post("/primary/query", headers=headers, json={"sql": "SELECT 1"})
    assert response.status_code == 401
    database[0].assert_not_called()


def test_read_key_stays_read_only_when_write_key_is_unset(
    client, monkeypatch, database, auth_headers
):
    monkeypatch.setattr(security, "WRITE_API_KEY", "")
    response = client.post(
        "/primary/query", headers=auth_headers, json={"sql": "UPDATE T SET ID=1"}
    )
    assert response.status_code == 403
    database[0].assert_not_called()
