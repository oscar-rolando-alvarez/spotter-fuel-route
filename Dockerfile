# syntax=docker/dockerfile:1.7
# Multi-stage image: dependencies are resolved from uv.lock (reproducible), the price data is
# loaded at build time so the runtime image is immutable and starts in seconds.

ARG PYTHON_VERSION=3.14

# ---------------------------------------------------------------- deps: locked virtualenv
FROM python:${PYTHON_VERSION}-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# Third-party deps only, in their own layer: code changes don't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------- build: code + baked data
FROM deps AS build
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev \
 && /app/.venv/bin/python manage.py migrate --noinput \
 && /app/.venv/bin/python manage.py load_fuel_data \
 && /app/.venv/bin/python manage.py check --deploy --fail-level ERROR

# ---------------------------------------------------------------- loadtest: + locust (compose profile)
FROM build AS loadtest
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --group load
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app

# ---------------------------------------------------------------- runtime: small, non-root
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN useradd --system --uid 10001 --home /app app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_DEBUG=0 \
    DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/', timeout=2)"]
CMD ["gunicorn", "config.wsgi", "--config", "gunicorn.conf.py"]
