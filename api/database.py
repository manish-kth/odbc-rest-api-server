"""ODBC connection management.

One or more databases are served (see `api.config`). Which one a request
talks to is fixed by the URL prefix its route was mounted under: no prefix
when there is a single database, `/<name>` when there are several.

`app.py` mounts each router once per database and attaches
`bind_database(config)`; handlers just ask for `Depends(get_db)`.
"""

import logging
import re
from typing import Callable, Generator

import pyodbc
from fastapi import Depends, HTTPException, Request

from api.config import DatabaseConfig

logger = logging.getLogger("api.database")

_SECRET_RE = re.compile(r"(?i)\b(PWD|PASSWORD)\s*=\s*(\{(?:[^}]|\}\})*\}|[^;]*)")


def scrub(message: str) -> str:
    """Mask any password a driver echoes back inside an error message."""
    return _SECRET_RE.sub(r"\1=***", message)


def bind_database(config: DatabaseConfig) -> Callable[[Request], None]:
    """Build the dependency that pins a mounted router to one database."""

    def _bind(request: Request) -> None:
        request.state.database = config

    return _bind


def get_database(request: Request) -> DatabaseConfig:
    """FastAPI dependency: the database this request's route is bound to."""
    return request.state.database


def get_connection(config: DatabaseConfig) -> pyodbc.Connection:
    """Return a live ODBC connection to the given database.

    Connections are opened with autocommit=True: every request is a single
    statement, and some ODBC drivers do not support manual transactions.
    """
    try:
        return pyodbc.connect(config.conn_str, autocommit=True)
    except pyodbc.Error as e:
        message = scrub(str(e))
        logger.error("ODBC connection failed for database=%s: %s", config.name, message)
        raise HTTPException(
            503, detail=f"ODBC connection to '{config.name}' failed: {message}"
        ) from e


def get_db(
    config: DatabaseConfig = Depends(get_database),
) -> Generator[pyodbc.Connection, None, None]:
    """FastAPI dependency that yields a live ODBC connection and closes it
    when the request finishes — including when the handler raises.

    Usage in a route:

        @router.get("/...")
        def handler(conn: pyodbc.Connection = Depends(get_db)):
            cursor = conn.cursor()
            ...
    """
    conn = get_connection(config)
    try:
        yield conn
    finally:
        conn.close()
