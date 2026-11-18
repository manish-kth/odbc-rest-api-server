"""Generic CRUD endpoints over any table.

The DELETE endpoint lives in `delete.py` and is only mounted when
`ALLOW_DELETE=true`.
"""

from typing import Optional

import pyodbc
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api.database import get_db
from api.dialect import Dialect, get_dialect
from api.schemas import RowData
from api.security import authorize_filter, require_write_key, verify_key
from api.utils import build_order_by, db_error, row_exists, rows_to_dicts, sql_name

router = APIRouter(dependencies=[Depends(verify_key)])

_PK_COL = Query(..., description="Primary key column name for this table")


# ---------------------------------------------------------------------------
# READ — list rows
# ---------------------------------------------------------------------------


@router.get("/tables/{table}", dependencies=[Depends(authorize_filter)])
def list_rows(
    table: str,
    limit: int = Query(default=100, ge=1, le=5000, description="Max rows to return"),
    offset: int = Query(default=0, ge=0, description="Row offset for paging"),
    order_by: Optional[str] = Query(
        default=None,
        max_length=1000,
        description="Comma-separated columns with optional ASC/DESC (default ASC), e.g. last_name, id. Include a unique tie-breaker for stable pages.",
    ),
    filter: Optional[str] = Query(
        default=None,
        description="Raw SQL WHERE clause, e.g. status='open'",
    ),
    conn: pyodbc.Connection = Depends(get_db),
    dialect: Dialect = Depends(get_dialect),
):
    """
    List rows from any table with optional pagination, sorting and filtering.

    `filter` is a raw SQL WHERE clause and works with either key. With the
    read key it must keep the statement a single read-only SELECT (no `;`,
    comments, or write keywords) or the request is refused with 403.

    `total` is the number of matching rows before paging; `rows` holds the
    requested page. Use `order_by` to sort before paging and include a
    unique column as the final sort field to break ties — without it the
    row order is whatever the database returns.

    Examples:
    - `/tables/customers?order_by=id&limit=50`
    - `/tables/customers?order_by=last_name,id&limit=5&offset=5`
    - `/tables/orders?filter=status='open'`
    """
    name = sql_name(table, dialect.quote)
    where = f" WHERE {filter}" if filter else ""
    ordering = build_order_by(order_by)

    paging = dialect.paging
    if paging == "offset_fetch" and not ordering:
        # OFFSET ... FETCH is only valid after ORDER BY.
        paging = "client"

    try:
        cursor = conn.cursor()

        # Count first so the response can still report `total` accurately.
        cursor.execute(f"SELECT COUNT(*) FROM {name}{where}")
        total = cursor.fetchone()[0]

        select = f"SELECT * FROM {name}{where}{ordering}"
        # limit and offset come from FastAPI's int-validated Query() params,
        # so inlining them is safe (no injection vector).
        if paging == "limit":
            cursor.execute(f"{select} LIMIT {limit} OFFSET {offset}")
            rows = rows_to_dicts(cursor)
        elif paging == "offset_fetch":
            cursor.execute(f"{select} OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY")
            rows = rows_to_dicts(cursor)
        elif offset >= total:
            rows = []
        else:
            # Page in the cursor: skip and cap rows so at most `limit` rows
            # are ever materialised in Python.
            cursor.execute(select)
            if offset:
                cursor.skip(offset)
            rows = rows_to_dicts(cursor, limit)

        return {
            "table": table,
            "total": total,
            "offset": offset,
            "limit": limit,
            "rows": rows,
        }
    except pyodbc.Error as e:
        raise db_error(e) from e


# ---------------------------------------------------------------------------
# READ — single row by PK
# ---------------------------------------------------------------------------


@router.get("/tables/{table}/{pk_value}")
def get_row(
    table: str,
    pk_value: str,
    pk_col: str = _PK_COL,
    conn: pyodbc.Connection = Depends(get_db),
    dialect: Dialect = Depends(get_dialect),
):
    """
    Fetch a single row by its primary key value.

    Example: `/tables/customers/192?pk_col=id`
    """
    name = sql_name(table, dialect.quote)
    key = sql_name(pk_col, dialect.quote)
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {name} WHERE {key} = ?", str(pk_value))
        rows = rows_to_dicts(cursor)
        if not rows:
            raise HTTPException(404, detail=f"Row with {pk_col}={pk_value} not found in '{table}'")
        return {"table": table, "row": rows[0]}
    except pyodbc.Error as e:
        raise db_error(e) from e


