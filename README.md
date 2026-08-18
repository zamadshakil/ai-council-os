# AI Council OS

AI Council OS is a self-hosted, human-approved automation platform for three production councils: Grant, Sales, and Content. It combines a FastAPI backend, durable PostgreSQL jobs, a Next.js operator dashboard, Telegram controls, six supported workflows, a PostgreSQL-backed Grant knowledge base, and a separate Blender cloud-GPU manager.

The product is intentionally narrow. CAD generation, Strategy and Support councils, browser submission to EU portals, account creation, and automatic Reddit posting are outside this release. Blender management is isolated from the council system. It never executes model-generated Python: the pod agent exposes only a trusted validate/repair/benchmark operation.

## What ships

### Three councils

- **Grant Council** — drafts proposal sections, critiques them against evaluation criteria, and exports clean DOCX/PDF files for manual portal submission. Threshold: 88.
- **Sales Council** — scores lead intent and drafts tailored outreach. Threshold: 85.
- **Content Council** — creates platform-specific content variants. Threshold: 85.

Each council uses a structured generator/critic loop with no more than three generated drafts. A run that never clears its threshold is marked `needs_manual_review`; confidence is never invented.

### Six workflows

- Telegram control and kill switch
- YouTube comment replies
- Reddit lead prospector (manual posting only)
- YouTube description updater
- Multi-platform content engine for X, LinkedIn, Facebook, Instagram, Reddit, and Discord
- Instagram professional-account comment discovery and approval-gated replies

All external writes require approval. Every destination has an independent task and publication state. A workflow stays disabled until its current credentials pass verification.

### Operator dashboard

The dashboard provides Overview, Queue/Approvals, Councils, Workflows, Blender Manager, History/Analytics, Knowledge, and Integrations/Settings views. It uses server-side sessions, HTTP-only cookies, CSRF protection, optimistic versions, and database-backed state. It does not fabricate connection status, costs, confidence, schedules, pod state, or account names.

Blender Manager reads live RunPod state, can explicitly start/stop a selected pod, and queues durable template jobs. A job preserves the source `.blend`, enables Cycles GPU devices and persistent data, applies bounded benchmark settings, checks missing external assets, saves a new copy, renders one proof frame, records the detected GPU backend, and can stop billing automatically. If GPU use cannot be proven, the job fails rather than reporting success.

### Durable production core

- PostgreSQL is authoritative in production; SQLite is local-development only.
- Alembic owns schema migrations.
- A separate worker claims leased jobs with retries and dead-letter states.
- Atomic external-item deduplication and publication idempotency prevent duplicate actions.
- The kill switch and workflow pause are checked before generation and again before every external write.
- Audit and outbox events are durable PostgreSQL records.

## Approved model routing

OpenRouter is the only model gateway. Readiness verifies the configured IDs against OpenRouter; there is no silent provider or emergency-model substitution.

- Grant generator: `anthropic/claude-sonnet-5`
- Grant critic: `google/gemini-3.6-flash`
- Sales generator: `openai/gpt-5.6-terra`
- Sales critic: `anthropic/claude-sonnet-5`
- Content generator: `google/gemini-3.6-flash`
- Content critic: `openai/gpt-5.6-luna`

## Local development

Requirements:

- Python 3.11+
- Node.js 20+
- A newly issued OpenRouter key for live model calls

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn src.api.server:app --reload
```

In another terminal:

```sh
cd dashboard
npm ci
npm run dev
```

Do not put exposed or previously pasted credentials in `.env`.

## Production deployment

Production runs with Docker Compose:

- Caddy is the only public service on ports 80/443.
- Next.js and FastAPI remain private behind Caddy.
- PostgreSQL, worker, and backup services remain on the internal network.
- `https://<server-ip>.sslip.io` provides the initial hostname and automatic TLS.
- Backend and dashboard images use immutable release tags for rollback.

Follow [DEPLOYMENT.md](./DEPLOYMENT.md). Deployment is blocked until every exposed credential has been revoked and replaced.

## Main API surface

- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/session`
- `POST /api/council-runs`, `GET /api/council-runs`, `GET /api/council-runs/{id}`
- `POST /api/approvals/{id}/actions`
- `GET/PATCH /api/workflows/{id}`, `POST /api/workflows/{id}/trigger`
- `GET/PUT /api/kill-switch`
- `GET /api/integrations/health`
- `GET /api/integrations/catalog`
- `PUT/DELETE /api/integrations/{provider}/credentials`
- `POST /api/integrations/connections/{provider}/verify`
- `PATCH /api/workflows/{id}/integrations`
- `PATCH /api/councils/{id}/integrations`
- `POST /api/knowledge/upload`, `GET /api/knowledge/search`
- `GET /api/blender/pods`, `POST /api/blender/pods/{id}/actions`
- `GET/POST /api/blender/jobs`, `GET /api/blender/jobs/{id}`
- `GET /api/grants/{id}/export.docx`, `GET /api/grants/{id}/export.pdf`

Mutation responses include the persisted resource, its current version, and an audit-event ID. Failures include stable machine-readable error codes.

## Verification

```sh
python -m compileall -q src
python -m pytest -q
cd dashboard
npm run lint
npm run build
npm audit --omit=dev --audit-level=high
```

Production acceptance additionally requires PostgreSQL migration tests, controlled live-integration smoke tests, HTTPS verification, a backup restore test, visual inspection of Grant DOCX/PDF output, and a pre-release VPS snapshot.

## Security boundary

- Never commit `.env`, OAuth files, database dumps, or generated credential material.
- Portal-managed integration secrets are write-only to the browser and encrypted at rest with a separately supplied server key.
- Reddit and EU portal submissions always remain manual.
- Service accounts, API usage costs, hosting charges, and third-party account creation remain the client’s responsibility.
