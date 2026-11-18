"""DELETE endpoint — off unless `ALLOW_DELETE=true`.

`app.py` only mounts this router when the setting is on, and every request
needs the write key. Deletes run in autocommit mode and cannot be undone
through this API, so enable it deliberately.
"""

import pyodbc
from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_db
from api.dialect import Dialect, get_dialect
from api.security import require_write_key
from api.utils import db_error, row_exists, sql_name

router = APIRouter(dependencies=[Depends(require_write_key)])


@router.delete("/tables/{table}/{pk_value}")
def delete_row(
    table: str,
    pk_value: str,
    pk_col: str = Query(..., description="Primary key column name for this table"),
    conn: pyodbc.Connection = Depends(get_db),
    dialect: Dialect = Depends(get_dialect),
):
    """
    Delete a single row by its primary key value.

    Example: `DELETE /tables/customers/192?pk_col=id`
    """
    name = sql_name(table, dialect.quote)
    key = sql_name(pk_col, dialect.quote)
    try:
        cursor = conn.cursor()

        # Verify the row exists first — rowcount is unreliable on some drivers.
        if not row_exists(cursor, name, key, pk_value):
            raise HTTPException(404, detail=f"Row with {pk_col}={pk_value} not found in '{table}'")

        cursor.execute(f"DELETE FROM {name} WHERE {key} = ?", str(pk_value))
        return {"message": "Row deleted successfully", "table": table, pk_col: pk_value}
    except pyodbc.Error as e:
        raise db_error(e) from e
