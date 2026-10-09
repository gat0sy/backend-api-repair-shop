# Repair Shop Task API

[![CI](https://github.com/gat0sy/backend-api-repair-shop/actions/workflows/ci.yml/badge.svg)](https://github.com/gat0sy/backend-api-repair-shop/actions/workflows/ci.yml)

A small task management REST API built with **FastAPI** and **PostgreSQL**.
It's designed so a frontend developer can use it without guessing: every
response shape, status code and error format is fixed and documented here,
and interactive docs are generated from the code.

- Interactive docs (Swagger UI): http://127.0.0.1:8000/docs
- Alternative docs (ReDoc): http://127.0.0.1:8000/redoc
- OpenAPI document: http://127.0.0.1:8000/openapi.json

## Contents

- [Getting started](#getting-started)
- [API reference](#api-reference)
  - [Conventions](#conventions)
  - [The task object](#the-task-object)
  - [Endpoints](#endpoints)
  - [Creating a task](#creating-a-task)
  - [Updating a task (PATCH semantics)](#updating-a-task-patch-semantics)
  - [Listing tasks](#listing-tasks)
  - [Errors](#errors)
- [Testing](#testing)
- [Code quality](#code-quality)
- [Continuous integration](#continuous-integration)
- [Project structure](#project-structure)

---

## Getting started

### Run it (one command)

Requirements: Docker with Compose. Nothing else: no Python, no uv, no `.env`.

```bash
docker compose up --build
```

This starts three services, in order:

1. `db`: PostgreSQL 17. On first start, it also creates the separate
   `repair_shop_test` database used by the test suite.
2. `migrate`: applies the database migrations (`alembic upgrade head`), then exits.
3. `api`: the API, started only after the migrations succeed.

The API is then available at http://127.0.0.1:8000, with interactive docs at
http://127.0.0.1:8000/docs.

- Stop: `Ctrl+C`, or `docker compose down` if started with `-d`.
- Reset all data: `docker compose down -v` (deletes the database volume).
- After changing the code, run `docker compose up --build` again.

The credentials in `compose.yaml` are for local development only. Ports are
bound to `127.0.0.1`, so nothing is reachable from other machines.

### Local development (tests, auto-reload)

To run the test suite or the API with auto-reload on your machine, you also
need [uv](https://docs.astral.sh/uv/) (it installs the pinned Python 3.13
automatically if needed).

Configuration is read from environment variables. For local development, copy
the example file. `.env` is git-ignored, and its values are for development only.

```bash
cp .env.example .env
```

| Variable            | Used by             | Purpose                                                            |
|---------------------|---------------------|--------------------------------------------------------------------|
| `DATABASE_URL`      | app, `alembic`      | Development database                                               |
| `TEST_DATABASE_URL` | test suite          | Test database; its schema is reset on each run, so the name must end in `_test` |

Real environment variables override values in `.env`. The values in
`.env.example` point to the Compose database, which is published on host port
**5433** (so it doesn't conflict with a PostgreSQL on the default 5432).

Start only the database, apply the migrations, then run the API with
auto-reload:

```bash
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

(Stop the Compose `api` service first if it's running: both use port 8000.)

---

## API reference

### Conventions

These apply to every endpoint:

- **JSON only.** Request bodies must be sent with `Content-Type: application/json`
  (parameters like `; charset=utf-8` are fine). Anything else returns `415`.
  JSON Patch and JSON Merge Patch media types are not supported.
- **Strict input.** Unknown body fields and unknown query parameters are
  rejected with `422`, never silently ignored. Invalid values are rejected,
  never clamped or truncated.
- **Timestamps** are UTC in ISO 8601 with a `Z` suffix, e.g. `2026-10-08T12:34:56.123456Z`.
- **Ids** are integers from `1` to `2147483647`, assigned by the server.
  An id outside that range (or not an integer, e.g. `/tasks/abc`) is invalid
  input (`422`). A valid id that doesn't exist is `404`.
- **No trailing slashes.** `/tasks/` is `404`, not a redirect to `/tasks`.
- **Wrong method.** A method the URL doesn't support returns `405`, with an
  `Allow` header listing the supported methods.
- **Errors** always use the same [Problem Details](#errors) structure.

### The task object

```json
{
  "id": 42,
  "title": "Fix printer",
  "description": "Printer on floor 2",
  "status": "in_progress",
  "priority": "high",
  "created_at": "2026-10-08T09:00:00Z",
  "updated_at": "2026-10-08T09:30:00Z"
}
```

| Field         | Type             | Rules                                                                                                     |
|---------------|------------------|-----------------------------------------------------------------------------------------------------------|
| `id`          | integer          | Assigned by the server. Can't be sent by clients.                                                         |
| `title`       | string           | Required on create. Surrounding whitespace is stripped; must then be 1–255 characters. Never `null`.      |
| `description` | string or `null` | Optional. Up to 5000 characters, stored **exactly as given** (no stripping). `null` means no description. Always present in responses. |
| `status`      | string           | `todo`, `in_progress` or `done`. Defaults to `todo`. Never `null`.                                         |
| `priority`    | string           | `low`, `medium` or `high`. Defaults to `medium`. Never `null`.                                             |
| `created_at`  | string (UTC)     | Set by the server when the task is created.                                                               |
| `updated_at`  | string (UTC)     | Set by the server. Changes only when a value actually changes (see [PATCH](#updating-a-task-patch-semantics)). |

Length limits count characters, not bytes: `"é"` and `"🔧"` count as one each.

Neither `title` nor `description` may contain NUL characters (`\u0000`) or
unpaired UTF-16 surrogates (e.g. a lone `\ud800` escape): PostgreSQL can't
store them, so such text is rejected with `422`.

### Endpoints

| Method   | Path           | Success                     | Possible errors          |
|----------|----------------|-----------------------------|--------------------------|
| `POST`   | `/tasks`       | `201` task + `Location`     | 400, 415, 422            |
| `GET`    | `/tasks`       | `200` page of tasks         | 422                      |
| `GET`    | `/tasks/{id}`  | `200` task                  | 404, 422                 |
| `PATCH`  | `/tasks/{id}`  | `200` task                  | 400, 404, 415, 422       |
| `DELETE` | `/tasks/{id}`  | `204` no body               | 404, 422                 |

Any endpoint can also return `500` (unexpected server error).

### Creating a task

```bash
curl -i -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title": "  Fix printer  ", "priority": "high"}'
```

```http
HTTP/1.1 201 Created
content-type: application/json
location: /tasks/1

{"id":1,"title":"Fix printer","description":null,"status":"todo","priority":"high","created_at":"2026-10-08T09:00:00.460852Z","updated_at":"2026-10-08T09:00:00.460852Z"}
```

Only `title` is required. The `Location` header is the URL of the new task.

### Updating a task (PATCH semantics)

HTTP doesn't define one standard format for `PATCH` bodies, so this is the
exact behavior of `PATCH /tasks/{id}`:

- The body is a JSON object with any of `title`, `description`, `status`,
  `priority`. **Only the fields present are considered**; omitted fields are
  left unchanged.
- `{}` is valid and changes nothing.
- `description`:
  - omitted: unchanged
  - `null`: clears it
  - a string: replaces it
- `title`, `status` and `priority` can't be `null`; sending `null` is `422`.
  A `title` follows the same rules as on create.
- **`updated_at` changes only if at least one value actually changes.**
  Sending values identical to the stored ones (including a title that only
  differs by surrounding whitespace) is a valid no-op that leaves
  `updated_at` untouched.
- The response is always the full, current task.
- Concurrent PATCHes of the same task are applied one after the other, so
  neither overwrites the other's changes.

```bash
# Change the status only
curl -X PATCH http://127.0.0.1:8000/tasks/1 \
  -H 'Content-Type: application/json' -d '{"status": "done"}'

# Clear the description
curl -X PATCH http://127.0.0.1:8000/tasks/1 \
  -H 'Content-Type: application/json' -d '{"description": null}'
```

### Listing tasks

`GET /tasks` returns one page of tasks:

```json
{
  "items": [ { "id": 2, "title": "...", "...": "..." }, { "id": 1, "...": "..." } ],
  "total": 37,
  "limit": 20,
  "offset": 0
}
```

| Query parameter | Default | Rules                                                     |
|-----------------|---------|-----------------------------------------------------------|
| `status`        | (all)   | `todo`, `in_progress` or `done`                           |
| `priority`      | (all)   | `low`, `medium` or `high`                                 |
| `limit`         | `20`    | Maximum number of tasks returned. `1` to `100`.           |
| `offset`        | `0`     | Number of matching tasks skipped first. `0` to `9223372036854775807` (2^63−1, PostgreSQL's 64-bit limit). |

- All parameters can be combined:
  `GET /tasks?status=todo&priority=high&limit=10&offset=20`.
- **Ordering** is always newest first: `created_at` descending, then `id`
  descending for tasks created at the same instant. Pages are stable.
- **`total`** is the number of tasks matching the filters, ignoring
  `limit`/`offset`. An `offset` past the end returns an empty `items` list,
  with `total` still filled in.
- **Out-of-range values are rejected, not clamped**: `limit=0`, `limit=500`,
  `offset=-1` and `offset=9223372036854775808` are all `422`.
- **Repeated parameters: the last value wins.** For example,
  `?limit=5&limit=10` uses `limit=10`. Earlier values are ignored and not
  validated, so `?limit=abc&limit=5` is accepted as `limit=5`, while
  `?limit=5&limit=500` is rejected because `500` is invalid. Send each
  parameter once.
- `items` and `total` come from two queries in the same transaction. If tasks
  are created or deleted at the same moment, `total` can be briefly off by
  that change. This is normal for paginated APIs.

### Browser frontends (CORS)

A frontend served from a different origin (for example a dev server on
`http://localhost:3000`) can only call the API if that origin is allowed.
List the allowed origins in `CORS_ORIGINS`, comma-separated:

```bash
CORS_ORIGINS=http://localhost:3000 docker compose up --build
```

(or put `CORS_ORIGINS=...` in `.env`). Rules:

- By default no origin is allowed. `*` (any origin) is rejected on purpose.
- Each entry is an exact origin: `scheme://host[:port]`, no path, no trailing
  slash. An invalid entry stops the API at startup with an error.
- Allowed methods are `GET`, `POST`, `PATCH`, `DELETE`; the only allowed request
  header is `Content-Type`. Frontend code can read the `Location` header.
- No credentials (cookies or auth headers): the API has no authentication.
- A rejected preflight request gets `400` in the usual error format.

### Errors

Every error response uses [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457),
with `Content-Type: application/problem+json` and always the same five keys:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Content",
  "status": 422,
  "detail": "The request contains invalid data.",
  "errors": [
    {"location": "query", "field": "foo", "message": "Unknown query parameter."},
    {"location": "body", "field": "title", "message": "title must not be empty or whitespace-only"},
    {"location": "body", "field": "priority", "message": "Input should be 'low', 'medium' or 'high'"}
  ]
}
```

| Key      | Meaning                                                                                  |
|----------|------------------------------------------------------------------------------------------|
| `type`   | Always `about:blank`. Distinguish errors by `status`.                                    |
| `title`  | The HTTP status phrase.                                                                  |
| `status` | The HTTP status code.                                                                    |
| `detail` | Human-readable explanation.                                                              |
| `errors` | For `422`: every problem found, each with `location` (`body`, `query` or `path`), `field` (or `null` for the whole body) and `message`. Empty for every other status. |

| Status | When                                                                                              |
|--------|---------------------------------------------------------------------------------------------------|
| `400`  | The body is not valid JSON, or a CORS preflight request was rejected.                             |
| `404`  | The task doesn't exist, or the URL doesn't exist.                                                 |
| `405`  | The method isn't supported at this URL (`Allow` lists the supported ones).                        |
| `415`  | A request body isn't sent as `application/json` (including a body sent with no `Content-Type`).   |
| `422`  | Invalid input: field rules, unknown fields or query parameters, out-of-range values, invalid ids. |
| `500`  | Unexpected server error. No internal details are included.                                        |

Error responses never echo the submitted values back.

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "Task 42 not found.",
  "errors": []
}
```

---

## Testing

The test suite needs the database running (`docker compose up -d db`, and a
`.env` as described in [Local development](#local-development-tests-auto-reload)).
It uses the separate `repair_shop_test` database and rebuilds its schema
through the migrations on every run.

```bash
uv run pytest
```

To run only the tests that don't need a database:

```bash
uv run pytest --ignore=tests/db
```

The tests cover each layer on its own (domain rules, schemas, repository,
service), the HTTP API, the error format, the OpenAPI document, and full-stack
behavior against PostgreSQL (real commits, rollback on errors, concurrent
updates).

## Code quality

[Ruff](https://docs.astral.sh/ruff/) lints and formats the code, and
[mypy](https://mypy.readthedocs.io/) type-checks it in strict mode (with the
Pydantic plugin). Settings live in `pyproject.toml`.

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting (drop --check to reformat)
uv run mypy                    # type-check app/, tests/ and migrations/
```

## Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and
on every pull request, as three parallel jobs:

| Job       | What it checks                                                                                       |
|-----------|------------------------------------------------------------------------------------------------------|
| `quality` | `ruff check`, `ruff format --check`, `mypy`, and that the generated OpenAPI document is a valid spec |
| `test`    | The full test suite against a PostgreSQL 17 service container                                        |
| `compose` | The one-command start: `docker compose up --build`, then a create request and an error response, then `docker compose down -v` |

Dependencies are installed exactly as locked (`uv sync --frozen`), with the
same uv version as local development and the Docker image.

## Project structure

```
app/
  domain.py      Task rules (title normalization, defaults, PATCH change detection). No framework code.
  db.py          Table definition (SQLAlchemy Core).
  repository.py  All SQL for tasks. Never commits; the caller owns the transaction.
  service.py     Use cases (create/get/list/update/delete). No SQL.
  schemas.py     Request/response JSON shapes and validation (Pydantic).
  api.py         HTTP routes. One transaction per request, opened after validation.
  errors.py      The Problem Details error format and its documentation.
  config.py      Settings from environment variables.
  main.py        App setup.
migrations/      Alembic migrations (the only way the schema changes).
tests/           Unit tests; tests/db/ needs PostgreSQL.
Dockerfile       The API image (also used by the one-shot migration service).
compose.yaml     Local stack: db, migrate, api.
docker/          PostgreSQL init script (creates the test database).
.github/         CI workflow.
```

A request flows `HTTP → route → schema validation → service → repository → PostgreSQL`
and back. Invalid requests are rejected before any database work starts.
