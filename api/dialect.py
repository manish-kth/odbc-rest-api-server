"""The few places where databases disagree, resolved once per database.

Everything else the API sends is plain ODBC: `?` parameters, `SELECT`,
`INSERT`, `UPDATE`, `DELETE`, `COUNT(*)` and the driver's own catalog
calls. Two things differ between engines and are handled here:

Paging a row listing
    limit         `... LIMIT n OFFSET m`
    offset_fetch  `... ORDER BY x OFFSET m ROWS FETCH NEXT n ROWS ONLY`
    client        run the full SELECT, skip and cap rows in the cursor —
                  slower on deep pages, but works on every engine

Quoting a name that is not a plain identifier (spaces, leading digit, ...)
    the quote character is asked of the driver.

With `ODBC_PAGING=auto` (the default) the mode is chosen from the DBMS
name the driver reports. An engine that is not recognised gets `client`,
which is always correct.
"""

from dataclasses import dataclass
from typing import Dict

import pyodbc
from fastapi import Depends

from api.config import DatabaseConfig
from api.database import get_database, get_db

# Substrings of SQL_DBMS_NAME, lower-cased. Kept deliberately short: only
# engines whose paging syntax is certain. Anything else pages in the cursor.
_LIMIT_ENGINES = ("postgresql", "mysql", "mariadb", "sqlite", "pervasive", "zen")
_OFFSET_FETCH_ENGINES = ("microsoft sql server", "oracle", "db2")


@dataclass(frozen=True)
class Dialect:
    # DBMS name as reported by the driver; "" if it would not say.
    dbms: str
    # "limit", "offset_fetch" or "client" — never "auto".
    paging: str
    # Character that opens and closes a quoted identifier; "" if the driver
    # reports none, in which case only plain names are accepted.
    quote: str


_cache: Dict[str, Dialect] = {}


def reset_cache() -> None:
    """Forget detected dialects (used by tests that swap the fake driver)."""
    _cache.clear()


def _info(conn: pyodbc.Connection, code: int) -> str:
    try:
        value = conn.getinfo(code)
    except pyodbc.Error:
        return ""
    return value.strip() if isinstance(value, str) else ""


def paging_for(dbms: str) -> str:
    """Paging mode for a DBMS name; `client` when the engine is unknown."""
    name = dbms.lower()
    if any(engine in name for engine in _LIMIT_ENGINES):
        return "limit"
    if any(engine in name for engine in _OFFSET_FETCH_ENGINES):
        return "offset_fetch"
    return "client"


def get_dialect(
    conn: pyodbc.Connection = Depends(get_db),
    config: DatabaseConfig = Depends(get_database),
) -> Dialect:
    """FastAPI dependency: the dialect of the database this request is bound to."""
    dialect = _cache.get(config.name)
    if dialect is None:
        dbms = _info(conn, pyodbc.SQL_DBMS_NAME)
        dialect = Dialect(
            dbms=dbms,
            paging=paging_for(dbms) if config.paging == "auto" else config.paging,
            quote=_info(conn, pyodbc.SQL_IDENTIFIER_QUOTE_CHAR),
        )
        _cache[config.name] = dialect
    return dialect
