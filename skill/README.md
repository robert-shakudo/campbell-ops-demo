# Campbell Ops Co-Pilot — Kaji Skill

Chat-native operations monitoring for Campbell & Company's trading infrastructure.
Kaji monitors 5 services, diagnoses failures from Confluence + incident history, applies fixes, and creates ClickUp tickets — all from Mattermost.

**Live app:** https://campbell-ops-demo.dev.hyperplane.dev
**Ops channel:** #campbell-ops-alerts

---

## Install via Skills Marketplace (Recommended)

### Step 1 — Open the Skills Marketplace

Go to: **https://kaji-admin-monitor.dev.hyperplane.dev**

Navigate to **Skills** in the left sidebar.

### Step 2 — Add the repo

Click **"Install from GitHub"** and enter:

```
robert-shakudo/campbell-ops-demo
```

The marketplace will scan the repo and detect the skill at `skill/SKILL.md`.

### Step 3 — Select and install

Select **`campbell-ops`** from the detected skills list and click **Install**.

### Step 4 — Configure the backend URL

In the Skills section, find `campbell-ops` → **Configure** → set:

```
CAMPBELL_OPS_URL = https://campbell-ops-demo.dev.hyperplane.dev
```

---

## Install via CLI (`openskills`)

```bash
openskills install robert-shakudo/campbell-ops-demo/skill
```

Set the environment variable:

```bash
echo "CAMPBELL_OPS_URL=https://campbell-ops-demo.dev.hyperplane.dev" \
  >> /root/gitrepos/.claude/skills/campbell-ops/.env
```

---

## Use from Terminal

```bash
# Set the app URL
export CAMPBELL_OPS_URL=https://campbell-ops-demo.dev.hyperplane.dev

# List all incidents
python skill/campbell_client.py list

# Inject a failure scenario
python skill/campbell_client.py inject airflow
python skill/campbell_client.py inject bloomberg
python skill/campbell_client.py inject teamcity
python skill/campbell_client.py inject risk-calculator
python skill/campbell_client.py inject price-feed

# Diagnose an incident
python skill/campbell_client.py diagnose <incident-id>

# Apply a fix
python skill/campbell_client.py fix <incident-id>

# Create a ClickUp ticket
python skill/campbell_client.py ticket <incident-id>

# Check service health
python skill/campbell_client.py health

# Reset all incidents (back to green)
python skill/campbell_client.py reset
```

---

## Use from Mattermost (#campbell-ops-alerts)

```
@kaji what failed in Airflow last night and what's the fix?
@kaji inject a Bloomberg failure
@kaji diagnose the risk calculator incident
@kaji apply the fix for the Airflow incident
@kaji create a ClickUp ticket for the price feed issue — assign to Jimmy
@kaji show me the current incident board
@kaji reset the demo
```

---

## The 5 Demo Scenarios

| Service | Error | Impact |
|---|---|---|
| Airflow | `KeyError: 'close_price'` | $50,000 |
| Bloomberg | `ConnectionTimeout` | $75,000 |
| TeamCity | `AssertionError test:87` | $25,000 |
| Risk Calculator | `NullPointerException` | $100,000 |
| Price Feed | `DataQualityException 7.3%` | $60,000 |
| **Total** | | **$310,000** |
