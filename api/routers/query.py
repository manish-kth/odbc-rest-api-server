"""Raw-SQL passthrough endpoint."""

import pyodbc
from fastapi import APIRouter, Body, Depends, HTTPException

from api.database import get_db
from api.schemas import SqlPayload
from api.security import verify_key
from api.sql_guard import ensure_read_only_sql
from api.utils import db_error, rows_to_dicts

router = APIRouter(dependencies=[Depends(verify_key)])


def authorized_query(
    body: SqlPayload = Body(
        ...,
        examples=[{"sql": "SELECT * FROM customers WHERE country = ?", "params": ["CA"]}],
    ),
    access: str = Depends(verify_key),
) -> SqlPayload:
    """Validate the statement against the caller's key.

    Declared before `get_db` in the handler so a refused statement never
    opens an ODBC connection.
    """
    if not body.sql.strip():
        raise HTTPException(400, detail="SQL statement is required")
    if access != "write":
        ensure_read_only_sql(body.sql)
    return body


@router.post("/query")
def raw_query(
    body: SqlPayload = Depends(authorized_query),
    conn: pyodbc.Connection = Depends(get_db),
):
    """
    Execute a SQL statement with optional parameterised values.

    - **Read key (`API_KEY`)**: a single `SELECT` (or `WITH ... SELECT`)
      only. Multiple statements, SQL comments, `SELECT ... INTO`, and any
      data- or schema-changing keyword are refused with 403.
    - **Write key (`WRITE_API_KEY`)**: any statement.

    The SQL is passed to the driver as written, so use the syntax of the
    database behind it. `limit`, `offset` and `order_by` do not apply here.

    Always use `?` placeholders with `params` instead of string formatting
    to prevent SQL injection.

    SELECT example:
    ```json
    {"sql": "SELECT * FROM customers WHERE country = ?", "params": ["CA"]}
    ```

    UPDATE example (write key):
    ```json
    {"sql": "UPDATE customers SET email = ? WHERE id = ?", "params": ["new@example.com", 192]}
    ```
    """
    try:
        cursor = conn.cursor()
        cursor.execute(body.sql, body.params or [])
        # A statement that produces a result set has a description; this
        # also covers WITH ... SELECT, which a "starts with SELECT" test misses.
        if cursor.description is not None:
            rows = rows_to_dicts(cursor)
            return {"rows": rows, "count": len(rows)}
        return {"message": "Query executed successfully"}
    except pyodbc.Error as e:
        raise db_error(e) from e
