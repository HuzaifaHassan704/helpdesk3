# syntax=docker/dockerfile:1

# ---------- builder: resolve and install dependencies into a virtualenv ----------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------- runtime: only the venv + application code, non-root ----------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production

RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app scripts ./scripts

USER app
EXPOSE 8000

# Uses the stdlib so the slim image needs no curl. If ALLOWED_HOSTS is set it must include "localhost".
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health/live', timeout=3)" || exit 1

# Apply migrations separately (`alembic upgrade head`, see docker-compose `migrate` service) - not on every replica start.
# Worker count: set WEB_CONCURRENCY.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
