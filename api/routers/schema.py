"""Schema-discovery endpoints: list tables and inspect a table's columns."""

import pyodbc
from fastapi import APIRouter, Depends, HTTPException

from api.database import get_db
from api.security import verify_key
from api.utils import db_error, split_name

router = APIRouter(dependencies=[Depends(verify_key)])


@router.get("/tables")
def list_tables(conn: pyodbc.Connection = Depends(get_db)):
    """List all available tables in the database."""
    try:
        cursor = conn.cursor()
        tables = [row.table_name for row in cursor.tables(tableType="TABLE")]
        return {"tables": tables}
    except pyodbc.Error as e:
        raise db_error(e) from e


@router.get("/tables/{table}/schema")
def table_schema(table: str, conn: pyodbc.Connection = Depends(get_db)):
    """Get column names and types for a table.

    `table` may be qualified (`schema.table` or `catalog.schema.table`) when
    the same table name exists in more than one schema.
    """
    *qualifiers, table_name = split_name(table)
    lookup = {"table": table_name}
    if qualifiers:
        lookup["schema"] = qualifiers[-1]
    if len(qualifiers) == 2:
        lookup["catalog"] = qualifiers[0]
    try:
        cursor = conn.cursor()
        columns = [
            {
                "name": col.column_name,
                "type": col.type_name,
                "nullable": bool(col.nullable),
                # SQLColumns field 7 is PRECISION in ODBC 2 / COLUMN_SIZE in ODBC 3.
                "size": col[6],
            }
            for col in cursor.columns(**lookup)
        ]
        if not columns:
            raise HTTPException(404, detail=f"Table '{table}' not found")
        return {"table": table, "columns": columns}
    except pyodbc.Error as e:
        raise db_error(e) from e
