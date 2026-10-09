# CLAUDE.md — Repair Shop Backend API

## Context
Simulated fixed-price freelance job ($150): make a small Task Management REST API reliable enough that a frontend developer can consume it without guessing what it returns. This is also a portfolio piece and a learning exercise. The human developer must be able to understand and defend every line.

You are the coding/execution agent. The user is the developer/reviewer. Architecture discussion and review happen in a separate conversation, so explain your decisions and don't settle open questions silently.

## Stack
- Python, FastAPI, PostgreSQL
- Dependency management: **uv** with `pyproject.toml`
- Data access: **SQLAlchemy Core** (no ORM), synchronous, **psycopg 3** driver. Chosen over the ORM (redundant change tracking and session semantics, since change detection lives in the domain), SQLModel (merges the schema and persistence layers), and handwritten SQL (manual mapping, no Alembic autogenerate).
- Migrations: **Alembic**. Migrations are snapshots: they write values literally and never import app code.
- Configuration: environment variables via **pydantic-settings** (`DATABASE_URL`, `TEST_DATABASE_URL`). `.env` is for local development only and is git-ignored, and `.env.example` documents it.
- Tests: pytest

## Domain
Task fields: `id`, `title`, `description`, `status`, `priority`, `created_at`, `updated_at`

## Endpoints
- `POST /tasks`: create
- `GET /tasks`: list, with `status`, `priority`, `limit`, `offset` (all combinable)
- `GET /tasks/{id}`: retrieve
- `PATCH /tasks/{id}`: partial update
- `DELETE /tasks/{id}`: delete

## Requirements
- Validate incoming JSON and query parameters
- Correct HTTP status codes
- One consistent JSON error structure for every error, documented
- Nonexistent IDs handled correctly
- Clean repository boundary between business logic and persistence
- Basic automated tests that pass
- Swagger/OpenAPI docs via FastAPI
- Starts from a clean checkout with one documented command or Docker Compose

## API contract (final, settled in review)
These are contract decisions. Implement each one in the build step it belongs to, not earlier. Don't change any of them silently: if implementation suggests a different behavior or value, raise it as an open question first.

### Identifier
- `id` is an auto-incrementing integer (Postgres identity column), assigned by the database. Clients never supply it.
- A malformed ID (e.g. `/tasks/abc`) is rejected as invalid input. A well-formed ID that doesn't exist (e.g. `/tasks/99999`) returns 404. Both use the single JSON error structure.
- Chosen over UUID because the project has one database, no auth, and no distributed ID generation. Revisit only if that changes.

### Title
- Required on create.
- `""` is invalid. Whitespace-only strings (e.g. `"   "`, `"\t\n"`) count as empty and are rejected.
- Surrounding whitespace is stripped: `"  Fix printer  "` → `"Fix printer"`.
- `title: null` is rejected.
- The same rules apply when `title` is provided in PATCH.
- Maximum length: **255 characters**, measured after stripping. Over-limit input is rejected, never truncated.

### Description
- Optional on create. A task doesn't need one. May be `null`.
- PATCH: omitted = leave unchanged. `null` = clear it. `"some text"` = replace it.
- Responses always include `description`, with `null` meaning none.
- Maximum length: **5000 characters**. Over-limit input is rejected, never truncated.
- Stored exactly as given: no stripping and no conversion. `""` and whitespace-only strings stay as they are. Only `null` means "no description".
- Length limits (title and description) count characters, not bytes. The request schemas (Step 6) are the primary enforcement. The database enforces them too, as a second layer: `CHECK (char_length(title) BETWEEN 1 AND 255)` and `CHECK (description IS NULL OR char_length(description) <= 5000)`.

### Status
- Exactly: `todo`, `in_progress`, `done`.
- New tasks default to `todo`.
- `status: null` is invalid on PATCH. Status can never be set to null.

### Priority
- Exactly: `low`, `medium`, `high`.
- New tasks default to `medium`.
- `priority: null` is invalid on PATCH. Priority can never be set to null.
- The public API uses string values only. Never expose numeric priorities.
- If ordering/comparison is needed internally, use an internal mapping (low=1, medium=2, high=3).

