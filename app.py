"""
ODBC CRUD REST API
------------------
FastAPI entry point. Wires routers together and applies CORS. All business
logic, helpers, and configuration live under the `api/` package.

Run locally:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000

See README.md for setup and configuration.
"""

import logging
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import __version__, config
from api.config import DatabaseConfig
from api.database import bind_database
from api.logging_config import configure_logging
from api.routers import crud, delete, health, query, schema

configure_logging()
logger = logging.getLogger("api")

DESCRIPTION = (
    "Generic CRUD REST API over any ODBC data source.\n\n"
    "With one database configured its endpoints are at the root "
    "(`/tables`, `/query`); with several, each is served under its own "
    "prefix (`/<name>/tables`, `/<name>/query`).\n\n"
    "Send `X-Api-Key` on data requests: `API_KEY` for reads (including "
    "filters and a single SELECT through `/query`), `WRITE_API_KEY` for "
    "reads, writes and unrestricted SQL."
)


def create_app(
    databases: Optional[Dict[str, DatabaseConfig]] = None,
    allow_delete: Optional[bool] = None,
    cors_origins: Optional[List[str]] = None,
) -> FastAPI:
    """Build the application. Arguments default to the environment's settings."""
    databases = config.DATABASES if databases is None else databases
    allow_delete = config.ALLOW_DELETE if allow_delete is None else allow_delete
    cors_origins = config.CORS_ORIGINS if cors_origins is None else cors_origins

    app = FastAPI(title="ODBC CRUD REST API", description=DESCRIPTION, version=__version__)
    app.state.databases = databases

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)

    # Every per-database router is mounted once per configured database,
    # under that database's prefix and pinned to its connection by
    # `bind_database`.
    # Order matters — schema must precede crud so `/tables/{table}/schema`
    # is not swallowed by `/tables/{table}/{pk_value}`.
    routers = [health.database_router, schema.router, crud.router, query.router]
    if allow_delete:
        routers.append(delete.router)

    for database in databases.values():
        for router in routers:
            app.include_router(
                router,
                prefix=database.prefix,
                tags=[database.name if database.prefix else "Database"],
                dependencies=[Depends(bind_database(database))],
            )

    logger.info(
        "API ready — databases=%s delete=%s version=%s",
        ",".join(databases),
        "on" if allow_delete else "off",
        __version__,
    )
    return app


app = create_app()
