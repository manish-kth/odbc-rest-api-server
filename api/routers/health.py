"""Health-check endpoints.

None of these are authenticated — load balancers, container orchestrators
and uptime monitors need to reach them without holding the API key.

  GET /               — liveness: the process is running. Always 200.
  GET /health/db      — readiness of EVERY configured database. 503 if
                        any one of them is unreachable.
  GET /<name>/health  — readiness of one database (`/health` when there
                        is only one).
"""

from typing import Dict, Optional

import pyodbc
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from api import __version__
from api.config import DatabaseConfig
from api.database import get_connection, get_database, scrub

# App-wide endpoints, mounted once at the root.
router = APIRouter()

# Per-database endpoint, mounted once under each database prefix.
database_router = APIRouter()


def _probe(config: DatabaseConfig) -> Optional[str]:
    """Check one database. Returns None when healthy, else the error text."""
    try:
        conn = get_connection(config)
    except HTTPException as e:
        return str(e.detail)
    try:
        if config.health_sql:
            cursor = conn.cursor()
            cursor.execute(config.health_sql)
            cursor.fetchone()
        return None
    except pyodbc.Error as e:
        return f"Database query failed: {scrub(str(e))}"
    finally:
        conn.close()


@router.get("/", tags=["Health"])
def health(request: Request):
    """Liveness check — confirms the API process is up."""
    databases: Dict[str, DatabaseConfig] = request.app.state.databases
    return {"status": "ok", "databases": list(databases), "version": __version__}


@router.get("/health/db", tags=["Health"])
def health_db(request: Request):
    """Readiness check across every configured database.

    Returns HTTP 200 only when all of them are reachable; otherwise 503
    with a per-database breakdown, so one database being down is never
    hidden by another being up.
    """
    databases: Dict[str, DatabaseConfig] = request.app.state.databases
    results = {}
    for name, config in databases.items():
        error = _probe(config)
        results[name] = (
            {"status": "ok"} if error is None else {"status": "unreachable", "error": error}
        )
    all_ok = all(r["status"] == "ok" for r in results.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ok" if all_ok else "degraded", "databases": results},
    )


@database_router.get("/health")
def health_one_db(config: DatabaseConfig = Depends(get_database)):
    """Readiness check for this database only.

    Wire a monitor to this endpoint when it should react to this specific
    database going down.
    """
    error = _probe(config)
    if error is not None:
        raise HTTPException(503, detail=error)
    return {"status": "ok", "database": config.name}