### Request bodies
- Unknown/unrecognized fields are rejected, not silently ignored.
- Media type: POST and PATCH bodies must be `application/json`. Parameters and case don't matter (`application/json; charset=utf-8` is fine). Any other `Content-Type`, including `+json` types such as `application/merge-patch+json`, or a body sent without `Content-Type`, gets **415**. A request with no body at all gets the normal 422 (missing body).
- Syntactically invalid JSON gets **400**. JSON that parses but has invalid values gets **422**.

### PATCH semantics
- PATCH is a partial update. Only provided fields are considered.
- `{}` is valid and is a no-op.
- A PATCH with no effective change is valid.
- If no persisted value actually changes, `updated_at` stays unchanged.
- If one or more persisted values change, `updated_at` is updated.
- Don't bump `updated_at` blindly on every PATCH. This rules out naive ORM `onupdate`/DB-trigger approaches that fire on any UPDATE. Detect actual changes.
- These semantics must be explicitly documented in the API contract/README, because HTTP PATCH doesn't define a universal patch-document format.
- Don't introduce JSON Patch or JSON Merge Patch media types unless a later design decision calls for them.

### Pagination (`GET /tasks`)
- `limit` = maximum number of tasks returned. Default **20**, minimum **1**, maximum **100**.
- `offset` = number of matching tasks skipped before collecting results. Default **0**, must be non-negative.
- Out-of-range values (e.g. `limit=500`, `limit=0`, `offset=-1`) are rejected, never silently clamped.
- `status` and `priority` filters are combinable with pagination.
- Deterministic ordering: `created_at DESC`, then `id DESC` as the tie-breaker.
- 20, 100 and this ordering are explicit project-contract choices. Don't change them silently.
- Response shape: `{"items": [...], "total": <int>, "limit": <int>, "offset": <int>}`. `total` is the number of tasks matching the filters, ignoring pagination.
- `total` and `items` come from two queries in the same transaction at the default isolation level (READ COMMITTED). A concurrent write between them can make `total` differ slightly from the page. This is accepted, normal pagination behavior. Do **not** use REPEATABLE READ.
- No index for the list query for now. Revisit only if data volume justifies it.

