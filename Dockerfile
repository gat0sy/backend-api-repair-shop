FROM python:3.13-slim

# uv, pinned to the version used for development (from its official image).
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv

WORKDIR /app

# UV_COMPILE_BYTECODE: precompile .pyc files at build time (faster startup).
# UV_LINK_MODE=copy: avoid hard-link warnings across Docker layers.
# UV_PYTHON_DOWNLOADS=never: use this image's Python 3.13, never download one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first: this layer is reused until pyproject.toml or uv.lock
# change. --frozen installs exactly what uv.lock pins; --no-dev skips the
# test and code-quality tools.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Don't run the application as root.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
