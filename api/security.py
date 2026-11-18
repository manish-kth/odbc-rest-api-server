"""Read/write API-key permissions, checked before opening an ODBC connection."""

import logging
from secrets import compare_digest
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader

from api.config import API_KEY, WRITE_API_KEY
from api.sql_guard import ensure_read_only_sql

logger = logging.getLogger("api.security")

api_key_header = APIKeyHeader(
    name="X-Api-Key",
    auto_error=False,
    description="API_KEY permits reads, including filters and a single SELECT via /query. WRITE_API_KEY also permits writes and unrestricted SQL.",
)


def verify_key(api_key: Optional[str] = Security(api_key_header)) -> Literal["read", "write"]:
    """Authenticate either key. An unset write key never grants access."""
    if api_key:
        supplied = api_key.encode("utf-8")
        if compare_digest(supplied, API_KEY.encode("utf-8")):
            return "read"
        if WRITE_API_KEY and compare_digest(supplied, WRITE_API_KEY.encode("utf-8")):
            return "write"
    logger.warning("Auth failed: missing or incorrect X-Api-Key header")
    raise HTTPException(401, detail="Invalid or missing API key (send as X-Api-Key header)")


def require_write_key(access: str = Depends(verify_key)) -> None:
    """Reject the read key before any write-capable operation reaches ODBC."""
    if access != "write":
        raise HTTPException(403, detail="This operation requires the write API key")


def authorize_filter(
    filter: Optional[str] = Query(default=None),
    access: str = Depends(verify_key),
) -> None:
    """The filter is a raw SQL WHERE clause. Both keys may use it, but with
    the read key the resulting statement must still be a single read-only
    SELECT — checked here, before any ODBC connection is opened."""
    if filter and access != "write":
        ensure_read_only_sql(f"SELECT * FROM T WHERE {filter}")
