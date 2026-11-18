"""Ordering is validated and applied before paging on either database."""

from unittest.mock import MagicMock, call

import pyodbc
import pytest


@pytest.fixture
def cursor(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = (10,)
    cursor.description = [("ID",)]
    cursor.fetchall.return_value = [(3,), (4,)]
    cursor.fetchmany.return_value = [(3,), (4,)]
    monkeypatch.setattr(pyodbc, "connect", lambda *args, **kwargs: connection)
    return cursor


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize("headers_fixture", ["auth_headers", "write_auth_headers"])
@pytest.mark.parametrize(
    "order_by,expected",
    [
        ("ID", "ID ASC"),
        ("Name desc, ID", "Name DESC, ID ASC"),
        (" Name asc , ID DESC ", "Name ASC, ID DESC"),
    ],
)
def test_ordering_precedes_pagination(
    client, request, cursor, prefix, headers_fixture, order_by, expected
):
    response = client.get(
        f"/{prefix}/tables/T",
        params={"order_by": order_by, "limit": 2, "offset": 3},
        headers=request.getfixturevalue(headers_fixture),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 10
    assert response.json()["offset"] == 3
    sql = f"SELECT * FROM T ORDER BY {expected}"
    if prefix == "primary":
        sql += " LIMIT 2 OFFSET 3"
        cursor.skip.assert_not_called()
    else:
        assert cursor.mock_calls[-3:] == [call.execute(sql), call.skip(3), call.fetchmany(2)]
    assert cursor.execute.call_args_list == [call("SELECT COUNT(*) FROM T"), call(sql)]


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize(
    "order_by",
    [
        "",
        " ",
        "ID,",
        ",ID",
        "ID,,Name",
        "ID; DELETE FROM T",
        "ID DESC --",
        "ID /* comment */",
        "ID NULLS FIRST",
        "LOWER(Name)",
        "(SELECT ID FROM T)",
        "T.ID",
        "1",
        "ID INTO T",
    ],
)
def test_invalid_ordering_never_executes_sql(client, auth_headers, cursor, prefix, order_by):
    response = client.get(
        f"/{prefix}/tables/T", params={"order_by": order_by}, headers=auth_headers
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
def test_ordering_is_combined_with_filter_but_not_count(client, write_auth_headers, cursor, prefix):
    response = client.get(
        f"/{prefix}/tables/T",
        params={"filter": "ID>0", "order_by": "ID DESC", "limit": 2},
        headers=write_auth_headers,
    )
    assert response.status_code == 200
    sql = "SELECT * FROM T WHERE ID>0 ORDER BY ID DESC"
    if prefix == "primary":
        sql += " LIMIT 2 OFFSET 0"
    assert cursor.execute.call_args_list == [call("SELECT COUNT(*) FROM T WHERE ID>0"), call(sql)]


def test_overlong_ordering_is_rejected(client, auth_headers, cursor):
    response = client.get(
        "/primary/tables/T", params={"order_by": "A" * 1001}, headers=auth_headers
    )
    assert response.status_code == 422
    cursor.execute.assert_not_called()
