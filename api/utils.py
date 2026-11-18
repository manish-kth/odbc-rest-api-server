"""Shared utilities used across routers."""

import re
from typing import Any, Dict, List, Optional

import pyodbc
from fastapi import HTTPException

from api.database import scrub

# A name that can be written into SQL as it is.
_PLAIN_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*", re.ASCII)
# A name that is safe once quoted: word characters plus a few separators,
# and nothing that could close a quote (" ` ] ') or start a new statement.
_QUOTABLE_NAME_RE = re.compile(r"[\w$# -]+")


def rows_to_dicts(cursor: pyodbc.Cursor, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Convert cursor rows to a list of dicts, stripping trailing whitespace.

    With `limit`, at most that many rows are fetched from the cursor.
    """
    columns = [col[0] for col in cursor.description]
    result = []
    for row in cursor.fetchall() if limit is None else cursor.fetchmany(limit):
        record = {}
        for col, val in zip(columns, row, strict=True):
            if isinstance(val, str):
                val = val.strip()
            record[col] = val
        result.append(record)
    return result


def split_name(name: str) -> List[str]:
    """Split `catalog.schema.table` into its validated parts.

    Raises HTTP 400 for anything that could not be a table or column name,
    which is what keeps names from being an SQL-injection vector.
    """
    parts = name.split(".")
    if len(parts) > 3 or not all(
        _QUOTABLE_NAME_RE.fullmatch(part) and part == part.strip() for part in parts
    ):
        raise HTTPException(400, detail=f"Unsafe identifier: '{name}'")
    return parts


def sql_name(name: str, quote: str = "") -> str:
    """Return a table or column name ready to place in a SQL statement.

    Plain names (`orders`, `dbo.orders`) are passed through unquoted, so the
    database applies its usual case rules. A part that is not plain — it
    has a space, starts with a digit, ... — is wrapped in the driver's
    quote character.
    """
    rendered = []
    for part in split_name(name):
        if _PLAIN_NAME_RE.fullmatch(part):
            rendered.append(part)
        elif quote:
            rendered.append(f"{quote}{part}{quote}")
        else:
            raise HTTPException(
                400,
                detail=f"Identifier '{name}' needs quoting, which this driver does not support",
            )
    return ".".join(rendered)


def db_error(error: pyodbc.Error) -> HTTPException:
    """The HTTP 400 returned when the database rejects a statement."""
    return HTTPException(400, detail=scrub(str(error)))


def row_exists(cursor: pyodbc.Cursor, table: str, pk_col: str, pk_value: str) -> bool:
    """Check if a row exists — `rowcount` after UPDATE/DELETE is not reliable
    on every driver. `table` and `pk_col` must already be rendered by `sql_name`."""
    cursor.execute(f"SELECT {pk_col} FROM {table} WHERE {pk_col} = ?", str(pk_value))
    return cursor.fetchone() is not None


def build_order_by(value: Optional[str]) -> str:
    """Build ordering from comma-separated identifiers; omitted directions use ASC.

    Restrict each term to a plain identifier and direction; never accept SQL
    expressions here. The database validates whether the column exists.
    """
    if value is None:
        return ""
    terms = []
    for part in value.split(","):
        match = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(ASC|DESC))?",
            part.strip(),
            flags=re.IGNORECASE | re.ASCII,
        )
        if match is None:
            raise HTTPException(
                400,
                detail="order_by must contain comma-separated column names, each optionally followed by ASC or DESC",
            )
        column, direction = match.groups()
        terms.append(f"{column} {(direction or 'ASC').upper()}")
    return " ORDER BY " + ", ".join(terms)