### Query parameters
- Unknown query parameters are rejected (422) on **every** endpoint, not just `GET /tasks`. This uses Pydantic query models with `extra="forbid"`; endpoints without query parameters declare an empty one.
- Every known query parameter has explicit validation constraints.
- All validation failures (body and query) are converted into the single error structure.
- Repeated scalar query parameters: **the last value wins** (FastAPI's behavior, kept on purpose). Earlier values are ignored and **not validated**: `?limit=abc&limit=5` is accepted as `limit=5`, and `?limit=5&limit=500` is rejected because 500 is invalid. Tests pin this behavior so a FastAPI upgrade that changes it is noticed. Known consequence: turning an existing scalar parameter into a multi-value one later (e.g. `status`) would be a breaking change for clients that send repeats.

### URLs and methods
- One canonical URL per resource. No trailing-slash redirects (`redirect_slashes=False`), so `/tasks/` is 404.
- 405 responses list **every** method the URL supports in `Allow` (RFC 9110). Starlette alone lists only the first matching route's methods.

### Error structure (RFC 9457 Problem Details)
- Every error response uses `Content-Type: application/problem+json` and exactly these keys:
  `{"type": "about:blank", "title": <HTTP status phrase>, "status": <code>, "detail": <explanation>, "errors": [...]}`.
- `type` is always `about:blank`, so clients distinguish errors by `status`. No custom type URIs.
- `errors` is always present. For 422 it lists every problem at once as `{"location": "body"|"query"|"path", "field": <dotted name or null>, "message": <text>}`. For every other status it is empty.
- Status codes:
  - 400: malformed JSON.
  - 404: unknown task or unknown URL.
  - 405: method not allowed.
  - 415: wrong media type.
  - 422: invalid input.
  - 500: unexpected error.
- Never echo client input, and never expose internal details on 500. The server logs the traceback.

## Out of scope — do NOT add
JWT, OAuth, Redis, Celery, Kafka, Kubernetes, microservices, AI features, frontend, distributed infrastructure, or abstractions the requirements don't need. No generic base repositories, DI containers, or plugin systems "for later". If you think something extra is justified, ask first.

## Architecture (request flow)
```
HTTP → FastAPI router → schemas/validation → service → repository → PostgreSQL
```
and back out through the response schemas. Each layer has one job. Routers contain no business logic, and services contain no SQL.

## Persistence decisions (settled)
- Table `tasks`: `id INTEGER GENERATED ALWAYS AS IDENTITY` (the database assigns ids and refuses explicit ones). `title`/`description` are `TEXT`. `status`/`priority` are `TEXT` with `CHECK (... IN (...))`, not native Postgres ENUMs. Timestamps are `timestamptz NOT NULL`.
- No server defaults. The application supplies status/priority defaults (domain) and both timestamps.
- Timestamps come from the application clock (UTC, timezone-aware). The service passes one `now` for inserts and for PATCHes that actually change something.
- Transactions: **one transaction per HTTP request**, owned by the application/request layer. It commits on success and rolls back on error. Repository methods never commit or roll back, and neither does the service.
- Invalid requests never touch the database. The transaction is opened in the route body (`with services.begin() as service:`), which FastAPI runs only after all path, query and body validation has passed, and it is committed before the response is sent. Dependencies do no I/O, because FastAPI runs them before parameter validation.
- PATCH runs read-modify-write in that one transaction. The row is locked with `SELECT ... FOR UPDATE` (`TaskRepository.get(..., for_update=True)`), so concurrent PATCHes can't overwrite each other's changes.
- Local development database: the Docker Compose `db` service (`postgres:17`), published on `127.0.0.1:5433`, which is what `.env.example` points to. On first initialization of its volume, an init script (`docker/postgres/init/`) creates `repair_shop_test`. The test suite uses that separate database, whose name must end in `_test`, and its schema is rebuilt through the migrations on every run.

## Running (settled)
- One command from a clean checkout: `docker compose up --build`. It starts `db`, then a one-shot `migrate` service (`alembic upgrade head`), then `api` on `127.0.0.1:8000`, but only after the migrations succeed. Migrations are never run from the API container's startup command.
- One image (`Dockerfile`) serves both `migrate` and `api`: `python:3.13-slim`, uv pinned to the development version, `uv sync --frozen --no-dev`, non-root user. `.dockerignore` keeps `.env`, `.venv`, `.git` and the tests out of it.
- Compose credentials are for local development only, and ports are bound to `127.0.0.1`.
- Local development (tests, `--reload`): `docker compose up -d db`, then the `uv run ...` commands with `.env` copied from `.env.example`.

## Build order (inside-out)
1. Project bootstrap
2. Core/domain behavior + tests
3. Database and persistence (+ migrations)
4. Repository
5. Service layer
6. FastAPI/API layer
7. Validation and error guardrails
8. Integration/API tests
9. OpenAPI docs + README
10. Code quality tooling (lint/format/type-check)
11. Docker / Docker Compose
12. CI pipeline

Work on one step at a time. Don't start the next step until the user says so. Tests are the behavioral map: write or update them alongside each layer.

## Working rules
- Explain important decisions and the alternatives you rejected, briefly.
- State assumptions explicitly. When uncertain, say so instead of guessing.
- Keep changes scoped to the current step. Don't refactor unrelated code.
- Prefer the simplest maintainable solution.
- Prefer framework-native mechanisms (FastAPI/Pydantic) when they satisfy the requirement; don't recreate existing framework functionality without a concrete reason.
- For ambiguous constraints, propose the exact behavior before implementing it.
- Run the tests after every change and report the real output (pass/fail counts, failures). Never claim tests pass without running them.
- Don't commit or push unless asked. Suggest a commit message per step.

## End-of-step report
After each step, report:
1. What changed (files, briefly)
2. Key decisions and why
3. Assumptions / open questions
4. Test results (actual command + summary)
5. Suggested commit message