# ---------------------------------------------------------------------------
# CREATE — insert a new row
# ---------------------------------------------------------------------------


@router.post("/tables/{table}", status_code=201, dependencies=[Depends(require_write_key)])
def create_row(
    table: str,
    body: RowData = Body(
        ..., examples=[{"data": {"name": "Ada Lovelace", "email": "ada@example.com"}}]
    ),
    conn: pyodbc.Connection = Depends(get_db),
    dialect: Dialect = Depends(get_dialect),
):
    """
    Insert a new row into a table.

    Send a JSON body mapping column names to values:
    ```json
    {"data": {"name": "Ada Lovelace", "email": "ada@example.com"}}
    ```
    """
    name = sql_name(table, dialect.quote)
    if not body.data:
        raise HTTPException(400, detail="Request body 'data' must not be empty")

    columns = ", ".join(sql_name(col, dialect.quote) for col in body.data)
    placeholders = ", ".join("?" for _ in body.data)
    sql = f"INSERT INTO {name} ({columns}) VALUES ({placeholders})"

    try:
        cursor = conn.cursor()
        cursor.execute(sql, list(body.data.values()))
        return {
            "message": "Row inserted successfully",
            "table": table,
            "data": body.data,
        }
    except pyodbc.Error as e:
        raise db_error(e) from e


# ---------------------------------------------------------------------------
# UPDATE — PUT and PATCH both set exactly the fields that were sent
# ---------------------------------------------------------------------------


def _update_row(
    conn: pyodbc.Connection,
    dialect: Dialect,
    table: str,
    pk_col: str,
    pk_value: str,
    body: RowData,
) -> None:
    name = sql_name(table, dialect.quote)
    key = sql_name(pk_col, dialect.quote)
    if not body.data:
        raise HTTPException(400, detail="Request body 'data' must not be empty")
    set_clause = ", ".join(f"{sql_name(col, dialect.quote)} = ?" for col in body.data)

    try:
        cursor = conn.cursor()

        # Verify the row exists first — rowcount is unreliable on some drivers.
        if not row_exists(cursor, name, key, pk_value):
            raise HTTPException(404, detail=f"Row with {pk_col}={pk_value} not found in '{table}'")

        cursor.execute(
            f"UPDATE {name} SET {set_clause} WHERE {key} = ?",
            list(body.data.values()) + [str(pk_value)],
        )
    except pyodbc.Error as e:
        raise db_error(e) from e


@router.put("/tables/{table}/{pk_value}", dependencies=[Depends(require_write_key)])
def replace_row(
    table: str,
    pk_value: str,
    body: RowData = Body(
        ..., examples=[{"data": {"name": "Ada King", "email": "ada.king@example.com"}}]
    ),
    pk_col: str = _PK_COL,
    conn: pyodbc.Connection = Depends(get_db),
    dialect: Dialect = Depends(get_dialect),
):
    """
    Full update — updates ALL supplied fields for the matching row.

    Example:
    ```json
    {"data": {"name": "Ada King", "email": "ada.king@example.com"}}
    ```
    """
    _update_row(conn, dialect, table, pk_col, pk_value, body)
    return {
        "message": "Row updated successfully",
        "table": table,
        pk_col: pk_value,
        "updated_fields": list(body.data.keys()),
        "data": body.data,
    }


@router.patch("/tables/{table}/{pk_value}", dependencies=[Depends(require_write_key)])
def patch_row(
    table: str,
    pk_value: str,
    body: RowData = Body(..., examples=[{"data": {"email": "new@example.com"}}]),
    pk_col: str = _PK_COL,
    conn: pyodbc.Connection = Depends(get_db),
    dialect: Dialect = Depends(get_dialect),
):
    """
    Partial update — only the fields you send get updated, everything else stays the same.

    Example — update just the email:
    ```json
    {"data": {"email": "new@example.com"}}
    ```
    """
    _update_row(conn, dialect, table, pk_col, pk_value, body)
    return {
        "message": "Row patched successfully",
        "table": table,
        pk_col: pk_value,
        "updated_fields": list(body.data.keys()),
    }
