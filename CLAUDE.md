# CLAUDE.md — Repair Shop Backend API

## Context
Simulated fixed-price freelance job ($150): make a small Task Management REST API reliable enough that a frontend developer can consume it without guessing what it returns. This is also a portfolio piece and a learning exercise. The human developer must be able to understand and defend every line.

You are the coding/execution agent. The user is the developer/reviewer. Architecture discussion and review happen in a separate conversation, so explain your decisions and don't settle open questions silently.

## Stack
- Python, FastAPI, PostgreSQL
- Dependency management: **uv** with `pyproject.toml`
- Data access: SQLAlchemy, SQLModel, or handwritten SQL. Propose one and justify it before adopting it.
- Migrations: required once PostgreSQL persistence is introduced (Alembic unless discussed otherwise)
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
- Length limits count characters, not bytes. They are enforced in the request schemas (Step 6). Whether to add a database-level `CHECK` as a second layer is open: propose it in the Step 3 report, don't add it unasked.

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

### Query parameters
- Unknown query parameters are rejected, not ignored.
- Every known query parameter has explicit validation constraints.
- All validation failures (body and query) are eventually converted into the single consistent JSON error structure.

## Out of scope — do NOT add
JWT, OAuth, Redis, Celery, Kafka, Kubernetes, microservices, AI features, frontend, distributed infrastructure, or abstractions the requirements don't need. No generic base repositories, DI containers, or plugin systems "for later". If you think something extra is justified, ask first.

## Architecture (request flow)
```
HTTP → FastAPI router → schemas/validation → service → repository → PostgreSQL
```
and back out through the response schemas. Each layer has one job. Routers contain no business logic, and services contain no SQL.

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
