# ODBC CRUD REST API

Turn any database you can reach through ODBC into a REST API: list
tables, read their schema, and create, read, update and delete rows over
HTTP, without writing a line of SQL or a single model class.

It is a small [FastAPI](https://fastapi.tiangolo.com/) app on top of
[pyodbc](https://github.com/mkleehammer/pyodbc). Point it at a DSN (or a
connection string), set an API key, and start it.

```bash
curl -H "X-Api-Key: $API_KEY" "http://localhost:8000/tables/customers?order_by=id&limit=5"
```

```json
{
  "table": "customers",
  "total": 1284,
  "offset": 0,
  "limit": 5,
  "rows": [{"id": 1, "name": "Ada Lovelace", "city": "London"}, "..."]
}
```

> **Typed by AI, steered by people.** Built in long pair-programming
> sessions with [Claude Code](https://claude.com/claude-code), and in many
> more human hours of deciding what it should do, testing it against real
> legacy systems, and sending it back to try again.

---

## Contents

- [Why this exists](#why-this-exists)
- [Endpoints](#endpoints)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Reading rows](#reading-rows)
- [Writing rows](#writing-rows)
- [Raw SQL](#raw-sql)
- [Database compatibility](#database-compatibility)
- [Health checks](#health-checks)
- [Deployment](#deployment)
- [Development](#development)
- [Build on it with Claude Code](#build-on-it-with-claude-code)
- [Limitations](#limitations)
- [Bugs, security and contributing](#bugs-security-and-contributing)
- [How it was built](#how-it-was-built)
- [License](#license)

---

## Why this exists

This started as a way into **Sage 300 Construction and Real Estate**
(formerly Timberline). We needed its data in other tools, and getting API
access to it turned out to be very hard. What it does ship with is an
ODBC driver — so we put a REST API on top of that driver instead, and
suddenly the data was a `curl` away.

Nothing in the result was really about Sage. Plenty of older accounting,
ERP and line-of-business systems are in the same position: no usable API,
but an ODBC driver that has worked for twenty years. So the Sage-specific
parts were taken out, and this is what is left — a REST API for anything
ODBC can reach.

If you have a system like that, this may save you the same weeks it
would have saved us.

*This project is independent. It is not affiliated with, endorsed by or
supported by Sage or any other database vendor; product names belong to
their owners.*

---

## Endpoints

| Method and path | What it does | Key needed |
| --- | --- | --- |
| `GET /` | Liveness: the process is up | none |
| `GET /health/db` | Readiness of every configured database | none |
| `GET /health` | Readiness of one database | none |
| `GET /tables` | List tables | read |
| `GET /tables/{table}/schema` | Column names, types, sizes, nullability | read |
| `GET /tables/{table}` | List rows: `limit`, `offset`, `order_by`, `filter` | read |
| `GET /tables/{table}/{pk_value}?pk_col=` | One row by key | read |
| `POST /tables/{table}` | Insert a row | write |
| `PUT /tables/{table}/{pk_value}?pk_col=` | Update the fields you send | write |
| `PATCH /tables/{table}/{pk_value}?pk_col=` | Update the fields you send | write |
| `DELETE /tables/{table}/{pk_value}?pk_col=` | Delete a row (only if `ALLOW_DELETE=true`) | write |
| `POST /query` | Run a SQL statement | read: one `SELECT`; write: anything |

With **one** database these paths are served as shown. With **several**,
each database gets the whole set under its own prefix: `/sales/tables`,
`/warehouse/query`, `/sales/health`, and so on.

Interactive documentation is generated for you at `/docs` (Swagger UI)
and `/redoc`.

---

## Quick start

You need Python 3.10+ and an ODBC driver for your database installed on
the machine that will run the API (see [Database compatibility](#database-compatibility)).

```bash
git clone https://github.com/manish-kth/odbc-rest-api-server.git
cd odbc-rest-api-server

python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                   # then edit .env — see below
uvicorn app:app --reload --port 8000
```

The minimum `.env`:

```ini
ODBC_DSN=MyDataSource
API_KEY=<a long random string>
```

Generate a key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then open <http://localhost:8000/docs>, click **Authorize**, paste the
key, and try `GET /tables`.

---

## Configuration

Everything is read from environment variables. A `.env` file in the
working directory is loaded automatically; real environment variables
take precedence over it. Settings are read once at startup, so restart
after changing them. The app refuses to start if a required setting is
missing or invalid.

### One database

| Variable | Required | Purpose |
| --- | --- | --- |
| `ODBC_DSN` | one of these two | Name of a DSN configured on this machine. |
| `ODBC_CONN` | one of these two | A full ODBC connection string. Wins over `ODBC_DSN` when both are set. |
| `ODBC_UID`, `ODBC_PWD` | no | Login added to `ODBC_DSN`, if the DSN needs one. |
| `ODBC_PAGING` | no | `auto` (default), `limit`, `offset_fetch` or `client`. See [Database compatibility](#database-compatibility). |
| `ODBC_HEALTH_SQL` | no | Statement the health check runs, e.g. `SELECT 1`. Blank (default) means a successful connection is enough. |

Examples of `ODBC_CONN`:

```ini
ODBC_CONN=Driver={PostgreSQL Unicode};Server=localhost;Database=shop;UID=me;PWD=secret;
ODBC_CONN=Driver={ODBC Driver 18 for SQL Server};Server=db;Database=shop;UID=me;PWD=secret;Encrypt=yes;
ODBC_CONN=Driver={SQLite3};Database=/data/shop.db;
```

### Several databases

List their names in `DATABASES`. Each one is served under `/<name>/...`
and takes the same settings as above from variables prefixed with its
upper-cased name:

```ini
DATABASES=sales,warehouse

SALES_ODBC_DSN=SalesDsn

WAREHOUSE_ODBC_CONN=Driver={ODBC Driver 18 for SQL Server};Server=db;Database=wh;UID=me;PWD=secret;
WAREHOUSE_ODBC_HEALTH_SQL=SELECT 1
```

Names must start with a letter and contain only letters, digits and
underscores. When `DATABASES` is set, the un-prefixed `ODBC_*` variables
are ignored. One Python process loads every driver, so on Windows all of
them must match Python's bitness (all 32-bit or all 64-bit).

### API keys and options

| Variable | Required | Purpose |
| --- | --- | --- |
| `API_KEY` | yes | Read-only key. |
| `WRITE_API_KEY` | no | Key for reads, writes and unrestricted SQL. Must differ from `API_KEY`. Blank disables every write. |
| `ALLOW_DELETE` | no | `true` mounts the `DELETE` endpoint. Default `false`. |
| `CORS_ORIGINS` | no | Comma-separated browser origins allowed to call the API. Default: none (closed). See [Browser access (CORS)](#browser-access-cors). |
| `LOG_LEVEL` | no | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`. |
| `LOG_FORMAT` | no | `text` (default) or `json` (one object per line). |

Passwords are never logged or returned: connection failures are reported
by database name, and any `PWD=` a driver echoes back is masked.

### Browser access (CORS)

Cross-origin browser access is **closed by default**. Until you set
`CORS_ORIGINS`, a web page served from another origin cannot call the API
with JavaScript — the browser blocks the request.

To let a frontend in, list its exact origin (scheme, host and port, no
trailing slash). Separate several with commas:

```env
CORS_ORIGINS=https://app.example.com,http://localhost:5173
```

- Server-side callers — `curl`, scripts, backends, Postman — do not use
  CORS and work whatever this is set to.
- The built-in `/docs` page is served by the API itself (same origin), so
  it keeps working with CORS closed.
- `CORS_ORIGINS=*` allows any website. Avoid it outside local testing.
- CORS is not authentication. Every request still needs a valid
  `X-Api-Key`, and a key placed in frontend code is visible to anyone who
  opens the page — call the API from your backend where you can.
- Restart the app after changing it.

### All settings at a glance

Every variable the app reads, in one place. `<NAME>_` stands for a
database name from `DATABASES`, upper-cased (`sales` → `SALES_`); with a
single database there is no prefix.

| Variable | Default | Accepted values | What it does |
| --- | --- | --- | --- |
| `DATABASES` | unset | Comma-separated names, e.g. `sales,warehouse` | Serves several databases, each under `/<name>/...`. Unset means one database at the root. |
| `ODBC_DSN` / `<NAME>_ODBC_DSN` | none | A DSN name | The data source to connect to. Required unless `ODBC_CONN` is set. |
| `ODBC_CONN` / `<NAME>_ODBC_CONN` | none | A full ODBC connection string | Used instead of the DSN, UID and PWD variables when set. |
| `ODBC_UID` / `<NAME>_ODBC_UID` | none | Text | Login name added to the DSN. |
| `ODBC_PWD` / `<NAME>_ODBC_PWD` | none | Text | Password added to the DSN. Never logged or returned. |
| `ODBC_PAGING` / `<NAME>_ODBC_PAGING` | `auto` | `auto`, `limit`, `offset_fetch`, `client` | How row listings are paged. `auto` picks from the engine the driver reports. |
| `ODBC_HEALTH_SQL` / `<NAME>_ODBC_HEALTH_SQL` | blank | One SQL statement, e.g. `SELECT 1` | What the health check runs. Blank means connecting is enough. |
| `API_KEY` | none — **required** | Any non-blank text | Read-only key, sent as `X-Api-Key`. |
| `WRITE_API_KEY` | blank (writes off) | Text different from `API_KEY` | Key for writes and unrestricted SQL. |
| `ALLOW_DELETE` | `false` | `true`/`false` (also `1`/`0`, `yes`/`no`, `on`/`off`) | Turns the `DELETE` endpoint on. It still needs the write key. |
| `CORS_ORIGINS` | none (closed) | Comma-separated origins, or `*` | Websites allowed to call the API from a browser. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | How much is logged. |
| `LOG_FORMAT` | `text` | `text`, `json` | Log line format. |

All of them are read once at startup: restart the app after any change.
A missing required value, or an invalid database, key, `ALLOW_DELETE` or
paging value, stops the app from starting with a message naming the
variable. An unrecognised `LOG_LEVEL` or `LOG_FORMAT` falls back to its
default.

---

## Authentication

Send a key in the `X-Api-Key` header. There are two, and the same pair
applies to every configured database.

| Operation | `API_KEY` (read) | `WRITE_API_KEY` |
| --- | --- | --- |
| Tables, schema, row listings, lookup by key | allowed | allowed |
| `POST /query` with a single read-only `SELECT` | allowed | allowed |
| `POST /query` with anything else | 403 | allowed |
| Insert, update, delete | 403 | allowed |
| Health endpoints | no key needed | no key needed |

A missing or wrong key returns 401. A valid read key on a restricted
operation returns 403, and neither opens a database connection.

### Why read and write are separated in the API, not in the database

The usual way to make access read-only is a database login that has no
write permission. Use that wherever your database offers it.

Many legacy systems do not. Older accounting, ERP and file-based
databases often reach ODBC through a driver that has no per-user
permissions at all: one shared login, or none, with full access to every
table. There is nothing to configure on the database side that would make
a connection read-only.

This API was built for that situation, so it draws the line itself, per
request:

- The key decides what a request may do, before any connection is opened.
- The read key may only run a single read-only `SELECT`.
- Inserts, updates, deletes and any other SQL need the write key.

That lets you hand out read access to a database that cannot tell readers
from writers. It is weaker than real database permissions, because it
judges the SQL text rather than what the database actually does — see the
note at the end of the next section. If your database supports a
read-only login, use both: the login as the guarantee, the keys as the
everyday control.

### What the read key may run

`/query` and the `filter` parameter accept SQL text. With the read key,
[api/sql_guard.py](api/sql_guard.py) refuses, before connecting, anything
that:

- does not start with `SELECT` or `WITH`
- contains more than one statement (a `;` anywhere but the very end)
- contains a SQL comment (`--`, `/* */`, `#`)
- contains `INTO`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `DROP`, `ALTER`,
  `CREATE`, `TRUNCATE`, `GRANT`, `REVOKE`, `EXEC`, `EXECUTE` or `CALL` as a
  whole word outside string values and double-quoted names

Text inside `'string values'` is not inspected, so `WHERE note = 'DELETE'`
is fine, and a column that happens to be called `Update` can be written
`"Update"`. The check fails closed: a harmless statement it cannot
classify is refused.

**This is a filter, not a guarantee.** It cannot see inside a function or
stored procedure that a `SELECT` calls, and it knows nothing about your
engine's own extensions. Where the read key must be provably harmless,
connect with a database login that has no write permission. The API's
keys never grant more than that login allows.

---

## Reading rows

```http
GET /tables
GET /tables/customers/schema
GET /tables/customers?order_by=last_name,id&limit=50&offset=100
GET /tables/orders?filter=status='open' AND total > 100
GET /tables/customers/192?pk_col=id
```

- **`limit`** (1–5000, default 100) and **`offset`** (default 0) page the
  result. `total` in the response counts all matching rows.
- **`order_by`** takes comma-separated column names, each optionally
  followed by `ASC` or `DESC` (ascending by default):
  `order_by=last_name DESC,id`. Only plain column names are accepted;
  expressions are rejected with 400. End with a unique column so pages
  are stable. Without `order_by` the row order is whatever the database
  returns. The API does not look up a primary key to sort by.
- **`filter`** is a SQL `WHERE` clause in your database's syntax. See
  [what the read key may run](#what-the-read-key-may-run).
- **`pk_col`** is required for single-row requests: the API does not
  guess which column identifies a row. The value is sent as a parameter,
  never pasted into the SQL.

**Table and column names.** Plain names (`customers`, `dbo.customers`,
`catalog.schema.table`) are used as written, so your database's usual
case rules apply. A name with a space or other unusual character
(`Order Details`) is wrapped in the quote character the driver reports.
Names containing quotes, brackets, semicolons or parentheses are
rejected with 400.

---

## Writing rows

All of these need `WRITE_API_KEY`.

```http
POST /tables/customers
{"data": {"name": "Ada Lovelace", "email": "ada@example.com"}}

PATCH /tables/customers/192?pk_col=id
{"data": {"email": "ada@newmail.example"}}

DELETE /tables/customers/192?pk_col=id
```

- `PUT` and `PATCH` both update exactly the columns you send and leave
  the rest alone. They return 404 if no row has that key.
- `DELETE` returns 405 unless `ALLOW_DELETE=true`. Deleted rows cannot be
  recovered through the API.
- Each request is one statement, committed immediately (autocommit).
  There are no multi-request transactions.
- Values are always sent as `?` parameters.

---

## Raw SQL

```http
POST /query
{"sql": "SELECT city, COUNT(*) AS n FROM customers WHERE country = ? GROUP BY city", "params": ["CA"]}
```

The statement goes to the driver as written, so use your database's own
syntax. A statement that returns rows answers `{"rows": [...], "count": n}`;
anything else answers `{"message": "Query executed successfully"}`.
`limit`, `offset` and `order_by` do not apply here: a `SELECT` returns
every matching row, so limit it in the SQL.

---

## Database compatibility

The API sends plain ODBC: `?` parameters, simple `SELECT` / `INSERT` /
`UPDATE` / `DELETE`, `COUNT(*)`, and the driver's own catalog calls for
tables and columns. That works with any conforming driver. Two things
differ between engines and are handled in [api/dialect.py](api/dialect.py):

**Paging.** `ODBC_PAGING` selects how `limit`/`offset` are applied:

| Mode | SQL sent | Used by `auto` for |
| --- | --- | --- |
| `limit` | `... LIMIT n OFFSET m` | PostgreSQL, MySQL, MariaDB, SQLite, Actian Zen / Pervasive |
| `offset_fetch` | `... ORDER BY x OFFSET m ROWS FETCH NEXT n ROWS ONLY` | SQL Server 2012+, Oracle 12c+, Db2 |
| `client` | the plain `SELECT`; rows are skipped and capped in the cursor | everything else |

`auto` (the default) picks a mode from the DBMS name the driver reports.
An engine it does not recognise gets `client`, which is correct on every
database but slower on deep pages because skipped rows are still read.
If your engine supports one of the other two, set `ODBC_PAGING`
explicitly. `offset_fetch` needs an `ORDER BY`, so a request without
`order_by` is paged in the cursor instead.

**Quoting unusual names.** The quote character is asked of the driver.

### What has actually been tested

- The automated suite runs against a fake driver, plus an end-to-end run
  against a real SQLite ODBC driver in CI
  ([tests/test_sqlite_integration.py](tests/test_sqlite_integration.py)).
- Earlier versions of this code were run against Actian Zen (Pervasive)
  with `limit` paging and against a Sage Timberline driver with `client`
  paging.
- PostgreSQL, MySQL, SQL Server, Oracle and Db2 use standard syntax for
  their mode but have **not** been tested against live servers by this
  project. Reports and fixes are welcome.

### Installing a driver

- **Windows:** install the vendor's driver and create a DSN in *ODBC Data
  Sources*. Use the 32-bit or 64-bit administrator that matches your
  Python.
- **Linux:** `unixodbc` plus the driver package (for example
  `odbc-postgresql`, `msodbcsql18`, `libsqliteodbc`).
- **macOS:** `brew install unixodbc` plus the driver.

Check a DSN outside the API first with `isql -v <DSN>` (macOS/Linux).

---

## Health checks

None need a key, so load balancers and monitors can call them.

- `GET /` answers 200 whenever the process is running, and lists the
  configured databases.
- `GET /health/db` connects to every database. It returns 200 only if all
  are reachable, otherwise 503 with a per-database breakdown.
- `GET /health` (or `/<name>/health`) checks a single database.

By default a successful connection counts as healthy. Set
`ODBC_HEALTH_SQL` (for example `SELECT 1`, or `SELECT 1 FROM DUAL` on
Oracle) to also run a statement.

---

## Deployment

ODBC drivers and DSNs belong to a machine, so the API must run on a host
that has the driver installed and can reach the database.

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --workers 2
```

- Drop `--reload` in production and run under a process manager
  (`systemd`, a Windows service via [NSSM](https://nssm.cc/), Docker) so
  it restarts on failure and on boot.
- Put a reverse proxy (nginx, Caddy, IIS) in front for TLS, and bind
  uvicorn to `127.0.0.1` behind it.
- Each request opens its own connection and closes it afterwards, so
  multiple workers are safe. Size them to your database's connection
  budget.

**Before exposing it beyond a trusted network:**

- [ ] `API_KEY` and `WRITE_API_KEY` are long, random, different, and not committed anywhere
- [ ] `WRITE_API_KEY` is left blank unless writes are really needed
- [ ] The database login has only the permissions this API should have
- [ ] TLS is terminated in front of the app
- [ ] `CORS_ORIGINS` is unset, or lists only your real frontends (never `*`)
- [ ] `ALLOW_DELETE` is off unless you need it

---

## Development

```bash
pip install -r requirements-dev.txt
pytest                    # tests
ruff check . && ruff format --check .
pre-commit install        # optional: run ruff on every commit
```

The tests need no database: `tests/conftest.py` sets dummy settings and
blocks real ODBC connections, and [tests/fakes.py](tests/fakes.py)
provides a stand-in driver. The SQLite end-to-end tests run only when
the SQLite ODBC driver is installed and are skipped otherwise.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs ruff and
pytest on Python 3.12 for every pull request and every push to `main`.

### Project layout

```text
app.py                  create_app(): mounts the routers once per database
api/
  config.py             environment variables -> settings, validated at startup
  database.py           connections, and binding a route to its database
  dialect.py            paging mode and quote character per database
  security.py           X-Api-Key checks: read key, write key
  sql_guard.py          the read key's single-SELECT restriction
  utils.py              name validation, ORDER BY building, row conversion
  routers/
    health.py           /, /health/db, /health
    schema.py           /tables, /tables/{table}/schema
    crud.py             list, get, insert, update
    delete.py           delete (mounted only when ALLOW_DELETE=true)
    query.py            /query
tests/
CLAUDE.md               briefing for AI coding assistants (see below)
```

### Adding an endpoint

Create a router under `api/routers/`, protect it with
`Depends(verify_key)` (reads) or `Depends(require_write_key)` (writes)
from `api.security`, take the connection with `Depends(get_db)`, and add
the router to the list in `create_app()` in [app.py](app.py). It is then
mounted for every configured database.

---

## Build on it with Claude Code

The repository includes a [CLAUDE.md](CLAUDE.md): a briefing that
[Claude Code](https://claude.com/claude-code) reads automatically, so it
knows how the project is laid out, how to run and test it, and which
rules must not be broken (never expose `.env`, keep the read key
read-only, and so on).

Clone the repository, open the folder in a Claude Code session, and just
talk to it:

```bash
git clone https://github.com/manish-kth/odbc-rest-api-server.git
cd odbc-rest-api-server
claude
```

Things you can ask straight away:

- "Set this up and run it against my DSN."
- "Why can't it connect to my database?"
- "Add an endpoint that returns open invoices with their customer name."
- "My database isn't paged correctly — work out which mode it needs."
- "Help me deploy this as a Windows service behind HTTPS."
- "Write tests for the change you just made."

You stay in charge of credentials: put them in `.env` yourself, and
review anything that writes to a real database before it runs. Other AI
coding assistants can use the same file as a starting point.

---

## Limitations

- **No transactions across requests.** Every statement is committed on
  its own.
- **Single-column keys only.** Rows are addressed by one column and one
  value; for composite keys use `filter` to read and `/query` to write.
- **Key values are sent as text.** Most engines convert them to the
  column's type. If yours does not, use `/query` with typed `params`.
- **`GET /tables` returns names only**, without their schema, and lists
  tables but not views. Views can still be read by name.
- **No connection pooling in the app.** Each request opens a connection;
  enable pooling in your ODBC driver manager if connecting is slow.
- **Types are whatever the driver returns.** Dates and decimals are
  converted by FastAPI's default JSON encoder; binary columns may not
  serialise at all, so select around them with `/query`.
- **`total` costs a `COUNT(*)`** on every listing, which can be slow on
  very large tables.

---

## Bugs, security and contributing

This is used for real work, but it is a young project and it has only
met a handful of database engines. Help is very welcome, and every
report is appreciated.

- **Found a bug, or a database it does not work with?** Open an issue.
  The engine and driver name, the request you sent and the response you
  got are usually enough. Never paste a real key, password or connection
  string.
- **Found a security problem?** Please report it privately first, through
  **Security → Report a vulnerability** on the repository page, instead
  of a public issue, so it can be fixed before it is widely known. Ways
  around the read key's `SELECT`-only restriction, the identifier checks
  or the password masking are exactly what we want to hear about.
- **Tested it on an engine not listed under
  [Database compatibility](#database-compatibility)?** Tell us how it
  went, working or not.
- **Want to fix or add something?** Pull requests are welcome. Run
  `pytest` and `ruff check .` first, and add a test for the change.

Thank you to everyone who takes the time.

---

## How it was built

Most of the code here was written by AI — [Claude](https://claude.com/claude-code),
working in the editor alongside us. That is worth saying plainly.

It is just as true that the code was the smaller part. The hours went
into the human side: wrestling legacy drivers on a real server, deciding
what a read key should and should not be allowed to do, reading every
change, rejecting the ones that were wrong, and asking "what happens
if…" until the answers held up. The AI typed fast; people decided what
was worth typing.

If you find something neither of us caught, that is what the section
above is for.

---

## License

[MIT](LICENSE). Use it, change it, ship it — just keep the copyright
notice. It comes with no warranty: test against a copy of your data
before you point it at the real thing.
