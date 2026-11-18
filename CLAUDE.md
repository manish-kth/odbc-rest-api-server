# CLAUDE.md

Guidance for Claude Code (and other AI coding assistants) working in this
repository. People: the README is written for you; this file is the short
version an assistant needs.

## What this is

A small FastAPI app that puts a REST API on top of any database reachable
through ODBC (via pyodbc): list tables, read schemas, and create, read,
update and delete rows, plus a `/query` endpoint for raw SQL. It was first
built to reach Sage 300 CRE through its ODBC driver and then generalised.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

uvicorn app:app --reload --port 8000    # run locally; docs at /docs
pytest                                  # tests — no database needed
ruff check . && ruff format --check .   # lint and format check (CI runs both)
ruff format .                           # apply formatting
```

CI runs ruff and pytest on Python 3.12. Keep both green before committing.

## How it fits together

- `app.py` — `create_app()` mounts every router once per configured
  database, under that database's URL prefix.
- `api/config.py` — reads and validates every environment variable at
  import time. The app refuses to start when something is wrong.
- `api/database.py` — opens one connection per request (`get_db`) and
  binds a route to its database (`bind_database`, `get_database`).
- `api/dialect.py` — the only engine-specific logic: paging mode
  (`limit`, `offset_fetch`, `client`) and the identifier quote character,
  detected once per database and cached.
- `api/security.py` — `verify_key` (read or write key), `require_write_key`,
  `authorize_filter`.
- `api/sql_guard.py` — what the read key may run: one read-only `SELECT`.
- `api/utils.py` — `sql_name` (identifier validation and quoting),
  `build_order_by`, `rows_to_dicts`, `db_error`.
- `api/routers/` — `health`, `schema`, `crud`, `delete` (mounted only when
  `ALLOW_DELETE=true`), `query`.
- `tests/` — `conftest.py` sets dummy settings and blocks real ODBC
  connections; `fakes.py` is the stand-in driver. `test_sqlite_integration.py`
  runs only when a SQLite ODBC driver is installed.

## Rules that must hold

- **Never read out, log, commit or send anywhere the contents of `.env`.**
  It holds database credentials and API keys. Check which variables are
  set without printing their values. `.env.example` is the public template.
- **Values go in as `?` parameters, never into the SQL text.** The only
  things interpolated into SQL are identifiers that passed `sql_name` /
  `build_order_by`, validated integers (`limit`, `offset`), and the
  caller's own `filter` / `/query` text, which is gated by the keys.
- **Every table or column name from a request goes through `sql_name`.**
- **Every route needs a key** — `Depends(verify_key)` for reads,
  `Depends(require_write_key)` for anything that changes data. Only the
  health endpoints are open.
- **The read key must stay read-only.** Any new place that accepts SQL
  text has to pass `ensure_read_only_sql` for read-key callers. The guard
  fails closed; keep it that way.
- **Database errors are returned through `db_error`**, which masks
  passwords a driver may echo back.
- **Keep it engine-neutral.** Anything that differs between databases
  belongs in `api/dialect.py`, with `client` paging as the safe fallback.
  No table names, vendor names or business logic in the generic routers.
- **Defaults stay closed:** no write key means no writes, `ALLOW_DELETE`
  is off, `CORS_ORIGINS` is empty.

## Making changes

- New endpoint: add a router under `api/routers/`, protect it as above,
  take the connection with `Depends(get_db)` and the dialect with
  `Depends(get_dialect)`, then add it to the list in `create_app()`.
- New setting: load and validate it in `api/config.py`, then document it
  in `.env.example` and in the README's "All settings at a glance" table.
- Add tests with every behaviour change; use `tests/fakes.py` instead of
  a real database.
- Update the README when behaviour, settings or endpoints change.

## Helping someone set it up

Typical requests after a fresh clone, and what to do:

- **"Get this running"** — create the virtualenv, install requirements,
  copy `.env.example` to `.env`, ask them for the DSN or connection
  string and have them put credentials in `.env` themselves, generate an
  `API_KEY` with `python -c "import secrets; print(secrets.token_urlsafe(32))"`,
  start uvicorn, then check `/health` and `/tables`.
- **"It can't connect"** — the ODBC driver and DSN must exist on the
  machine running the app, and on Windows the driver's bitness (32 or
  64-bit) must match Python's. `/health` reports the driver's error.
- **"Paging is wrong or slow"** — see `ODBC_PAGING` in the README; set it
  explicitly when the engine is not recognised.
- **"Deploy it"** — follow the README's Deployment section: a process
  manager, a reverse proxy for TLS, and the pre-exposure checklist. Do not
  expose it to the internet without TLS and strong keys.
- **Writes and deletes against a real database are not reversible.** Ask
  before running any against live data, and prefer the read key while
  exploring.
