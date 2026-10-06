# Phase 3 — Production-Grade Engineering

This document covers the 10 features added in Phase 3, on top of the
Phase 1 (multi-user web app) and Phase 2 (advanced AI/RAG platform)
functionality, which are unchanged and documented in the main `README.md`.

## 1. Architecture

```
                 ┌─────────────┐        ┌──────────────┐
Browser ───────▶ │  Next.js    │──────▶ │   FastAPI    │
                 │  frontend   │  HTTP  │   backend    │
                 └─────────────┘        └──────┬───────┘
                                                │
                    ┌───────────────────────────┼───────────────────────┐
                    │                            │                       │
                    ▼                            ▼                       ▼
             ┌─────────────┐             ┌──────────────┐        ┌─────────────┐
             │ PostgreSQL  │             │    Redis     │        │  Gemini API │
             │ (all state) │             │ (rate limit, │        │ (chat +     │
             └─────────────┘             │  Celery      │        │  embeddings)│
                                          │  broker/     │        └─────────────┘
                                          │  backend)    │
                                          └──────┬───────┘
                                                 │
                                    ┌────────────┴────────────┐
                                    ▼                          ▼
                             ┌─────────────┐           ┌──────────────┐
                             │ Celery      │           │ Celery beat  │
                             │ worker      │           │ (scheduler)  │
                             │ (notif.     │           └──────────────┘
                             │  email,     │
                             │  analytics  │
                             │  aggregation,│
                             │  maintenance)│
                             └─────────────┘
```

Redis is one piece of infrastructure serving two Phase 3 needs (rate
limiting counters, Celery broker/result backend) rather than two separate
systems. Phase 2's own async work (KB indexing, evaluation runs) keeps its
existing execution model deliberately -- see `app/workers/celery_app.py`'s
docstring for why moving already-working code onto Celery would have been
exactly the kind of needless replacement Phase 3's brief said not to do.

## 2. Roles & RBAC (Feature 19)

Four roles: `customer`, `support_agent`, `admin`, `super_admin` (`roles` /
`user_roles` tables, from Phase 1). Phase 3 adds a **fine-grained
permission layer** on top (`permissions` / `role_permissions`), additive
to -- not a replacement for -- the existing `require_roles` checks used
throughout Phase 1/2 routes.

See `app/auth/permissions.py` for the full permission list and each role's
default grant set. Two permissions are worth calling out specifically:

- `system.read` -- admin can view operational dashboards (health, metrics,
  error log) read-only.
- `system.manage` -- **super_admin only**. Required to grant the `admin`
  or `super_admin` role to anyone. This is the privilege-escalation guard:
  an admin can promote a customer to `support_agent`, but cannot mint
  another admin, and cannot change their own roles at all (self-escalation
  is blocked unconditionally in `app/api/admin_routes.py::update_user_role`).

Every sensitive endpoint checks authorization server-side
(`require_roles` / `require_permission` FastAPI dependencies) --
never only via frontend nav-hiding. Ownership-scoped resources (orders,
tickets, conversations, notifications) filter by the *authenticated*
user's ID at the query level; no route trusts a client-supplied `user_id`.

## 3. Rate limiting (Feature 20)

Redis-backed fixed-window counters (`app/security/rate_limit.py`), one
independent bucket per endpoint category, each with its own configurable
`(count, window_seconds)` pair in `app/config.py` / `.env.example`:

| Bucket | Default | Keyed by |
|---|---|---|
| `login` | 10 / 60s | IP |
| `signup` | 5 / 3600s | IP |
| `ai_chat` | 30 / 60s | user |
| `ticket_create` | 10 / 3600s | user |
| `feedback` | 30 / 3600s | user |
| `kb_upload` | 20 / 3600s | user (admin) |
| `analytics` | 60 / 60s | user |

