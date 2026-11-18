"""ODBC 2 and 3 expose the same SQLColumns size field under different names."""

from collections import namedtuple
from unittest.mock import MagicMock

import pyodbc
import pytest


@pytest.mark.parametrize("prefix", ["primary", "legacy"])
@pytest.mark.parametrize("size_name", ["precision", "column_size"])
def test_schema_supports_both_odbc_metadata_versions(
    client, auth_headers, monkeypatch, prefix, size_name
):
    column_type = namedtuple(
        "Column",
        f"catalog schema table column_name data_type type_name {size_name} length scale radix nullable",
    )
    column = column_type(None, None, "T", "NAME", 12, "VARCHAR", 42, 42, None, None, 1)
    connection = MagicMock()
    connection.cursor.return_value.columns.return_value = [column]
    monkeypatch.setattr(pyodbc, "connect", lambda *args, **kwargs: connection)
    response = client.get(f"/{prefix}/tables/T/schema", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {
        "table": "T",
        "columns": [{"name": "NAME", "type": "VARCHAR", "size": 42, "nullable": True}],
    }
