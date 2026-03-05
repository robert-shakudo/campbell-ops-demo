# App Info & Architecture — Campbell & Company Ops Co-Pilot

## Overview

Live demo for Campbell & Company (quantitative trading firm) showing how Kaji monitors trading infrastructure, diagnoses failures, routes fixes for human approval, then applies them — all from Mattermost chat.

**Live**: https://campbell-ops-demo.dev.hyperplane.dev  
**GitHub**: https://github.com/robert-shakudo/campbell-ops-demo  
**ClickUp Demo Ticket**: https://app.clickup.com/t/86afywfd4

---

## Deployment

| Field | Value |
|---|---|
| **Microservice** | `campbell-ops-demo` |
| **Port** | `8787` |
| **Environment** | `basic-medium` |
| **Git** | `robert-shakudo/campbell-ops-demo` (GitHub) |
| **Working Dir** | `/tmp/git/monorepo/` |

---

## Full System Flow

```
┌───────────────────────────────────────────────────────────────────────────┐
│                    CAMPBELL OPS CO-PILOT — SYSTEM DESIGN                  │
└───────────────────────────────────────────────────────────────────────────┘

MONITORING (n8n Automated)
─────────────────────────
WF1 — Log Watcher (every 5 min):
  n8n cron → GET /api/logs/all/latest-errors
  IF errors found → POST to #campbell-ops-alerts (Mattermost alert)

WF2 — Daily Digest (9am UTC):
  n8n cron → GET /api/incidents + GET /api/health
  → Format 24h summary → POST to #campbell-ops-alerts

ALERT FLOW (when failure injected)
───────────────────────────────────
POST /api/logs/{service}/inject
  → INSERT campbell_incidents (status=open)
  → POST Mattermost: "🚨 [Airflow] KeyError... | $50k at risk"
  → SSE broadcast → dashboard: card appears in Open column

KAJI DIAGNOSIS FLOW (async, with live steps)
──────────────────────────────────────────────
POST /api/incidents/{id}/diagnose
  → simulate_diagnosis_flow() background task:
      Step 1: read_logs(service) → confirm error
      Step 2: search_confluence("{service} runbook")
      Step 3: read_confluence_page(runbook)        ← KB Hit event
      Step 4: search_incident_history(service)      ← History Hit event
      Step 5: read_source_file(file:line)
      Step 6: generate_patch()
      → Each step: SSE diagnosis_step → shows in modal + card
  → UPDATE incidents SET status='diagnosed', diagnosis=..., code_diff=...
  → SSE: incident_diagnosed

WF3 — HUMAN-IN-THE-LOOP CODE REVIEW
─────────────────────────────────────
POST /api/incidents/{id}/request-review  [or "Request Human Review" button]
  → UPDATE status='review_pending'
  → POST Mattermost interactive message:
      "🔍 Code Review Required — [Service]
       Error | File | Root Cause | Diff | Risk | Historical Ref
       [✅ Approve & Apply]  [❌ Reject — Retry]"

  IF [✅ Approve] clicked:
    → Mattermost POSTs to POST /api/webhooks/approve/{id}
    → simulate_fix_flow(): status=fixing → build steps → status=resolved
    → POST Mattermost: "✅ Fix applied by Jimmy. Commit a3f92c1. Dashboard updated."

  IF [❌ Reject] clicked:
    → Mattermost POSTs to POST /api/webhooks/reject/{id}
    → status → 'diagnosed', POST Mattermost: "Fix rejected — @kaji retry"

FIX + CI/CD SIMULATION
──────────────────────
simulate_fix_flow() (background):
  1. status = 'fixing'
  2. SSE: kaji_activity "apply_code_fix"
  3. SSE: build_started {commit, build_name}
  4. SSE × 5: build_step "Pulling" → "Installing" → "Testing" → "PASSED" → "Deployed"
  5. status = 'resolved', savings += impact
  6. SSE: incident_resolved → savings counter bumps
  7. POST Mattermost: fix confirmation

CLICKUP TICKET
──────────────
POST /api/incidents/{id}/create-ticket
  → ClickUp API: POST /api/v2/list/901320600795/task
  → Labels: campbell-ops, kaji, {service}
  → UPDATE incidents SET clickup_url=...
  → SSE: ticket_created → card shows ClickUp link

REAL-TIME DASHBOARD (SSE)
──────────────────────────
GET /api/stream → SSE event stream
Events:
  log              → Log Stream panel
  kaji_activity    → Kaji Activity panel
  kb_hit           → KB Hits panel
  diagnosis_step   → Live steps in card + modal
  build_step       → CI/CD steps in card + modal
  incident_*       → Kanban card moves
  ticket_created   → ClickUp link appears
```

---

## When Mattermost Is Used

| Trigger | Message |
|---|---|
| Service failure | 🚨 Alert with service, error, $ at risk |
| Request Review | Interactive message with ✅/❌ buttons |
| Fix approved + applied | ✅ Commit hash + build status |
| Fix rejected | ❌ Notice, Kaji retries |
| n8n WF1 (every 5 min) | Errors detected alert |
| n8n WF2 (9am daily) | 24h digest + savings |

---

## When n8n Is Used

| Workflow | Trigger | Action |
|---|---|---|
| WF1 Log Watcher | Every 5 min | Poll errors → alert |
| WF2 Daily Digest | 9am UTC | Summarize → post |
| WF3 Code Review | POST from Campbell API | Format + interactive MM message |

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + Uvicorn (Python 3.10) |
| Database | Supabase Metaflow (PostgreSQL) |
| Frontend | Alpine.js 3 + Tailwind CSS CDN |
| Real-time | Server-Sent Events |
| Monitoring | n8n v2 (3 workflows) |
| Alerts | Mattermost (`#campbell-ops-alerts`) |
| Tickets | ClickUp API (Campbell & Company list) |

---

## 5 Demo Scenarios

| Service | Error | Impact |
|---|---|---|
| Airflow | `KeyError: 'close_price'` | $50,000 |
| Bloomberg | `ConnectionTimeout` | $75,000 |
| TeamCity | `AssertionError test:87` | $25,000 |
| Risk Calculator | `NullPointerException` | $100,000 |
| Price Feed | `DataQualityException 7.3%` | $60,000 |
| **Total** | | **$310,000** |

---

## API Endpoints

```
GET  /api/health                        → service statuses
POST /api/logs/{service}/inject         → inject failure
GET  /api/logs/all/latest-errors        → for n8n WF1
GET  /api/incidents                     → all incidents (enriched)
POST /api/incidents/{id}/diagnose       → async diagnosis
POST /api/incidents/{id}/request-review → human review flow
POST /api/incidents/{id}/apply-fix      → apply + CI
POST /api/incidents/{id}/create-ticket  → ClickUp ticket
POST /api/webhooks/approve/{id}         → MM button handler
POST /api/webhooks/reject/{id}          → MM button handler
GET  /api/stream                        → SSE events
POST /api/demo/reset                    → clean slate
GET  /.well-known/skills/campbell-ops/SKILL.md → Kaji skill
```