A 429 always includes `Retry-After`, `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, `X-RateLimit-Reset` headers and a JSON body
`{"error": "rate_limit_exceeded", "message": ..., "retry_after": ...}`.

**Fails open**: if Redis is unreachable, requests are allowed through
(logged as a warning) rather than taking the whole API down over a
rate-limiter outage -- a deliberate availability choice, not an oversight.
Master switch: `RATE_LIMIT_ENABLED` (the test suite disables it globally
by default and re-enables it per-test where it's actually being tested, so
unrelated tests never trip a limit).

Client IP resolution (`app/security/net.py`) only trusts
`X-Forwarded-For` when the immediate peer is a private/loopback address
(i.e. a proxy this deployment itself put in front of uvicorn) -- never a
bare client-supplied header.

## 4. Audit logs (Feature 21)

Extends the *existing* `audit_events` table (added in Phase 1 for
login/signup) with the fields a real audit viewer needs: `actor_role`,
`resource_type`/`resource_id`, `ip_address`, `user_agent`, `success`,
`request_id`. One helper, `app/services/audit_service.log_event()`, is the
single write path, so every event is redacted (see PII below) consistently.

`GET /admin/audit-logs` (permission: `audit_logs.read`) supports filtering
by actor email, event type, resource type, success/failure, and date
range, with pagination. Normal users get a 403; nothing here is reachable
without the permission.

## 5. PII protection (Feature 22)

`app/security/pii.py` provides:
- `redact_pii(value)` -- recursively masks emails/phones and fully
  redacts any dict key that looks like a secret (`password`, `token`,
  `api_key`, ...), used before anything is written to the audit log, the
  error-tracking table, or AI traces.
- `mask_email` / `mask_phone` -- used directly where only one field needs
  masking (e.g. the console email provider logs a masked recipient).

Applied at: audit logs, error events, and the console notification
provider's logging. The Phase 2 AI trace viewer's own existing
citation/metadata shape was already minimal (no raw customer PII was ever
stored in a trace -- see `app/logging_utils.py`); Phase 3 didn't need to
change what's captured there, only ensure nothing *new* leaks PII, which
the redaction utility now guarantees for its own callers.

## 6. Notifications (Feature 23)

`notifications` table + `app/notifications/service.py`. In-app rows are
written synchronously (so the bell/unread-count reflects them
immediately); email delivery is enqueued to Celery
(`app/workers/tasks/notification_tasks.py`) so a slow SMTP call never
blocks the request that triggered it.

Wired to real events: ticket created, ticket assigned, ticket status
changed (including `ticket_resolved`), and AI handoff requested. Delivery
provider is swappable via `EMAIL_PROVIDER` (`console` by default -- zero
config, logs a masked recipient; `smtp` for real delivery).

API: `GET /notifications`, `GET /notifications/unread-count`,
`POST /notifications/{id}/read`, `POST /notifications/read-all` -- all
owner-scoped like every other Phase 1/2 resource.

## 7. Background workers (Feature 24)

Celery + Redis (`app/workers/celery_app.py`). Three task modules:
- `notification_tasks.py` -- email delivery, retried up to 3x.
- `maintenance_tasks.py` -- hourly cleanup of expired auth
  sessions/password-reset tokens (via Celery beat).
- `analytics_tasks.py` -- daily analytics pre-aggregation (the live
  `/analytics` endpoint still computes synchronously from Phase 2; this is
  the seam for a future pre-aggregated read path).

**Idempotency**: every task goes through `app/workers/tasks/job_tracking.py`,
which records a `background_jobs` row keyed by a `dedupe_key`. A retried or
duplicate submission of the same logical job (e.g. the same notification
email) is detected and skipped rather than redone.
`task_always_eager=True` is set automatically under pytest, so the test
suite exercises real task bodies synchronously without needing a live
broker connection.

## 8. Monitoring (Feature 25)

- `GET /health`, `/health/live` (never touches a dependency),
  `/health/ready` (checks Postgres -- hard dependency -- and Redis/Celery
  workers, which degrade gracefully rather than failing readiness).
- `GET /admin/system/health` -- the same readiness detail, admin-only.
- `GET /admin/system/metrics` (`app/monitoring/metrics.py`) -- in-process
  counters (HTTP requests/status codes/latency, AI request count/latency,
  rate-limit events, auth failures, worker task counts, notification
  failures), recorded from real request/event handling in
  `app/server.py`'s middleware -- **nothing here is a hardcoded number**.

Known limitation: these are single-process in-memory counters, correct
for this deployment's single backend container. A multi-replica
deployment would need to either push these to Redis so they aggregate
across processes, or swap in `prometheus_client` with its multiprocess
registry -- noted here rather than silently pretending single-process
counters are already cluster-wide.

## 9. Error tracking (Feature 26)

Every unhandled exception is recorded in the `error_events` table
(`app/monitoring/error_tracking.py::capture_exception`) -- always, so the
admin error viewer (`GET /admin/errors`) never depends on an external
service being configured. If `ERROR_TRACKING_ENABLED=true` and
`SENTRY_DSN` is set (and `sentry-sdk` is installed), the same exception is
also mirrored to Sentry; if the package isn't installed or the DSN is
empty, that part silently no-ops -- the app keeps working either way.
Error messages and metadata are redacted (`redact_pii`) before storage.
Customers only ever see `{"detail": "Internal server error.",
"request_id": "..."}` -- never a stack trace or internal path.

## 10. Docker (Feature 27)

`docker-compose.yml` services: `postgres`, `redis`, `backend`, `worker`
(Celery worker), `scheduler` (Celery beat), `frontend`. One backend image
(`Dockerfile`) is reused for all three Python roles (API, worker,
scheduler) via `command:` overrides. The image runs as a non-root user,
has a healthcheck hitting `/health/live`, and never runs a dev server.
Postgres and Redis both use named volumes for persistence.

```bash
cp .env.example .env   # fill in GEMINI_API_KEY, or leave USE_MOCK_LLM=1
docker compose up --build
docker compose exec backend python scripts/seed_db.py
```

## 11. CI/CD (Feature 28)

`.github/workflows/ci.yml`: on every PR/push --
1. **backend** job: real Postgres + Redis service containers, migrations,
   the full `tests/` (AI/RAG core) and `tests_web/` (API) suites, plus a
   mock-mode evaluation harness smoke check. `USE_MOCK_LLM=1` -- no API
   key/network needed.
2. **frontend** job: `npm ci`, `eslint`, `tsc --noEmit`, `next build`.
3. **security** job: secret scanning (gitleaks, blocking) +
   dependency-vulnerability scanning (`pip-audit`, `npm audit` --
   advisory/non-blocking, since transitive-dependency noise shouldn't
   block every PR the way a real committed secret should).
4. **docker-build** job: builds both images and validates
   `docker compose config`.

`.github/workflows/cd.yml`: builds and pushes both images to GHCR on every
push to `main`. The `deploy` job is a real, reusable workflow gated behind
a GitHub Environment (manual approval) that checks for a
`DEPLOY_TARGET_CONFIGURED` secret and **stops with an explanatory message
if it isn't set** -- images are still built and pushed, but nothing
deploys to an unconfigured/unknown target. See Deployment below for what
setting it up would require.

## 12. Environment variables

See `.env.example` for the full list with defaults. Every Phase 3
behavior is configurable: `RATE_LIMIT_ENABLED`, `PII_REDACTION_ENABLED`,
`NOTIFICATIONS_ENABLED`, `WORKERS_ENABLED`, `MONITORING_ENABLED`,
`ERROR_TRACKING_ENABLED`, plus per-bucket rate limits and email/Sentry
provider settings. Nothing sensitive has a real value committed anywhere.

## 13. Testing

```bash
# AI/RAG core (unchanged from Phase 0/1/2)
USE_MOCK_LLM=1 python -m pytest tests/ -v

