"""Structural tests over the registered route table.

These catch the most common refactor breakages:
  - An endpoint accidentally dropped when reshuffling routers.
  - DELETE accidentally enabled when `ALLOW_DELETE` is off.
"""

from api.config import load_databases
from app import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _routes(app) -> set[tuple[str, str]]:
    """Return the (method, path) pairs registered on the app.

    Read from the OpenAPI schema rather than `app.routes`: newer FastAPI
    releases keep included routers as nested objects there instead of a
    flat list of APIRoute, so walking `app.routes` silently finds nothing.
    """
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in HTTP_METHODS
    }


DATA_ROUTES = {
    ("GET", "/tables"),
    ("GET", "/tables/{table}/schema"),
    ("GET", "/tables/{table}"),
    ("POST", "/tables/{table}"),
    ("GET", "/tables/{table}/{pk_value}"),
    ("PUT", "/tables/{table}/{pk_value}"),
    ("PATCH", "/tables/{table}/{pk_value}"),
    ("POST", "/query"),
}

# Each database gets the full set under its own fixed prefix, plus a
# per-database health check.
EXPECTED_ACTIVE_ROUTES = {("GET", "/"), ("GET", "/health/db")} | {
    (method, f"/{prefix}{path}")
    for prefix in ("primary", "legacy")
    for (method, path) in DATA_ROUTES | {("GET", "/health")}
}


def test_all_expected_routes_are_registered(client):
    actual = _routes(client.app)
    assert actual, "No routes discovered — the route-listing helper is broken"
    missing = EXPECTED_ACTIVE_ROUTES - actual
    assert not missing, f"Expected routes are missing: {missing}"


def test_no_unprefixed_data_routes(client):
    """With several databases, data endpoints only exist under a prefix —
    never at the root, where it would be ambiguous which database they hit."""
    leaked = DATA_ROUTES & _routes(client.app)
    assert not leaked, f"Un-prefixed data routes are registered: {leaked}"


def test_delete_endpoint_is_off_by_default(client):
    actual = _routes(client.app)
    delete_routes = {(m, p) for (m, p) in actual if m == "DELETE"}
    assert not delete_routes, f"DELETE routes leaked into the app: {delete_routes}"


def test_allow_delete_mounts_delete_for_every_database():
    actual = _routes(create_app(allow_delete=True))
    assert {(m, p) for (m, p) in actual if m == "DELETE"} == {
        ("DELETE", "/primary/tables/{table}/{pk_value}"),
        ("DELETE", "/legacy/tables/{table}/{pk_value}"),
    }


def test_single_database_is_served_at_the_root():
    app = create_app(databases=load_databases({"ODBC_DSN": "only"}))
    assert _routes(app) == DATA_ROUTES | {("GET", "/"), ("GET", "/health/db"), ("GET", "/health")}
