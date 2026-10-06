# Production-oriented image: no dev server, no unnecessary packages, runs
# as a non-root user. The same image is used for the API (default CMD),
# the Celery worker, and the Celery beat scheduler (docker-compose.yml
# overrides `command:` for the latter two) -- one image, three roles,
# rather than three separate builds to keep in sync.
FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root: the app never needs root inside the container.
RUN useradd --create-home --uid 1000 asterrow \
    && mkdir -p /app/logs \
    && chown -R asterrow:asterrow /app
USER asterrow

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')" || exit 1

# Runs migrations before serving -- see docs/PHASE_3.md's rollback section
# for what to do if a migration fails during this step. uvicorn (not
# --reload) is a production ASGI server, not a dev server.
CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn app.server:app --host 0.0.0.0 --port 8000"]