# Full web API, including Phase 3 (RBAC, rate limiting, audit, PII,
# notifications, workers, monitoring, error tracking)
python -m pytest tests_web/ -v
```

New Phase 3 test files: `test_rbac_and_audit.py` (13 tests -- permission
gating, privilege-escalation prevention, audit content/access),
`test_rate_limiting.py` (6 tests -- 429s, per-bucket independence,
per-user vs per-IP, fail-open), `test_notifications_monitoring_workers.py`
(17 tests -- notification creation/unread/read/duplicate-prevention, job
idempotency/retry/failure, health/readiness, metrics are real numbers,
error capture + redaction, admin-only access to all of the above).

## 14. Deployment

No deployment target is configured in this repository. To enable the `cd.yml`
`deploy` job:
1. Choose a target (a VM via SSH, a managed container platform, etc.).
2. Add the secrets `cd.yml` checks for (`DEPLOY_TARGET_CONFIGURED=true`,
   plus whatever the chosen target needs -- e.g. an SSH key, or a cloud
   provider's deploy credentials).
3. Replace the three `echo "Placeholder: ..."` steps in the `deploy` job
   with the real migration/rollout/smoke-test commands for that target.

### Rollback

- **Identifying a failed deployment**: the CD workflow's smoke-test step
  (once implemented) should curl the deployed `/health/ready` and fail the
  job on a non-200; GitHub Actions then shows the run as failed.
- **Reverting the application**: redeploy the previous image tag
  (`ghcr.io/<repo>/backend:<previous-sha>` -- every image is tagged with
  its commit SHA, not just `latest`) to the same target.
- **Migration failures**: Alembic migrations in this codebase are written
  additively (see every migration under `migrations/versions/` -- new
  tables/columns, `server_default` provided for any new NOT NULL column
  on an existing table) specifically so a failed *application* deploy can
  roll back to the previous image while the schema stays forward-compatible.
  A migration that fails outright should be fixed and re-applied, not
  worked around by hand-editing the production schema (never do this --
  see the Phase 3 brief's explicit warning against it).
- **Restoring the previous image**: since CD tags every build with its
  commit SHA, "restore the previous image" is just re-running the deploy
  step with the prior SHA's tag -- no image is ever overwritten.

## 15. Security considerations

- Authentication: bcrypt password hashing, JWT access tokens (short TTL),
  revocable refresh-token sessions (hashed at rest), password-reset tokens
  hashed and time-limited.
- Authorization: RBAC + fine-grained permissions, enforced server-side on
  every sensitive route; ownership-scoped queries (never fetch-then-check)
  for orders/tickets/conversations/notifications; privilege-escalation
  guards on role management.
- Rate limiting: brute-force/abuse protection on auth, AI chat, ticket
  creation, feedback, KB upload, analytics -- fails open, never fails
  closed and takes down the API.
- PII: redaction utility applied to audit logs and error events; secrets
  are never logged (`_SECRET_KEY_MARKERS` in `app/security/pii.py`).
- Secrets: `.env` is gitignored; `.env.example` has no real values;
  `AUTH_SECRET`/`SENTRY_DSN`/SMTP credentials are all environment-only.
  CI's secret-scanning job (gitleaks) blocks a real committed credential.
- SQL injection: all queries go through SQLAlchemy's ORM/parameterized
  query builder -- no raw string-interpolated SQL anywhere in the codebase.
- Error responses: customers never see a stack trace, internal path, or
  raw exception message -- only a generic message + correlation
  `request_id`, which an admin can then look up in `/admin/errors`.
