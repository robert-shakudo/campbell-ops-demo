---
name: campbell-ops
description: "Campbell & Company Ops Co-Pilot — monitor, diagnose, and fix infrastructure incidents from chat. Injects failures, runs diagnoses, applies fixes, creates ClickUp tickets, and queries incident history. Use when someone asks about Campbell ops alerts, service failures, Airflow/Bloomberg/TeamCity/risk-calculator/price-feed issues, or wants to trigger/resolve a demo incident."
license: MIT
compatibility: opencode
metadata:
  author: robert-shakudo
  version: "1.0"
  category: ops
---

# Campbell Ops Co-Pilot

Live operations demo for Campbell & Company. Kaji monitors 5 trading infrastructure services, diagnoses failures using Confluence + incident history, and applies code fixes with CI verification — all from Mattermost chat.

**Live endpoint**: `https://campbell-ops-demo.dev.hyperplane.dev`

**Ops channel**: `#campbell-ops-alerts`

---

## When to Activate

- Someone asks about a Campbell service failure or alert
- Requests to "inject" a demo failure scenario
- Asking for root cause or diagnosis of an Airflow/Bloomberg/TeamCity/risk-calculator/price-feed error
- Wants to apply a fix, check build status, or create a ticket
- Questions about the demo: savings counter, incident board, live feed

---

## Available Actions

### From Mattermost (#campbell-ops-alerts)

```
@kaji what failed in Airflow last night and what's the fix?
@kaji inject a Bloomberg failure
@kaji diagnose the risk calculator incident
@kaji apply the fix for the Airflow incident
@kaji create a ClickUp ticket for the price feed issue — assign to Jimmy
@kaji set up a daily 9am ops check for all services
@kaji show me the current incident board
@kaji reset the demo
```

### API Endpoints (for tool calls)

**Health & Status**
```bash
GET https://campbell-ops-demo.dev.hyperplane.dev/api/health
# → all 5 service statuses

GET https://campbell-ops-demo.dev.hyperplane.dev/api/incidents
# → all incidents with enriched detail (source, resolution steps, notified)
```

**Demo Control**
```bash
POST https://campbell-ops-demo.dev.hyperplane.dev/api/logs/{service}/inject
# service: airflow | bloomberg | teamcity | risk-calculator | price-feed
# → injects failure, posts Mattermost alert, creates Supabase incident

POST https://campbell-ops-demo.dev.hyperplane.dev/api/incidents/{id}/diagnose
# → runs diagnosis, queries Confluence + incident history, returns root cause + diff

POST https://campbell-ops-demo.dev.hyperplane.dev/api/incidents/{id}/apply-fix
# → applies code patch, runs build simulation, moves card to Resolved

POST https://campbell-ops-demo.dev.hyperplane.dev/api/incidents/{id}/create-ticket
# → creates ClickUp ticket in Campbell & Company list

POST https://campbell-ops-demo.dev.hyperplane.dev/api/demo/reset
# → clears all incidents, resets services to healthy
```

**Knowledge Base & Logs**
```bash
GET https://campbell-ops-demo.dev.hyperplane.dev/api/confluence/search?q=airflow
GET https://campbell-ops-demo.dev.hyperplane.dev/api/confluence/page/airflow-runbook
GET https://campbell-ops-demo.dev.hyperplane.dev/api/incidents/history?q=close_price
GET https://campbell-ops-demo.dev.hyperplane.dev/api/logs/airflow/latest-error
GET https://campbell-ops-demo.dev.hyperplane.dev/api/logs/all/latest-errors
```

---

## The 5 Demo Scenarios

| Service | Error | Impact | Historical Ref |
|---|---|---|---|
| Airflow | `KeyError: 'close_price'` | $50,000 | CAMP-847 |
| Bloomberg | `ConnectionTimeout` | $75,000 | CAMP-891 |
| TeamCity | `AssertionError test:87` | $25,000 | CAMP-834 |
| Risk Calculator | `NullPointerException` | $100,000 | CAMP-812 |
| Price Feed | `DataQualityException 7.3%` | $60,000 | CAMP-799 |
| **Total** | | **$310,000** | |

---

## Tool Call Examples (for agents)

```python
import httpx

BASE = "https://campbell-ops-demo.dev.hyperplane.dev"

def inject_failure(service: str) -> dict:
    r = httpx.post(f"{BASE}/api/logs/{service}/inject")
    return r.json()

def get_incidents() -> list:
    r = httpx.get(f"{BASE}/api/incidents")
    return r.json()["incidents"]

def diagnose(incident_id: str) -> dict:
    r = httpx.post(f"{BASE}/api/incidents/{incident_id}/diagnose")
    return r.json()

def apply_fix(incident_id: str) -> dict:
    r = httpx.post(f"{BASE}/api/incidents/{incident_id}/apply-fix")
    return r.json()

def search_confluence(query: str) -> list:
    r = httpx.get(f"{BASE}/api/confluence/search", params={"q": query})
    return r.json()["results"]
```

---

## Architecture

```
#campbell-ops-alerts (Mattermost)
        ↓ @kaji prompt
Kaji → Campbell Ops API (FastAPI)
        ↓
Supabase (incidents + kaji_activity)
        ↓ SSE
Dashboard (Alpine.js + Tailwind, 3 themes)
        ↓
n8n v2 (5-min watcher + 9am daily digest)
```

## Skill Discovery

```
GET https://campbell-ops-demo.dev.hyperplane.dev/.well-known/skills/campbell-ops/SKILL.md
```
