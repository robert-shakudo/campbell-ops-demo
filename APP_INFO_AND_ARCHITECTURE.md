# App Info & Architecture — Campbell & Company Ops Co-Pilot

## Overview

Live demo system showing how Kaji autonomously monitors Campbell & Company's trading infrastructure, diagnoses failures, applies fixes, and creates tickets — all without human intervention.

---

## Shakudo Deployment

| Field | Value |
|---|---|
| **Microservice Name** | `campbell-ops-demo` |
| **External URL** | https://campbell-ops-demo.dev.hyperplane.dev |
| **Port** | `8787` |
| **Environment** | `basic-ai-tools-large` (4 CPU, 8Gi RAM) |
| **Run Script** | `run.sh` |
| **Git Source** | `gitea-hello-world` → `shakudo/hello-world` |
| **Working Dir** | `/tmp/git/monorepo/campbell-ops-demo/` |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI 0.115 + Uvicorn |
| **Database** | Supabase (PostgreSQL) — `campbell_incidents`, `campbell_kaji_activity` |
| **Frontend** | Alpine.js + Tailwind CSS (CDN, no build) |
| **Real-time** | Server-Sent Events (SSE) |
| **Monitoring** | n8n v2 workflows |
| **Alerts** | Mattermost `#campbell-ops-alerts` |

---

## Architecture

```
Browser (Alpine.js + Tailwind)
    │
    ├── GET /          → index.html
    ├── GET /api/health → service health bar
    ├── GET /api/stream → SSE (real-time updates)
    ├── POST /api/logs/{svc}/inject → trigger demo scenario
    ├── POST /api/incidents/{id}/diagnose → run diagnosis
    ├── POST /api/incidents/{id}/apply-fix → apply + build
    └── POST /api/incidents/{id}/create-ticket → ClickUp

FastAPI Backend (main.py)
    ├── In-memory: service_failures, log_buffer, sse_subscribers
    ├── Supabase: campbell_incidents, campbell_kaji_activity
    ├── Mattermost: posts to #campbell-ops-alerts
    └── ClickUp: creates real tickets

n8n v2 Workflows
    ├── Log Watcher (every 5 min) → alerts Mattermost on new failures
    └── Daily Digest (9am UTC) → LLM summary to #campbell-ops-alerts
```

---

## Demo Scenarios

| # | Service | Error | Impact |
|---|---|---|---|
| 1 | Airflow | `KeyError: 'close_price'` | $50,000 |
| 2 | Bloomberg Compress | `ConnectionTimeout` | $75,000 |
| 3 | TeamCity | `AssertionError in risk_calculator_test.py:87` | $25,000 |
| 4 | Risk Calculator | `NullPointerException` | $100,000 |
| 5 | Price Feed | `DataQualityException: AAPL deviation 7.3%` | $60,000 |
| **Total** | | | **$310,000** |

---

## Brand

- **Primary**: `#0A1628` (dark navy)
- **Accent**: `#C9A84C` (gold)
- **Source**: campbellandc.com (fallback applied — site inaccessible at build time)

---

## Mattermost

- **Channel**: `#campbell-ops-alerts` (ID: `cw5wxp5wajrz5nkc1yeqyxbazc`)
- **Team**: `shakudo-internal`

---

## Supabase Schema

```sql
campbell_incidents (
  id UUID PRIMARY KEY,
  status TEXT,              -- open | diagnosed | fixing | resolved
  service TEXT,
  error TEXT,
  diagnosis TEXT,
  code_diff TEXT,
  clickup_url TEXT,
  savings_value INTEGER,
  mattermost_thread TEXT,   -- MM post ID for deep link
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
)

campbell_kaji_activity (
  id UUID PRIMARY KEY,
  timestamp TIMESTAMPTZ,
  tool TEXT,                -- read_logs | search_confluence | apply_code_fix | etc.
  params JSONB,
  summary TEXT
)
```

---

## n8n Workflows

- **Campbell Log Watcher**: polls `/api/logs/all/latest-errors` every 5 min, posts new failures to Mattermost
- **Campbell Daily Digest**: runs at 9am UTC, summarizes 24h activity via LiteLLM, posts to Mattermost

---

## Key Endpoints

```
GET  /api/health                    → all services status
GET  /api/logs/{service}            → log lines
GET  /api/logs/{service}/latest-error → latest error
POST /api/logs/{service}/inject     → inject failure (demo trigger)
GET  /api/confluence/search?q=      → KB search
GET  /api/confluence/page/{id}      → page content
GET  /api/incidents/history?q=      → historical incidents
GET  /api/git/file/{path}           → source file
POST /api/git/patch                 → apply diff
GET  /api/incidents                 → current incidents
POST /api/incidents/{id}/diagnose   → run diagnosis + KB lookup
POST /api/incidents/{id}/apply-fix  → trigger fix + build sim
POST /api/incidents/{id}/create-ticket → ClickUp ticket
GET  /api/stream                    → SSE real-time stream
POST /api/demo/reset                → clean slate for new demo run
```
