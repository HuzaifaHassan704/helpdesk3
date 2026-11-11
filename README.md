# Helpdesk Ticket Management API

FastAPI · SQLAlchemy 2.0 (async) · Alembic · Pydantic v2 · JWT · structlog · slowapi · pytest · Docker · GitHub Actions

## Contents
1. [Quick start (local)](#1-quick-start-local)
2. [Database migrations (Alembic)](#2-database-migrations-alembic)
3. [Logging & request IDs](#3-logging--request-ids)
4. [Rate limiting & security hardening](#4-rate-limiting--security-hardening)
5. [Tickets API: filtering & pagination](#5-tickets-api-filtering--pagination)
6. [Tests, lint, coverage](#6-tests-lint-coverage)
7. [Docker & docker compose](#7-docker--docker-compose)
8. [CI (GitHub Actions)](#8-ci-github-actions)
9. [Configuration reference](#9-configuration-reference)
10. [Endpoints & permission rules](#10-endpoints--permission-rules)

## 1. Quick start (local)

Requires Python 3.11+ (https://python.org). From the project folder run **one command**:

```bash
python start.py          # Windows: python start.py   (or double-click start.bat)
```

On the first run it creates `.venv`, installs the packages, writes `.env` (with a random `SECRET_KEY`), creates the
SQLite database, creates the first admin and opens **http://127.0.0.1:8000/**. Later runs start in seconds.

* First admin: `admin@example.com` / `StrongPass123` (override with the `ADMIN_EMAIL` / `ADMIN_PASSWORD` environment variables on the first run).
* API docs: http://127.0.0.1:8000/docs
* `python start.py test` runs the test suite. Options: `--port 8001`, `--reload`, `--no-browser`.

Manual setup, if you prefer: `python -m venv .venv`, activate it, `pip install -r requirements-dev.txt`, copy `.env.example` to `.env`,
`alembic upgrade head`, `python -m scripts.create_admin admin@example.com "Admin" "StrongPass123"`, `uvicorn app.main:app --reload`.

PostgreSQL locally: `docker compose up -d db`, then set `DATABASE_URL=postgresql+asyncpg://helpdesk:helpdesk@localhost:5432/helpdesk` in `.env`
and run `python start.py` again.

## 2. Database migrations (Alembic)

`alembic/env.py` is async and takes both the URL (`DATABASE_URL`) and the metadata (`Base.metadata`, with every
model imported) from the application, so there is nothing to configure in `alembic.ini`. Constraint names follow a
naming convention (`app/core/database.py`), which keeps autogenerate and downgrades deterministic.

```bash
alembic upgrade head                                  # apply all migrations
alembic downgrade -1                                  # roll back one
alembic current / alembic history                     # inspect
alembic upgrade head --sql > schema.sql               # emit SQL without connecting (for DBAs)

# after changing a model:
alembic revision --autogenerate -m "add ticket category"
#   REVIEW the generated file in alembic/versions/, then:
alembic upgrade head
alembic check                                         # exits non-zero if models and migrations differ
```

`tests/test_migrations.py` fails the build if a model changes without a matching migration, if upgrade/downgrade
break, or if there is more than one head. SQLite uses Alembic's batch mode automatically.

## 3. Logging & request IDs

All logs, including uvicorn's and SQLAlchemy's, go through structlog and print one JSON object per line
(`LOG_JSON=false` gives readable console output for development).

* `RequestContextMiddleware` (pure ASGI) reads `X-Request-ID` or generates one, returns it in the response header and
  binds it to every log line produced while handling the request. Incoming IDs that are not 8-128 characters of
  `[A-Za-z0-9._-]` are replaced, so a client cannot inject arbitrary text into your logs.
* Each request produces one summary line: `method`, `path`, `status_code`, `duration_ms`, `client_ip`, `request_id`,
  plus `user_id` / `user_role` once the caller is authenticated. 5xx = `error`, 4xx = `warning`, otherwise `info`.
  Unhandled exceptions log `request_failed` with the stack trace. Health checks log at `debug`.
* Query strings, passwords, tokens and submitted emails are never logged (failed logins log `login_failed` only).

```json
{"event": "request_completed", "method": "GET", "path": "/users/me", "status_code": 200, "duration_ms": 3.1,
 "request_id": "ede2b90ccd824c908cd78370c5e2612b", "user_id": 1, "user_role": "admin", "level": "info", "timestamp": "..."}
```

Log from your own code with `from app.core.logging import get_logger; logger = get_logger("app.x"); logger.info("event_name", key=value)`.

## 4. Rate limiting & security hardening

**Rate limits** (slowapi, per client IP; `limits` syntax, configurable via env):

| Endpoint | Env var | Default |
|---|---|---|
| `POST /auth/login` | `RATE_LIMIT_LOGIN` | `5/minute` |
| `POST /auth/register` | `RATE_LIMIT_REGISTER` | `10/hour` |
| `POST /tickets/` | `RATE_LIMIT_CREATE_TICKET` | `30/minute` |

Exceeded limits return `429 {"detail": "Rate limit exceeded: ..."}`. The default store is in-process memory, which is
**per worker**. With more than one worker or replica set `RATE_LIMIT_STORAGE_URI=redis://host:6379/0` (compose does this).
Behind a reverse proxy, run uvicorn with `--proxy-headers` and `FORWARDED_ALLOW_IPS=<proxy ip>` so the real client IP
is used rather than the proxy's.

**Headers** on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy`, `Cross-Origin-Resource-Policy`, `Content-Security-Policy: default-src 'none'`, `Cache-Control: no-store`,
and `Strict-Transport-Security` when `ENVIRONMENT=production`. The CSP/cache headers skip `/docs` and `/redoc` so Swagger UI still works.

**CORS** is off unless `CORS_ORIGINS` lists explicit origins. It allows only `GET/POST/PATCH/DELETE/OPTIONS`, the
`Authorization`, `Content-Type` and `X-Request-ID` request headers, and no credentials (the API uses bearer tokens, not cookies).
**`ALLOWED_HOSTS`** restricts the `Host` header (include `localhost` if you use the Docker health check).

**Fail-fast production guards:** with `ENVIRONMENT=production` the app refuses to start unless `SECRET_KEY` is 32+
characters and not the default, and `CORS_ORIGINS` contains no `*`. Set `ENABLE_DOCS=false` to hide `/docs` and `/openapi.json`.

## 5. Tickets API: filtering & pagination

`GET /tickets/` returns newest first. Filters: `status`, `priority`, `assignee_id`, `search` (title or description,
case-insensitive, `%`/`_` treated literally), `created_from`, `created_to` (ISO 8601; naive values are treated as UTC).

```jsonc
{
  "items": [ ... ],
  "total": 57,          // matching the filters
  "skip": 20, "limit": 20,
  "page": 2, "pages": 3,
  "has_next": true, "has_prev": true,
  "next_cursor": "aWQ6Mzg"   // continue with ?cursor=...
}
```

* **Offset:** `?skip=20&limit=20` or `?page=2&limit=20` (`page` wins). Also sends `X-Total-Count`.
* **Cursor (keyset):** `?limit=20&cursor=<next_cursor>`. Cost does not grow with page depth and results do not shift when
  tickets are created mid-pagination. `page` is `null` in cursor mode. Combining `cursor` with `skip`/`page` returns 400.
* **Indexes** (see the initial migration): `(status, priority)`, `(assignee_id, status)`, `(creator_id, created_at)`,
  `created_at`, plus single-column indexes on `status`/`priority`. FK columns `creator_id`/`assignee_id` are covered as the leading
  columns of the composites (a separate single-column index would only slow writes).
* Not yet indexed: substring `search` uses `ILIKE '%term%'`, which a B-tree cannot serve. For large tables add a PostgreSQL
  `pg_trgm` GIN index in a migration.

## 6. Tests, lint, coverage

```bash
pytest                                              # 103 tests, in-memory SQLite, no services needed
pytest --cov --cov-report=term-missing              # coverage (~95%)

# the same suite against PostgreSQL (what CI does):
TEST_DATABASE_URL=postgresql+asyncpg://helpdesk:helpdesk@localhost:5432/helpdesk pytest
#   (PowerShell: $env:TEST_DATABASE_URL="postgresql+asyncpg://..."; pytest)   NOTE: this DB's tables are dropped.

ruff check .            # lint        (ruff check --fix . to auto-fix)
ruff format .           # format      (ruff format --check . in CI)
```

Rate limiting is disabled during the suite and switched on only inside `tests/test_rate_limit.py`.

## 7. Docker & docker compose

The `Dockerfile` is multi-stage (dependencies built in a throwaway stage, runtime image has only the venv and code),
runs as a non-root user, and has a `HEALTHCHECK` on `/health/live`.

```bash
export SECRET_KEY=$(openssl rand -hex 32)            # PowerShell: $env:SECRET_KEY = python -c "import secrets;print(secrets.token_hex(32))"
docker compose up --build
docker compose run --rm api python -m scripts.create_admin admin@example.com "Admin" "StrongPass123"
curl http://localhost:8000/health/ready
```

Services: `db` (PostgreSQL 16, `pg_isready` health check) → `migrate` (one-shot `alembic upgrade head`, so migrations
run once rather than racing on every replica) → `api` (health check on `/health/ready`, i.e. the DB is reachable) and `redis`
(shared rate-limit counters). `docker compose up -d db` alone gives you just PostgreSQL for local development.
Compose sets `ENVIRONMENT=production`, so docs are hidden unless `ENABLE_DOCS=true`. Change `POSTGRES_PASSWORD` outside local use.

`/health/live` = process is up. `/health/ready` = the database answers (503 otherwise).

## 8. CI (GitHub Actions)

`.github/workflows/ci.yml` runs on pushes to `main` and on pull requests:
1. **lint:** `ruff check` and `ruff format --check`.
2. **test:** Python 3.12 and 3.13 against a PostgreSQL 16 service: `alembic upgrade head` → `alembic check` →
   `alembic downgrade base` → `pytest --cov --cov-fail-under=90`; uploads `coverage.xml`.
3. **docker:** builds the image and checks that it runs as non-root and imports cleanly.

## 9. Configuration reference

See `.env.example` for every variable with comments. Highlights: `ENVIRONMENT`, `DATABASE_URL`, `SECRET_KEY`,
`LOG_JSON`/`LOG_LEVEL`, `CORS_ORIGINS`, `ALLOWED_HOSTS`, `RATE_LIMIT_*`, `ENABLE_DOCS`, `DB_POOL_SIZE`, `WEB_CONCURRENCY` (uvicorn workers).

## 10. Endpoints & permission rules

| Method | Path | Access |
|---|---|---|
| POST | `/auth/register` | Public → Employee; Admin token required for `agent`/`admin` (rate limited) |
| POST | `/auth/login` | Public, form fields `username` (email) + `password` (rate limited) |
| GET | `/users/me` | Any authenticated user |
| GET/PATCH/DELETE | `/users/`, `/users/{id}` | Admin |
| POST | `/tickets/` | Employee, Admin (rate limited) |
| GET | `/tickets/` | Employee (own) · Agent/Admin (all) |
| GET | `/tickets/{id}`, `/tickets/{id}/history` | Owner · Agent/Admin |
| GET | `/tickets/export.csv` | Agent, Admin |
| POST | `/users/me/password` | Any authenticated user |
| PATCH | `/tickets/{id}` | Employee: own `title`/`description`/`priority`, may close or reopen a resolved ticket · Agent: `status`/`priority` · Admin: all |
| POST | `/tickets/{id}/assign` | Agent, Admin (empty body = assign to self) |
| DELETE | `/tickets/{id}` | Admin |
| POST/GET | `/tickets/{id}/comments` | Owner · Agent/Admin (internal notes hidden from employees) |
| GET | `/dashboard/stats` | Agent, Admin |
| GET/POST/PATCH/DELETE | `/admin/settings/`, `/admin/settings/{key}` | Admin (system configuration) |
| GET | `/system/public` | Public (company name, whether sign-up is open) |
| GET | `/health/live`, `/health/ready` | Public |

## Web interface

Start the server and open **http://127.0.0.1:8000/** (the API docs stay at `/docs`). Sign in or register; Employees create and
follow their tickets, Agents work the queue (assign, change status/priority, internal notes), Admins also get the Dashboard and Users pages.
The UI is plain HTML/CSS/JS in `app/static/` (no build step) and calls the same API.

## Status workflow

`Open -> In Progress -> Resolved -> Closed`, enforced by the API (`TRANSITIONS` in `app/services/ticket_service.py`).

| From | Allowed next statuses |
|---|---|
| Open | In Progress, Closed |
| In Progress | Open, Resolved, Closed |
| Resolved | In Progress, Open (reopen), Closed |
| Closed | Open, admin only |

An invalid change returns `409`; a change the role may not make returns `403` (Employees may only close their own ticket or reopen a resolved one).
Every ticket response includes `allowed_statuses`, the next statuses the current user can choose, which the web UI uses to build its dropdown.

## System settings (Admin)

Admins have full CRUD on runtime configuration: `GET/POST /admin/settings/`, `GET/PATCH/DELETE /admin/settings/{key}`, or use the **Settings** page.
Changes apply immediately and are written to the audit log. Built-in keys (seeded by migration `0002`, with code defaults if deleted):

| Key | Effect |
|---|---|
| `company_name` | Shown in the web UI header and login page (`GET /system/public`, no login needed) |
| `allow_employee_registration` | `false` closes public sign-up (admins can still create users) |
| `max_open_tickets_per_employee` | Employees cannot exceed this many Open/In Progress tickets (admins are exempt) |

## Enhancements (v2.2)

* **Ticket history:** every create, edit, priority/status change, assignment and public comment is stored (`GET /tickets/{id}/history`, shown in the ticket dialog).
* **SLA due dates:** each ticket gets `due_at` from its priority (settings `sla_hours_urgent|high|medium|low`, default 4/8/24/72 h); `is_overdue` is flagged on tickets and counted on the dashboard.
* **Auto-assign:** setting `auto_assign_on_create=true` gives new tickets to the active agent with the fewest Open/In Progress tickets.
* **Email notifications:** assignment and status changes email the person concerned. Set `SMTP_HOST` (and `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`) in `.env`; without it emails are only written to the log.
* **Accounts:** `POST /users/me/password` (also the **Password** button). After `LOGIN_MAX_ATTEMPTS` (5) failed logins from one IP against one email, that IP/email pair is refused for `LOCKOUT_MINUTES` (15). Other IPs, including the real owner, are not affected. Unknown emails are throttled the same way and every failure is the same `401 Incorrect email or password`, so nothing reveals which accounts exist (bcrypt also runs for unknown emails, so timing doesn't either). Emails are stored only as a SHA-256 hash in `login_attempts`. An admin can clear the counters with `PATCH /users/{id}` `{"unlock": true}`.
* **Reporting & UI:** `GET /tickets/export.csv` (agents/admins, honours the filters, formula-injection safe, **CSV** button) and a light/dark/auto theme switch.

## Layout

```
app/
  core/      config, database, security, deps (RBAC), logging, middleware, rate_limit, pagination
  models/  schemas/  services/  routers/
alembic/     env.py (async) + versions/
scripts/     create_admin.py
tests/       auth, rbac, tickets, pagination, middleware, rate_limit, migrations, config, dashboard
Dockerfile  docker-compose.yml  .github/workflows/ci.yml  pyproject.toml (ruff, coverage)
```
