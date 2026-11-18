"""Database config parsing — pure function over an env mapping, no ODBC."""

import pytest

from api.config import load_api_keys, load_cors_origins, load_databases, load_flag


def test_single_database_has_no_prefix():
    databases = load_databases({"ODBC_DSN": "MyDsn"})
    assert list(databases) == ["default"]
    config = databases["default"]
    assert config.prefix == ""
    assert config.conn_str == "DSN=MyDsn;"
    assert config.paging == "auto"
    assert config.health_sql == ""


def test_several_databases_each_get_a_prefix_and_their_own_settings():
    databases = load_databases(
        {
            "DATABASES": "Sales, warehouse",
            "SALES_ODBC_DSN": "SalesDsn",
            "WAREHOUSE_ODBC_DSN": "Warehouse Data Source",
            "WAREHOUSE_ODBC_UID": "bob",
            "WAREHOUSE_ODBC_PWD": "s3cret",
            "WAREHOUSE_ODBC_PAGING": "client",
            "WAREHOUSE_ODBC_HEALTH_SQL": "SELECT 1",
            # Ignored: a named list replaces the single-database variables.
            "ODBC_DSN": "ignored",
        }
    )
    assert list(databases) == ["sales", "warehouse"]
    assert databases["sales"].prefix == "/sales"
    assert databases["sales"].conn_str == "DSN=SalesDsn;"
    assert databases["sales"].paging == "auto"
    assert databases["warehouse"].conn_str == "DSN=Warehouse Data Source;UID=bob;PWD=s3cret;"
    assert databases["warehouse"].paging == "client"
    assert databases["warehouse"].health_sql == "SELECT 1"


def test_dsn_with_login_appended_is_passed_through():
    value = "My Data Source;UID=bob;PWD=s3cret;"
    assert load_databases({"ODBC_DSN": value})["default"].conn_str == "DSN=" + value


def test_full_connection_string_wins_over_dsn_parts():
    databases = load_databases({"ODBC_CONN": "Driver={X};Server=h;", "ODBC_DSN": "ignored"})
    assert databases["default"].conn_str == "Driver={X};Server=h;"


def test_password_with_special_characters_is_brace_quoted():
    databases = load_databases({"ODBC_DSN": "X", "ODBC_PWD": "p;w}d"})
    assert databases["default"].conn_str == "DSN=X;PWD={p;w}}d};"


@pytest.mark.parametrize(
    "env",
    [
        {},  # nothing configured
        {"ODBC_DSN": "A", "ODBC_PAGING": "magic"},  # bad paging mode
        {"DATABASES": "sales"},  # listed but has no connection
        {"DATABASES": "sales,sales", "SALES_ODBC_DSN": "A"},  # duplicate
        {"DATABASES": "my-db", "MY-DB_ODBC_DSN": "A"},  # not a valid name
        {"DATABASES": "tables", "TABLES_ODBC_DSN": "A"},  # collides with /tables
    ],
)
def test_misconfiguration_fails_fast(env):
    with pytest.raises(RuntimeError):
        load_databases(env)


@pytest.mark.parametrize("write_key", ["", "separate-write-key"])
def test_api_keys_allow_optional_distinct_write_key(write_key):
    assert load_api_keys({"API_KEY": "read-key", "WRITE_API_KEY": write_key}) == (
        "read-key",
        write_key,
    )


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"API_KEY": " "},
        {"API_KEY": "same", "WRITE_API_KEY": "same"},
        {"API_KEY": "read", "WRITE_API_KEY": " "},
    ],
)
def test_invalid_api_key_configuration_is_rejected(env):
    with pytest.raises(RuntimeError):
        load_api_keys(env)


@pytest.mark.parametrize(
    "value,expected", [("", False), ("false", False), ("0", False), ("true", True), ("YES", True)]
)
def test_flag_values(value, expected):
    assert load_flag({"ALLOW_DELETE": value}, "ALLOW_DELETE") is expected
    assert load_flag({}, "ALLOW_DELETE") is False


def test_unrecognised_flag_value_is_rejected():
    with pytest.raises(RuntimeError):
        load_flag({"ALLOW_DELETE": "maybe"}, "ALLOW_DELETE")


def test_cors_origins_default_to_none():
    assert load_cors_origins({}) == []
    assert load_cors_origins({"CORS_ORIGINS": "  "}) == []
    assert load_cors_origins({"CORS_ORIGINS": "*"}) == ["*"]
    assert load_cors_origins({"CORS_ORIGINS": "https://a.example, https://b.example"}) == [
        "https://a.example",
        "https://b.example",
    ]
