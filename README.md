# Repair Shop Task API

Task Management REST API built with FastAPI and PostgreSQL.

> Work in progress. Full API contract and documentation will be added in a later step.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs the pinned Python 3.13 automatically if needed)
- Docker (for the local PostgreSQL database)

## Local setup

### 1. Configuration

Configuration is read from environment variables. For local development, copy
the example file. `.env` is git-ignored, and its values are for development only.

```bash
cp .env.example .env
```

| Variable            | Used by             | Purpose                                                   |
|---------------------|---------------------|-----------------------------------------------------------|
| `DATABASE_URL`      | app, `alembic`      | Development database                                      |
| `TEST_DATABASE_URL` | test suite          | Test database; schema is reset each run, name must end in `_test` |

Real environment variables override values in `.env`.

### 2. Database

Start PostgreSQL 17 in Docker. It uses host port **5433**, so it doesn't
conflict with a PostgreSQL already running on the default 5432:

```bash
docker run -d --name repair-shop-db \
  -e POSTGRES_USER=repair_shop -e POSTGRES_PASSWORD=repair_shop -e POSTGRES_DB=repair_shop \
  -p 127.0.0.1:5433:5432 -v repair-shop-pgdata:/var/lib/postgresql/data \
  postgres:17
```

Create the separate test database (once, after the container is up):

```bash
docker exec repair-shop-db createdb -U repair_shop repair_shop_test
```

Apply the migrations to the development database:

```bash
uv run alembic upgrade head
```

Later, `docker start repair-shop-db` / `docker stop repair-shop-db` start and
stop the database. Data lives in the `repair-shop-pgdata` volume.

> This manual setup will be replaced by Docker Compose in a later step.

## Run

```bash
uv run uvicorn app.main:app --reload
```

Interactive API docs: http://127.0.0.1:8000/docs

## Test

The database tests need the database container running (see above).

```bash
uv run pytest
```
