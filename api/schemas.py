"""Pydantic request models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RowData(BaseModel):
    data: Dict[str, Any]


class SqlPayload(BaseModel):
    sql: str
    params: Optional[List[Any]] = []
