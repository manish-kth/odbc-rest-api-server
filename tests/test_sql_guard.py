"""The read key may run one read-only SELECT through /query and nothing else."""

from unittest.mock import MagicMock

import pyodbc
import pytest
from fastapi import HTTPException

from api.sql_guard import ensure_read_only_sql

ALLOWED = [
    "SELECT 1",
    "select * from customers where country = ?",
    "  SELECT A, B FROM T ORDER BY A DESC;",
    "SELECT COUNT(*) AS N FROM T GROUP BY A HAVING COUNT(*) > 1",
    "SELECT * FROM T WHERE NOTE = 'please DELETE; then UPDATE -- ok /* fine */'",
    "SELECT * FROM T WHERE NAME = 'O''Brien; DROP'",
    'SELECT "Update", "Into" FROM T',
    "SELECT UPDATE_DATE, CREATED_BY, INTOXICATED FROM T",
    "SELECT A FROM T UNION SELECT A FROM U",
    "(SELECT A FROM T) UNION (SELECT A FROM U)",
    "SELECT * FROM T WHERE A IN (SELECT A FROM U)",
    "WITH X AS (SELECT A FROM T) SELECT * FROM X",
    "SELECT REPLACE(NAME, 'a', 'b') FROM T",
]

REJECTED = [
    "UPDATE T SET A = 1",
    "DELETE FROM T",
    "INSERT INTO T (A) VALUES (1)",
    "DROP TABLE T",
    "CALL SOME_PROC()",
    "EXEC SOME_PROC",
    "SELECTED",
    "SELECT 1; DELETE FROM T",
    "SELECT 1;\nDELETE FROM T",
    "SELECT * INTO T2 FROM T",
    "SELECT *\tINTO\nT2 FROM T",
    "SELECT * FROM T FOR UPDATE",
    "WITH X AS (DELETE FROM T RETURNING A) SELECT * FROM X",
    "SELECT 1 -- trailing comment",
    "SELECT 1 /* comment */",
    "SELECT/**/1",
    # A quote hidden in a comment must not swallow the statement after it.
    "SELECT 1 -- '\n; DELETE FROM T -- '",
    "SELECT 1 /* ' */; DELETE FROM T /* ' */",
    # Unterminated literals.
    "SELECT 'abc ; DELETE FROM T",
    'SELECT "abc ; DELETE FROM T',
    "SELECT * FROM T WHERE A = 'x' ; DELETE FROM T WHERE B = 'y'",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_read_only_statements_pass(sql):
    ensure_read_only_sql(sql)


@pytest.mark.parametrize("sql", REJECTED)
def test_everything_else_is_refused(sql):
    with pytest.raises(HTTPException) as exc:
        ensure_read_only_sql(sql)
    assert exc.value.status_code == 403


@pytest.fixture
def connect(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.description = [("ID",)]
    cursor.fetchall.return_value = [(1,)]
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(pyodbc, "connect", connect)
    return connect


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
def test_read_key_can_select_through_query(client, auth_headers, connect, prefix):
    resp = client.post(
        f"/{prefix}/query",
        headers=auth_headers,
        json={"sql": "SELECT ID FROM T WHERE ID = ?", "params": [1]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"rows": [{"ID": 1}], "count": 1}


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize(
    "sql", ["UPDATE T SET ID = 1", "SELECT 1; DELETE FROM T", "SELECT * INTO U FROM T"]
)
def test_read_key_write_attempt_never_opens_a_connection(
    client, auth_headers, connect, prefix, sql
):
    resp = client.post(f"/{prefix}/query", headers=auth_headers, json={"sql": sql})
    assert resp.status_code == 403
    connect.assert_not_called()


def test_write_key_is_not_restricted(client, write_auth_headers, connect):
    connect.return_value.cursor.return_value.description = None
    resp = client.post(
        "/primary/query", headers=write_auth_headers, json={"sql": "UPDATE T SET ID = 1 -- note"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"message": "Query executed successfully"}


def test_with_query_returns_rows(client, write_auth_headers, connect):
    resp = client.post(
        "/primary/query",
        headers=write_auth_headers,
        json={"sql": "WITH X AS (SELECT ID FROM T) SELECT * FROM X"},
    )
    assert resp.json() == {"rows": [{"ID": 1}], "count": 1}


def test_blank_sql_is_400_without_connecting(client, auth_headers, connect):
    assert (
        client.post("/primary/query", headers=auth_headers, json={"sql": "  "}).status_code == 400
    )
    connect.assert_not_called()
