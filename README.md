# Aster Support AI

Aster Support AI is a full-stack AI customer-support platform for the fictional **Aster & Row** ecommerce brand.

It combines customer-facing AI chat, Google Gemini, retrieval-augmented generation (RAG), a versioned Knowledge Base, customer/order/ticket context, human support workflows, AI evaluation, safety and quality controls, analytics, model routing, background processing, and role-based administration.

> **Project status:** Local/demo/portfolio application. Production deployment requires deployment-specific security, infrastructure, monitoring, backups, provider configuration, and operational controls.

---

## Table of Contents

- [Features](#features)
- [Technology Stack](#technology-stack)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Environment Configuration](#environment-configuration)
- [Docker Quick Start](#docker-quick-start)
- [Application URLs](#application-urls)
- [Authentication](#authentication)
- [Database and Migrations](#database-and-migrations)
- [Knowledge Base and RAG](#knowledge-base-and-rag)
- [AI Behavior](#ai-behavior)
- [Support and Admin Workflows](#support-and-admin-workflows)
- [Background Jobs](#background-jobs)
- [Testing](#testing)
- [Frontend Development](#frontend-development)
- [Backend Development](#backend-development)
- [Docker Commands](#docker-commands)
- [Troubleshooting](#troubleshooting)
- [Data Safety](#data-safety)
- [GitHub Safety](#github-safety)
- [Manual Acceptance Checklist](#manual-acceptance-checklist)
- [Production Considerations](#production-considerations)
- [Project Identity](#project-identity)
- [License](#license)

---

# Features

## Customer

- Login and authentication
- Optional self-signup controlled by configuration
- Persistent AI conversations
- Conversation rename, archive, and delete
- Explicit conversation-delete confirmation
- Edit/retry conversation turns
- Share Conversation
- Order lookup
- Ticket creation and ticket history
- Profile and settings
- AI Assistant
- Source Explorer
- Global Search
- Advanced AI features

## Support

- Support Workspace
- Customer and conversation context
- AI-suggested replies
- Human approval before sending AI drafts
- Sentiment and intent information
- AI quality information
- Related orders and tickets
- Internal notes
- Ticket assignment
- Ticket escalation
- Ticket resolution
- Global Search
- Action Center

## Admin

- User Management
- Analytics
- Knowledge Base management
- Knowledge Base versioning
- AI Traces
- Evaluations
- AI Evaluation Playground
- Prompt Management
- AI Usage & Routing
- AI Intelligence
- AI Safety
- Action Center
- Support Workspace
- Customer 360
- Global Search
- Admin ticket Apply/Save workflow

---

# Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python |
| Database | PostgreSQL 16 |
| Cache / Broker | Redis 7 |
| Background Jobs | Celery + Celery Beat |
| AI | Google Gemini |
| Embeddings | Gemini embedding model |
| Authentication | JWT access tokens + server-side refresh sessions |
| Password Storage | Hashed passwords |
| Migrations | Alembic |
| Containers | Docker Compose |
| Backend Tests | Pytest |
| Frontend Checks | ESLint + Next.js production build |
| CI/CD | GitHub Actions |

---

# Architecture

```text
                         ┌─────────────────────────┐
                         │         Browser         │
                         │   Next.js / React UI    │
                         │       :3000             │
                         └────────────┬────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │      FastAPI Backend    │
                         │          :8000          │
                         └──────────┬───────┬──────┘
                                    │       │
                       ┌────────────┘       └─────────────┐
                       ▼                                  ▼
             ┌──────────────────┐               ┌──────────────────┐
             │   PostgreSQL 16  │               │     Redis 7      │
             │      :5432       │               │      :6379       │
             └──────────────────┘               └────────┬─────────┘
                                                         │
                                            ┌────────────┴────────────┐
                                            ▼                         ▼
                                   ┌────────────────┐        ┌────────────────┐
                                   │ Celery Worker  │        │ Celery Beat    │
                                   └────────────────┘        └────────────────┘
```

Inside Docker, services communicate by Compose service name:

```text
Backend → postgres:5432
Backend → redis:6379
```

From the browser, the published application endpoints are:

```text
Browser → http://localhost:3000
Browser → http://localhost:8000
```

**Do not use `localhost` as the PostgreSQL or Redis hostname from inside the backend container.**

---

# Repository Structure

```text
aster-support-ai/
├── app/
│   ├── api/
│   ├── auth/
│   ├── db/
│   ├── enterprise/
│   ├── notifications/
│   ├── phase4/
│   ├── services/
│   ├── workers/
│   ├── agent.py
│   ├── config.py
│   └── server.py
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── lib/
│   │   └── types/
│   └── package.json
│
├── alembic/
├── knowledge-base/
├── scripts/
├── tests/
├── tests_web/
├── data/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

Runtime secrets, local environment files, database volumes, Redis data, logs, and conversation data should not be committed to Git.

---

# Prerequisites

Install:

- Docker Desktop
- Git

Recommended for development outside Docker:

- Node.js 20+
- Python 3.11+

Verify Docker:

```cmd
docker --version
docker compose version
```

Verify Git:

```cmd
git --version
```

---

# Environment Configuration

The repository should contain:

```text
.env.example
```

Create a local environment file from the example.

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### Linux/macOS

```bash
cp .env.example .env
```

Set the required local credentials, including the Gemini API key when real Gemini calls are enabled:

```env
GEMINI_API_KEY=<your-real-key>
```

Typical Docker-local service configuration:

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/aster_row
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Example AI configuration:

```env
CHAT_MODEL=gemini-2.5-flash
CHAT_FALLBACK_MODEL=gemini-3.5-flash-lite
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=768
USE_MOCK_LLM=0
```

Model availability can change. Confirm that the configured models are available to the Google account/API being used.

## Never commit secrets

Never commit:

- `.env`
- Gemini API keys
- database production passwords
- JWT/authentication secrets
- SMTP credentials
- webhook encryption keys
- private keys
- provider API keys

If a real secret was ever committed or exposed, **revoke/rotate it**. Removing it from the working tree alone does not remove it from Git history.

---

# Docker Quick Start

## 1. Start the complete stack

From the repository root:

```cmd
docker compose up --build
```

For detached/background mode:

```cmd
docker compose up -d --build
```

## 2. Check service status

```cmd
docker compose ps
```

## 3. View logs

All services:

```cmd
docker compose logs -f
```

Backend:

```cmd
docker compose logs -f backend
```

Frontend:

```cmd
docker compose logs -f frontend
```

Worker:

```cmd
docker compose logs -f worker
```

Scheduler:

```cmd
docker compose logs -f scheduler
```

## 4. Start normally after the first successful build

```cmd
docker compose up -d
```

---

# Application URLs

When the stack is running:

| Service | URL |
|---|---|
| Frontend | `http://localhost:3000` |
| Backend | `http://localhost:8000` |
| Backend health | `http://localhost:8000/healthz` |
| Backend live health | `http://localhost:8000/health/live` |

Common frontend routes include:

```text
/login
/signup
/chat
/orders
/tickets
/support-workspace
/action-center
/analytics
/users
/kb
/ai-traces
/evaluations
/ai-evaluation-playground
/prompt-management
/ai-usage
/customer-360/<id>
/search
/profile
/settings
/source-explorer
```

Exact availability depends on authentication, role, and configuration.

---

# Authentication

Authentication uses:

1. Access JWTs.
2. Server-side refresh sessions.
3. Hashed refresh tokens.
4. Refresh-token rotation.
5. Browser-side persistence of authentication tokens.
6. Access-token refresh after an unauthorized/expired request.
7. Periodic/focus refresh while the application is open.

Frontend token keys:

```text
ar_access_token
ar_refresh_token
```

Relevant backend endpoints include:

```text
POST /auth/login
POST /auth/refresh
POST /auth/logout
```

Logout flow:

```text
User selects Log out
        ↓
Frontend calls /auth/logout
        ↓
Backend revokes the refresh session
        ↓
Frontend clears local tokens
        ↓
Frontend redirects to /login
```

Example local/demo session settings:

```env
ACCESS_TOKEN_TTL_MINUTES=1440
REFRESH_TOKEN_TTL_DAYS=365
```

These are **not recommended production security defaults**.

---

# Local Demo Accounts

For the controlled local/demo environment, the canonical accounts are:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@example.com` | `Admin123!` |
| Support Agent | `support@example.com` | `Support123!` |
| Customer | `customer@example.com` | `Customer123!` |

**These credentials are for local development/demo use only. Never use them in production.**

The project initialization/reset tooling is designed to create the canonical roles, permissions, and demo accounts without requiring a destructive database wipe.

If the project contains the clean-demo reset script, run it only when you intentionally want to reset application/demo data:

```cmd
docker compose exec backend python scripts/reset_clean_demo_data.py
```

Or, if the maintenance Compose profile is configured:

```cmd
docker compose --profile maintenance run --rm clean-reset
```

**Do not run a clean reset against a database containing data you need to preserve.**

---

# Database and Migrations

PostgreSQL is the primary application database.

The backend uses Alembic migrations.

The startup process should:

1. Wait for PostgreSQL to become reachable.
2. Apply pending migrations.
3. Initialize required local/demo authentication data when configured.
4. Start the API.

Inspect migration state:

```cmd
docker compose exec backend alembic current
```

View migration history:

```cmd
docker compose exec backend alembic history
```

Apply migrations manually when necessary:

```cmd
docker compose exec backend alembic upgrade head
```

Do **not** delete database volumes to solve ordinary migration errors.

---

# Knowledge Base and RAG

The Knowledge Base is stored under:

```text
knowledge-base/
```

Example source documents include:

```text
01-returns-policy-current.md
02-returns-policy-legacy.md
03-final-sale-and-promotions.md
04-damaged-or-wrong-items.md
05-domestic-shipping.md
06-international-shipping.md
07-warranty.md
08-order-changes-and-cancellations.md
09-trailplus-membership.md
10-gift-cards-and-price-adjustments.md
11-product-care.md
12-breeze-tumbler-product-card.md
13-support-escalation.md
14-internal-content-migration-notes.md
15-missing-or-delayed-packages.md
```

The application can use:

- Customer/order/ticket context
- Knowledge Base retrieval
- Hybrid retrieval
- Verified RAG citations
- Google Gemini
- AI quality and safety checks

Example retrieval configuration:

```env
RETRIEVAL_TOP_K=5
RETRIEVAL_MIN_SIMILARITY=0.45
RETRIEVAL_SEMANTIC_WEIGHT=0.65
RETRIEVAL_KEYWORD_WEIGHT=0.35
RETRIEVAL_KEYWORD_SATURATION_K=2.5
RETRIEVAL_HYBRID_MIN_SCORE=0.22
RAG_CITATIONS_ENABLED=true
MAX_HISTORY_TURNS=6
```

The Knowledge Base is source code/content and may be committed to Git when it contains only information intended for the repository.

Conversation history is runtime database data and should not be committed.

---

# AI Behavior

Aster Support AI supports two broad answer paths.

## Aster & Row support questions

Questions about:

- policies
- products
- orders
- returns
- shipping
- warranties
- tickets
- authorized customer information

can use the application's context and RAG pipeline.

## General knowledge

Questions such as:

```text
What is photosynthesis?
Explain gravity.
What is Python?
How does the internet work?
```

can use the general Gemini path without requiring an Aster & Row Knowledge Base match.

The general Gemini path does **not** guarantee live/current information.

Current news, live sports, current weather, real-time prices, and other time-sensitive information require an appropriate live search/data integration.

---

# Source Explorer

Source Explorer displays verified retrieved passages associated with a conversation.

Route:

```text
/source-explorer
```

With a conversation:

```text
/source-explorer?c=<conversation-id>
```

A valid RAG-backed conversation can display:

- document
- heading
- document version
- update date
- relevance score
- verified retrieved passage

The application should not invent citations.

For a general Gemini response with no RAG citation, an empty state such as:

```text
No verified source found.
```

is expected.

---

# Conversation Management

Users can:

- create conversations
- open conversations
- rename conversations
- archive conversations
- delete conversations
- edit previous questions
- retry failed responses
- share conversation URLs

Deleting a conversation requires explicit confirmation:

```text
Do you want to delete this conversation?

This will permanently delete the selected conversation history.

[ No ] [ Yes, Delete ]
```

The Knowledge Base is separate from conversation history.

---

# Share Conversation

The Share action uses the browser Web Share API where supported and falls back to copying the conversation URL.

Typical URL:

```text
http://localhost:3000/chat?c=<conversation-id>
```

Sharing the URL does **not** make a private conversation publicly accessible.

The recipient still needs the appropriate authenticated access.

---

# Support and Admin Workflows

## Support Workspace

Support users can work with:

- customer context
- conversation context
- AI-suggested replies
- human approval/editing
- sentiment
- intent
- related orders
- related tickets
- internal notes
- assignment
- escalation
- resolution

## Admin Apply/Save

Authorized admin users can use an explicit Apply/Save workflow for supported ticket changes.

After saving, the application should persist the change and display the saved value after refresh.

## Action Center

AI actions can be configured with human approval:

```env
AI_AGENT_ACTIONS_ENABLED=true
AI_ACTION_APPROVAL_REQUIRED=true
```

Mutating actions should not execute without the required approval.

---

# Model Routing and AI Quality

Model routing can be enabled with:

```env
MODEL_ROUTER_ENABLED=true
```

Example routing categories include:

```text
simple_question
complex_question
classification
summarization
retrieval
tool_call
```

AI quality/safety configuration can include:

```env
QUALITY_GROUNDING_ALLOW=0.75
QUALITY_GROUNDING_HIGH=0.85
QUALITY_GROUNDING_MEDIUM=0.65
QUALITY_RETRY_TOP_K_MULTIPLIER=2
QUALITY_CLARIFY_MAX_WORDS=4
PII_REDACTION_ENABLED=true
```

Retry/failover configuration can include:

```env
LLM_MAX_ATTEMPTS_PER_MODEL=2
LLM_RETRY_INITIAL_DELAY_SECONDS=0.5
LLM_RETRY_MAX_DELAY_SECONDS=2.0
LLM_FAILOVER_HUMAN_HANDOFF=1
```

Retries should be limited to appropriate transient failures. Invalid configuration, authentication failures, unsupported models, and programming errors should not be blindly retried.

---

# Background Jobs

Redis is used for caching/rate limiting and Celery messaging.

Example configuration:

```env
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

The application includes:

- Celery worker
- Celery Beat scheduler

Check status:

```cmd
docker compose ps worker scheduler
```

View worker logs:

```cmd
docker compose logs -f worker
```

View scheduler logs:

```cmd
docker compose logs -f scheduler
```

---

# Rate Limiting

Example configuration:

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_LOGIN_COUNT=10
RATE_LIMIT_LOGIN_WINDOW_SECONDS=60
RATE_LIMIT_AI_CHAT_COUNT=30
RATE_LIMIT_AI_CHAT_WINDOW_SECONDS=60
RATE_LIMIT_GENERAL_COUNT=120
RATE_LIMIT_GENERAL_WINDOW_SECONDS=60
```

Review and tune these values before production deployment.

---

# Notifications

Example local configuration:

```env
NOTIFICATIONS_ENABLED=true
EMAIL_PROVIDER=console
```

A real email provider requires deployment-specific credentials and configuration.

---

# Testing

Backend tests are under:

```text
tests/
```

Web/API tests are under:

```text
tests_web/
```

Run backend tests:

```cmd
USE_MOCK_LLM=1 python -m pytest tests/ -v
```

Run web/API tests:

```cmd
USE_MOCK_LLM=1 python -m pytest tests_web/ -v
```

Inside Docker:

```cmd
docker compose exec backend pytest tests/ -v
docker compose exec backend pytest tests_web/ -v
```

For deterministic tests where a real Gemini request is unnecessary, use:

```env
USE_MOCK_LLM=1
```

A passing automated test suite does not guarantee that every browser, provider, network, or production integration is error-free. Perform the manual acceptance checklist before deployment.

---

# Frontend Development

From the frontend directory:

```cmd
cd frontend
npm install
```

Development server:

```cmd
npm run dev
```

Production build:

```cmd
npm run build
```

Lint:

```cmd
npm run lint
```

The browser-facing API URL should normally be:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Do not commit local frontend environment files containing secrets.

---

# Backend Development

Create a virtual environment:

```cmd
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```cmd
pip install -r requirements.txt
```

Run migrations:

```cmd
alembic upgrade head
```

Run FastAPI:

```cmd
uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

For non-Docker development, PostgreSQL and Redis must be reachable using the configured environment URLs.

---

# Docker Commands

## Start

```cmd
docker compose up -d
```

## Start and rebuild

```cmd
docker compose up -d --build
```

## Stop safely

```cmd
docker compose down
```

This removes the Compose containers/network while preserving named volumes.

## Stop without removing containers

```cmd
docker compose stop
```

## Start stopped containers

```cmd
docker compose start
```

## Status

```cmd
docker compose ps
```

## Logs

```cmd
docker compose logs -f
```

## Restart one service

```cmd
docker compose restart backend
```

or:

```cmd
docker compose restart frontend
```

## Rebuild without cache

Only when necessary:

```cmd
docker compose build --no-cache
docker compose up -d
```

---

# Troubleshooting

## PostgreSQL hostname is not resolvable

If the backend repeatedly prints:

```text
PostgreSQL hostname is not resolvable yet; retrying...
```

check:

```cmd
docker compose ps
```

Then:

```cmd
docker compose logs postgres
```

and:

```cmd
docker compose logs backend
```

The backend must connect to:

```text
postgres:5432
```

inside Docker.

Do not change this to:

```text
localhost:5432
```

inside the backend container.

If the Compose stack was previously interrupted or contains stale project containers:

```cmd
docker compose down --remove-orphans
docker compose up -d --build
```

Do **not** use `-v` unless you intentionally want to remove database/Redis volumes.

---

## Port 3000 is already allocated

Error:

```text
Bind for 0.0.0.0:3000 failed: port is already allocated
```

Find the Docker container using port 3000:

```cmd
docker ps --filter "publish=3000"
```

If it is an old/stale project container, stop it:

```cmd
docker stop <OLD_CONTAINER_NAME>
```

Then start the current project:

```cmd
docker compose up -d
```

If Docker is not using the port, check Windows:

```powershell
netstat -ano | findstr :3000
```

Identify the process:

```powershell
tasklist /FI "PID eq <PID>"
```

Stop only a process you recognize as the application that should no longer own the port.

**Do not delete database volumes to solve a port problem.**

---

## Port 8000 is already allocated

Find the Docker container:

```cmd
docker ps --filter "publish=8000"
```

Stop the old/stale container:

```cmd
docker stop <OLD_CONTAINER_NAME>
```

Then:

```cmd
docker compose up -d
```

If Docker is not using the port:

```powershell
netstat -ano | findstr :8000
```

---

## Old Compose volume warning

A warning such as:

```text
volume "..." already exists but was created for project "..."
```

means Docker found a volume created by another Compose project.

Do not delete the volume automatically.

The correct solution is to use project-specific volume names or explicitly configure an intentionally shared volume as external.

Do not use:

```cmd
docker compose down -v
```

just to remove a warning.

---

## Login says "Invalid email or password"

First check:

```cmd
docker compose ps
```

Then:

```cmd
docker compose logs backend
```

If an authentication initialization service exists:

```cmd
docker compose logs auth-init
```

Verify the local demo account exists and try:

```text
Email: admin@example.com
Password: Admin123!
```

If authentication still fails, inspect backend/auth initialization logs.

Do **not** disable authentication or create a login bypass to solve a normal database/account initialization problem.

---

## Frontend cannot reach backend

Check:

```cmd
docker compose ps frontend backend
```

Then:

```cmd
docker compose logs frontend
docker compose logs backend
```

Verify the browser-facing API URL:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Remember:

```text
Browser → localhost:8000
Backend container → postgres:5432
Backend container → redis:6379
```

These are different network contexts.

---

## Container keeps restarting

Check:

```cmd
docker compose ps
```

Then inspect the failing service:

```cmd
docker compose logs --tail=200 <service>
```

For example:

```cmd
docker compose logs --tail=200 backend
```

Fix the first meaningful application error rather than repeatedly restarting the container.

---

# Data Safety

## Important: do not casually use `down -v`

This command:

```cmd
docker compose down -v
```

can remove persistent Compose-managed volumes.

Only use it when you intentionally want to delete the local database/Redis data and have confirmed that the data can be discarded.

## Normal shutdown

Use:

```cmd
docker compose down
```

This preserves named volumes.

## Runtime data

The following are runtime data and should not be committed to Git:

```text
PostgreSQL data
Redis data
Conversations
Messages
Citations
Runtime logs
Generated test output
Local .env files
```

---

# Runtime Test-Data Cleanup

If the repository contains:

```text
scripts/clear_test_dashboard_data.py
```

run a dry run first:

```cmd
docker compose exec backend python scripts/clear_test_dashboard_data.py
```

After reviewing the output:

```cmd
docker compose exec backend python scripts/clear_test_dashboard_data.py --yes
```

This is intended for targeted dashboard/test records and is narrower than a complete database reset.

---

# Conversation Cleanup

If the repository contains:

```text
scripts/clear_all_conversation_data.py
```

perform a dry run:

```cmd
docker compose exec backend python scripts/clear_all_conversation_data.py
```

Then, only after reviewing the result:

```cmd
docker compose exec backend python scripts/clear_all_conversation_data.py --yes
```

Deleting conversation data can make an old Source Explorer conversation URL invalid. It does not delete the Knowledge Base files.

---

# Full Clean Demo Reset

If the repository contains:

```text
scripts/reset_clean_demo_data.py
```

the command:

```cmd
docker compose exec backend python scripts/reset_clean_demo_data.py
```

is intended for a deliberately clean local/demo database.

Treat this as a **destructive data operation** for application/runtime data.

Do not run it against a database containing information that must be preserved.

---

# GitHub Safety

Before pushing:

```cmd
git status
git diff
git diff --cached
```

Confirm that:

- `.env` is not staged.
- No API key is staged.
- No private key/certificate is staged.
- No database volume is staged.
- No Redis data is staged.
- No runtime conversation export is staged.
- No generated logs are staged.
- `.env.example` contains placeholders, not real secrets.
- Knowledge Base files contain only information intended for the repository.

If a secret has ever been committed:

1. Revoke/rotate it.
2. Remove it from the working tree.
3. Remove it from Git history when necessary.
4. Run a secret scanner before publishing.

---

# CI/CD

GitHub Actions workflows are stored under:

```text
.github/workflows/
```

Typical workflows include:

```text
ci.yml
cd.yml
```

CI/CD should validate the project before deployment, including as applicable:

- Frontend lint/build
- Backend Python checks
- Backend tests
- Migration validation
- Security checks
- Docker image builds
- Workflow YAML syntax

Before pushing:

```cmd
git status
git add .
git commit -m "Update Aster Support AI"
git push origin main
```

Then inspect the repository's **Actions** tab on GitHub.

---

# Manual Acceptance Checklist

## Login

1. Open:

```text
http://localhost:3000/login
```

2. Log in with a valid local account.
3. Confirm the authenticated UI loads.
4. Refresh the browser.
5. Confirm the session remains valid while the refresh session is valid.
6. Log out.
7. Confirm redirect to `/login`.

## General Gemini

Test:

```text
What is photosynthesis?
Explain gravity.
What is Python?
How does the internet work?
```

These should use the general AI path rather than incorrectly requiring an Aster & Row Knowledge Base match.

## RAG

Test an Aster & Row question such as:

```text
What is your return policy?
```

or:

```text
How long does domestic shipping take?
```

Confirm the answer can use the Knowledge Base.

## Source Explorer

1. Create/open a conversation.
2. Ask an Aster & Row question expected to retrieve Knowledge Base content.
3. Open Source Explorer.
4. Confirm verified retrieved passages appear.
5. Confirm document/version/relevance information is displayed.
6. Open Source Explorer without a conversation.
7. Confirm the empty state is handled gracefully.
8. A general Gemini question may legitimately show:

```text
No verified source found.
```

## Conversation Delete

1. Open a conversation.
2. Select delete.
3. Confirm the Yes/No dialog.
4. Select **No** and confirm the conversation remains.
5. Select delete again.
6. Select **Yes, Delete**.
7. Confirm the conversation disappears.

## Global Search

1. Log in as customer.
2. Confirm Global Search is available.
3. Search for authorized records.
4. Log in as support/admin.
5. Confirm results respect authorization boundaries.

## Admin Ticket Apply/Save

1. Log in as admin.
2. Open Support Workspace.
3. Open a ticket.
4. Change a supported field.
5. Confirm the intended Apply/Save workflow.
6. Save.
7. Refresh.
8. Confirm the saved value persists.

## Share

1. Open a conversation.
2. Select Share.
3. Confirm Web Share or clipboard fallback.
4. Confirm the generated URL contains the conversation identifier.

## Docker

Confirm:

```cmd
docker compose ps
```

shows the required services running/healthy.

Confirm:

```text
http://localhost:3000
```

loads the frontend.

Confirm:

```text
http://localhost:8000/healthz
```

returns a healthy response.

---

# Production Considerations

This repository is a local/demo/portfolio application.

Before production deployment, review at minimum:

- Secret management
- Authentication/session TTLs
- Database credentials
- HTTPS/TLS
- CORS
- Secure cookie/token strategy
- CSRF considerations where applicable
- Rate limits
- Database backups
- Redis security
- Email provider configuration
- Webhook security
- Monitoring and alerting
- Log retention
- PII handling
- Authorization boundaries
- Tenant isolation
- AI provider quotas and pricing
- Current Gemini model availability
- Current Google API requirements
- Container image patching
- Dependency updates
- Public/private conversation policy
- Data retention/deletion policy

Do not use the documented demo credentials in production.

---

# Project Identity

**Project:** Aster Support AI

**Fictional company:** Aster & Row

**Classification:** Generative AI / Artificial Intelligence

**Core techniques:**

- Large Language Models
- Google Gemini
- Retrieval-Augmented Generation (RAG)
- Semantic retrieval / embeddings
- Hybrid retrieval
- AI evaluation
- AI safety and quality controls

**Supporting technologies:**

- FastAPI
- Next.js
- PostgreSQL
- Redis
- Celery
- Docker
- TypeScript
- Python

### Short project description

> Aster Support AI is a Generative AI and RAG-based intelligent customer-support platform built using Google Gemini, semantic retrieval, knowledge-base grounding, AI evaluation, analytics, and a full-stack web architecture.

---

# Final Local Run

From the repository root:

```cmd
docker compose up -d --build
docker compose ps
```

Open:

```text
http://localhost:3000
```

Check backend health:

```text
http://localhost:8000/healthz
```

For a clean GitHub repository, keep local `.env` files, database volumes, Redis data, runtime conversations, generated logs, and secrets out of source control while retaining the application code, migrations, tests, intended Knowledge Base documents, and documentation.

---

# License

Aster & Row is a fictional ecommerce/support brand used for this application and demonstration environment.

This repository is intended as a portfolio/take-home style full-stack AI support application. Review secrets, provider configuration, security controls, infrastructure, and deployment architecture before using it for real customer data or production traffic.
