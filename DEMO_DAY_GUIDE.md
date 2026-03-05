# Demo Day Guide — Campbell & Company Ops Co-Pilot

**URL**: https://campbell-ops-demo.dev.hyperplane.dev  
**Mattermost channel**: #campbell-ops-alerts  
**ClickUp**: Campbell & Company list

---

## Pre-Demo Setup (5 min before)

1. **Open these tabs**:
   - Tab 1: https://campbell-ops-demo.dev.hyperplane.dev (Incident Board)
   - Tab 2: Mattermost → #campbell-ops-alerts
   - Tab 3: https://app.clickup.com/90131266176/v/l/901320600795 (Campbell list)
   - Tab 4: https://n8n-v2.dev.hyperplane.dev (show n8n workflows running)

2. **Reset the demo**: Click ↺ on the Incident Board or call `POST /api/demo/reset`

3. **Verify all systems green**: Top bar shows ✅ for all 5 services

4. **Mode**: Keep in `🎮 SIM` mode for demo

---

## The 20-Minute Script

### Act 1 — Open on the Dashboard (3 min)

Start here. No explanation needed — execs see the UI.

- Top bar: 5 systems, all green. _"This is your ops state right now — one view."_
- Empty kanban. _"No open incidents. Healthy morning."_
- $0 savings. _"By the end, that number will be very different."_
- Switch to Live Feed tab — panels empty. _"When something happens, this lights up."_

**Then**: Switch to Live Feed → click **⚡ Simulate Airflow** (or use 🎲 Simulate Random)

↳ Dashboard: Airflow turns 🔴. Card appears in Open column.
↳ Mattermost: alert fires automatically.

_"It's 7:15am. Airflow failed at 2:14am. Your system caught it. Nobody had to check."_

---

### Act 2 — The Monitoring System (2 min)

Stay on Live Feed tab.

- Show the n8n icon → switch to n8n tab briefly
- _"This ran at 2:14am. Found the error. Posted the alert automatically."_
- Show WF2 daily digest workflow. _"Every morning at 9am, your team gets a summary — before anyone asks."_

_"Monitoring that works while your engineers sleep."_

---

### Act 3 — Kaji Diagnoses in 30 Seconds (4 min)

Switch to Mattermost. The alert is already there.

**In Mattermost, type**: `@kaji what failed in Airflow last night and what's the fix?`

Switch back to Live Feed — watch panels populate in real time:
- Log Stream: error lines appear
- Kaji Activity: tool calls stream (`read_logs`, `search_confluence`, `search_incident_history`, `read_source_file`, `generate_patch`)
- KB Hits: Airflow Runbook page appears
- History: CAMP-847 referenced

Switch back to Incident Board — card moves from Open → **Diagnosed**.
Click the card → modal shows: root cause, code diff, resolution steps.

_"Three data sources. Thirty seconds. A senior engineer: 45 minutes."_

---

### Act 4 — Human Review (THE WOW MOMENT) (3 min)

In the modal, click **🔍 Request Human Review**.

↳ Mattermost receives an interactive message:
```
🔍 Code Review Required — Airflow Market Data
Error: KeyError: 'close_price' | File: transform_equity_data.py:142
Root Cause: Bloomberg renamed field...
[DIFF shown]
Risk: High — Production trading infrastructure
Ref: CAMP-847

[✅ Approve & Apply]  [❌ Reject — Retry]
```

**Jimmy in the room clicks ✅ Approve & Apply**

↳ Dashboard: card moves to ⚙️ Fixing
↳ Live Feed: build steps stream in real time (Pulling → Installing → Testing → PASSED)
↳ Mattermost: "✅ Fix applied by Jimmy. Commit a3f92c1. Build: market_data_pipeline — PASSED"
↳ Dashboard: card moves to ✅ Resolved. **Savings counter: +$50,000**

_"Kaji finds the fix. n8n holds it for review. Jimmy approves from Mattermost. Nobody touched a server."_

---

### Act 5 — Scale It (3 min)

Click **🎲 Simulate Random** — AI picks the next most relevant scenario.

Walk through 2 more: Bloomberg ($75k) + Risk Calculator ($100k).

- Each time: alert → diagnose → review → approve → resolve → counter increments
- By now: **$225,000**

_"This isn't one use case. It's a system. Every class of failure, same workflow."_

---

### Act 6 — Live ClickUp Ticket (1 min)

On any resolved card, click **🎫 Create Ticket**.

↳ ClickUp ticket created in "Campbell & Company" list  
↳ Link appears on the card  
↳ Switch to ClickUp tab — ticket is live

_"That's your real system. Real ticket. Not a mock."_

---

### Act 7 — Settings: When You're Ready to Go Live (2 min)

Click ⚙️ Settings.

Show the **🔴 Live Mode** button. Click it.

_"Right now we're in Simulation Mode. When you hand us these credentials—"_

Walk through each integration field: Airflow, Confluence, Jira, Perforce, TeamCity, Mattermost.

Click **🔌 Test All Connections** — all show ✅.

_"—the demo system you just watched becomes your production system. Same Kaji. Real data. Days, not weeks."_

**Final counter: $310,000.**

---

## Talking Points

| Moment | Line |
|---|---|
| Alert fires | "Your system caught it. Nobody had to check." |
| Diagnosis | "Three data sources. Thirty seconds. A senior engineer: 45 minutes." |
| Human review | "Kaji finds the fix. n8n holds it for review. Jimmy approves. Nobody touched a server." |
| Fix applied | "Detected, diagnosed, reviewed, fixed, CI verified. One button." |
| Scale | "This isn't one use case. It's a system." |
| ClickUp | "That's your real system. Real ticket. Not a mock." |
| Settings | "Days, not weeks." |

---

## Going Live — Production Checklist

When Campbell is ready to go from demo to production:

### Week 1 — Connections (2-3 days)
- [ ] Airflow: endpoint + service account credentials
- [ ] Confluence: base URL + API token + space key
- [ ] Mattermost: self-hosted → point to Campbell's server + bot token
- [ ] ClickUp / Jira: project key + API token

### Week 1 — Data Sources (1-2 days)
- [ ] Connect to real Airflow logs (replace mock `/api/logs` with real Airflow API)
- [ ] Connect to real Bloomberg feed (replace `ConnectionTimeout` with real alerts)
- [ ] Connect to real TeamCity webhooks
- [ ] Connect to real risk engine logs

### Week 2 — Kaji Configuration (1-2 days)
- [ ] Load real Confluence runbooks into Kaji's KB
- [ ] Load historical incident data into `campbell_incidents`
- [ ] Configure real Perforce/Git access for code fix application
- [ ] Set `authMethod: LIVE` in Settings → switch from simulation

### Week 2 — n8n Workflows (1 day)
- [ ] Import `n8n/campbell-log-watcher.json` → point to production endpoints
- [ ] Import `n8n/campbell-daily-digest.json` → set team email list
- [ ] Import `n8n/wf3-code-review-human-loop.json` → set approval routing

### Production Deployment
Same Shakudo microservice, same code, same dashboard.
Just swap: mock data → real integrations, simulation mode → live mode.

**Estimated time from demo to production: 5-10 business days.**

---

## Demo Reset

Between demos, go to Live Feed → Click **↺ Reset Demo** (bottom right of simulation panel).

Or call: `POST https://campbell-ops-demo.dev.hyperplane.dev/api/demo/reset`
