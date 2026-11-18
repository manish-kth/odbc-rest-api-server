"""Runtime configuration loaded from environment variables.

A `.env` file at the project root is auto-loaded via python-dotenv, so
local development only needs `cp .env.example .env` and filling in values.
See `.env.example` for the full list of supported variables.

This module fails fast at import time if a required variable is missing —
better to crash on `uvicorn` startup than to serve requests in an
incorrectly configured state.

Databases
---------
One database — its endpoints sit at the root (`/tables`, `/query`):

    ODBC_DSN=MyDataSource
    ODBC_UID=someuser          # only if the DSN needs a login
    ODBC_PWD=somepassword

Several databases — each gets its own URL prefix and its own settings,
read from variables prefixed with its upper-cased name:

    DATABASES=sales,warehouse
    SALES_ODBC_DSN=SalesDsn                 ->  /sales/tables, /sales/query
    WAREHOUSE_ODBC_CONN=Driver={...};...    ->  /warehouse/tables, ...

For either form, `<PREFIX>ODBC_CONN` (a full connection string) replaces
the DSN/UID/PWD variables when set.
"""

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

from dotenv import load_dotenv

load_dotenv()

# "auto" picks one of the other three from the DBMS name the driver reports.
PAGING_MODES = ("auto", "limit", "offset_fetch", "client")

# Name given to the database when only one is configured (no URL prefix).
DEFAULT_DATABASE = "default"

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")

# Prefixes that would collide with the app's own root-level paths.
RESERVED_NAMES = frozenset({"health", "tables", "query", "docs", "redoc", "openapi"})

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("", "0", "false", "no", "off")


@dataclass(frozen=True)
class DatabaseConfig:
    """Everything needed to connect to, and talk to, one ODBC database."""

    # Identifier used in logs and health reports, e.g. "sales".
    name: str
    # URL prefix its endpoints are mounted under: "/sales", or "" when it is
    # the only database.
    prefix: str
    # Full ODBC connection string. May contain a password — never log it or
    # return it in a response.
    conn_str: str
    # How row listings are paged; one of PAGING_MODES. See `api.dialect`.
    paging: str
    # Statement run by the health check. Blank means "a successful connect
    # is enough", which works on every engine.
    health_sql: str


def _odbc_value(value: str) -> str:
    """Brace-quote a connection-string value if it contains special characters."""
    if value and (value != value.strip() or any(c in value for c in ";{}=")):
        return "{" + value.replace("}", "}}") + "}"
    return value


def _load_database(
    name: str, url_prefix: str, env_prefix: str, env: Mapping[str, str]
) -> Optional[DatabaseConfig]:
    """Build one database from `<env_prefix>ODBC_*`; None if it has no connection."""
    conn_str = env.get(env_prefix + "ODBC_CONN", "").strip()
    if not conn_str:
        dsn = env.get(env_prefix + "ODBC_DSN", "").strip()
        if not dsn:
            return None
        if ";" in dsn:
            # Login appended to the DSN name, e.g. "MyDsn;UID=me;PWD=secret;".
            # A DSN name cannot contain ";", so pass it through as written
            # instead of quoting it.
            parts = [f"DSN={dsn.rstrip(';')}"]
        else:
            parts = [f"DSN={_odbc_value(dsn)}"]
        # Credentials are not stripped — a password may legitimately start
        # or end with a space.
        uid = env.get(env_prefix + "ODBC_UID", "")
        pwd = env.get(env_prefix + "ODBC_PWD", "")
        if uid:
            parts.append(f"UID={_odbc_value(uid)}")
        if pwd:
            parts.append(f"PWD={_odbc_value(pwd)}")
        conn_str = ";".join(parts) + ";"

    paging_var = env_prefix + "ODBC_PAGING"
    paging = env.get(paging_var, "").strip().lower() or "auto"
    if paging not in PAGING_MODES:
        raise RuntimeError(f"{paging_var} must be one of {PAGING_MODES}, got '{paging}'.")

    return DatabaseConfig(
        name=name,
        prefix=url_prefix,
        conn_str=conn_str,
        paging=paging,
        health_sql=env.get(env_prefix + "ODBC_HEALTH_SQL", "").strip(),
    )


def load_databases(env: Mapping[str, str]) -> Dict[str, DatabaseConfig]:
    """Build the configured databases, keyed by name.

    Raises RuntimeError on misconfiguration so the app refuses to start.
    """
    names = [n.strip().lower() for n in env.get("DATABASES", "").split(",") if n.strip()]

    if not names:
        config = _load_database(DEFAULT_DATABASE, "", "", env)
        if config is None:
            raise RuntimeError(
                "No database configured. Set ODBC_DSN (or ODBC_CONN) in your .env "
                "file, or list several databases in DATABASES (see .env.example)."
            )
        return {DEFAULT_DATABASE: config}

    databases: Dict[str, DatabaseConfig] = {}
    for name in names:
        if not _NAME_RE.fullmatch(name):
            raise RuntimeError(
                f"Invalid name '{name}' in DATABASES: use a letter followed by "
                "letters, digits or underscores."
            )
        if name in RESERVED_NAMES:
            raise RuntimeError(f"'{name}' in DATABASES is reserved; choose another name.")
        if name in databases:
            raise RuntimeError(f"'{name}' is listed twice in DATABASES.")
        env_prefix = name.upper() + "_"
        config = _load_database(name, f"/{name}", env_prefix, env)
        if config is None:
            raise RuntimeError(
                f"DATABASES lists '{name}' but neither {env_prefix}ODBC_DSN nor "
                f"{env_prefix}ODBC_CONN is set."
            )
        databases[name] = config
    return databases


def load_api_keys(env: Mapping[str, str]) -> tuple[str, str]:
    """`API_KEY` is the read-only key; an optional distinct key permits writes."""
    read_key = env.get("API_KEY", "")
    write_key = env.get("WRITE_API_KEY", "")
    if not read_key.strip():
        raise RuntimeError("API_KEY is required and must not be blank. Set it in your .env file.")
    if write_key and not write_key.strip():
        raise RuntimeError("WRITE_API_KEY must be nonblank or unset to disable writes.")
    if write_key == read_key:
        raise RuntimeError("WRITE_API_KEY must be different from the read-only API_KEY.")
    return read_key, write_key


def load_flag(env: Mapping[str, str], name: str) -> bool:
    """Read an on/off setting; unset or blank is off."""
    value = env.get(name, "").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise RuntimeError(f"{name} must be true or false, got '{value}'.")


def load_cors_origins(env: Mapping[str, str]) -> List[str]:
    """Origins allowed to call the API from a browser. Default: none.

    Closed unless opened: with nothing set, no web page may call the API
    from a browser. Server-side callers (curl, scripts, backends) do not
    use CORS and are unaffected. `*` allows any origin.
    """
    return [o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()]


# Every configured database, keyed by name.
DATABASES: Dict[str, DatabaseConfig] = load_databases(os.environ)

API_KEY, WRITE_API_KEY = load_api_keys(os.environ)

# DELETE endpoints are only mounted when this is on (and need the write key).
ALLOW_DELETE: bool = load_flag(os.environ, "ALLOW_DELETE")

CORS_ORIGINS: List[str] = load_cors_origins(os.environ)
