"""Shared pytest fixtures and environment setup.

Env vars MUST be set before `api.config` is imported — that module fails
fast at import time if `API_KEY` is missing. Setting them at the top of
this file (which pytest loads before any test module) guarantees they
exist for the rest of the test session.
"""

import os

# Fixed test-only settings take precedence over both CI and local configuration.
# In particular, blank full connection strings prevent them overriding test DSNs.
os.environ.update(
    DATABASES="primary,legacy",
    PRIMARY_ODBC_DSN="test-primary-dsn",
    PRIMARY_ODBC_CONN="",
    PRIMARY_ODBC_UID="",
    PRIMARY_ODBC_PWD="",
    PRIMARY_ODBC_PAGING="limit",
    PRIMARY_ODBC_HEALTH_SQL="SELECT 1",
    LEGACY_ODBC_DSN="test-legacy-dsn",
    LEGACY_ODBC_CONN="",
    LEGACY_ODBC_UID="test-user",
    LEGACY_ODBC_PWD="test-secret",
    LEGACY_ODBC_PAGING="client",
    LEGACY_ODBC_HEALTH_SQL="",
    API_KEY="test-api-key",
    WRITE_API_KEY="test-write-api-key",
    ALLOW_DELETE="",
    CORS_ORIGINS="",
)

import pyodbc
import pytest
from fastapi.testclient import TestClient

from api import dialect
from app import app as _app

TEST_API_KEY = os.environ["API_KEY"]


@pytest.fixture
def client() -> TestClient:
    """A FastAPI TestClient bound to the real application."""
    return TestClient(_app)


@pytest.fixture
def auth_headers() -> dict:
    """Headers carrying a valid API key for protected endpoints."""
    return {"X-Api-Key": TEST_API_KEY}


@pytest.fixture
def write_auth_headers() -> dict:
    return {"X-Api-Key": os.environ["WRITE_API_KEY"]}


@pytest.fixture(autouse=True)
def block_live_odbc(monkeypatch):
    """Unit tests must explicitly mock successful connections; never use real DSNs."""

    def unavailable(*args, **kwargs):
        raise pyodbc.Error("08001", "Live ODBC is disabled in unit tests")

    monkeypatch.setattr(pyodbc, "connect", unavailable)


@pytest.fixture(autouse=True)
def fresh_dialects():
    """Each test detects its own fake driver's dialect."""
    dialect.reset_cache()
    yield
    dialect.reset_cache()
