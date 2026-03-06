"""
Campbell & Company — Ops Co-Pilot Demo Backend
FastAPI + Supabase + Mattermost + SSE
Port: 8787
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import string
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

import httpx
import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─────────────────────────── Config ───────────────────────────
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:changeme@supabase-metaflow-postgresql.hyperplane-supabase-metaflow.svc.cluster.local:5432/postgres",
)
MM_URL = os.getenv(
    "MATTERMOST_URL",
    "http://mattermost-mattermost-enterprise-edition.hyperplane-mattermost.svc.cluster.local:8065",
)
MM_TOKEN = os.getenv("MATTERMOST_TOKEN", "")
MM_CHANNEL_ID = os.getenv("MM_CHANNEL_ID", "cw5wxp5wajrz5nkc1yeqyxbazc")
MM_EXT = os.getenv("MM_EXT_URL", "https://mattermost.dev.hyperplane.dev")
ANTHROPIC_KEY = os.getenv(
    "ANTHROPIC_API_KEY",
    "",
)
CLICKUP_LIST_ID = os.getenv("CLICKUP_LIST_ID", "901320600795")
CLICKUP_TOKEN = os.getenv(
    "CLICKUP_TOKEN", "pk_150142682_TO57FJP04N2FUC2QSTYA28PBZL8QGN3V"
)
DEMO_URL = os.getenv("DEMO_URL", "https://campbell-ops-demo.dev.hyperplane.dev")
_CAMPBELL_INTERNAL_DEFAULT = (
    "http://hyperplane-service-e400e4.hyperplane-pipelines.svc.cluster.local:8787"
)
WEBHOOK_BASE = os.getenv("CAMPBELL_INTERNAL_URL", _CAMPBELL_INTERNAL_DEFAULT)
N8N_KEY = os.getenv(
    "N8N_API_KEY",
    "",
)
N8N_WF3_WEBHOOK = os.getenv("N8N_WF3_WEBHOOK_URL", "")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("campbell")

app = FastAPI(title="Campbell Ops Co-Pilot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────── SSE State ───────────────────────────
sse_subscribers: List[asyncio.Queue] = []
log_subscribers: List[asyncio.Queue] = []

# ─────────────────────────── In-memory state ───────────────────────────
# Tracks which services are currently "down" (injected failure)
service_failures: Dict[str, Optional[Dict]] = {
    "airflow": None,
    "bloomberg": None,
    "teamcity": None,
    "risk-calculator": None,
    "price-feed": None,
}

# Simulated log buffer (circular, per service)
log_buffer: Dict[str, List[Dict]] = {s: [] for s in service_failures}

# Active kaji sessions per incident
kaji_threads: Dict[str, str] = {}  # incident_id → mattermost post_id

# ─────────────────────────── Mock Data ───────────────────────────
SERVICES_CONFIG = {
    "airflow": {
        "display": "Airflow Market Data",
        "icon": "⚡",
        "error": "KeyError: 'close_price' in transform_equity_data.py:142",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/opt/airflow/dags/market_data_ingestion.py", line 68, in run\n'
            "    result = transform_equity_data(raw)\n"
            '  File "/opt/airflow/tasks/transform_equity_data.py", line 142, in transform_equity_data\n'
            "    data['close'] = row['close_price']\n"
            "KeyError: 'close_price'"
        ),
        "impact": 50000,
        "scenario": "Bloomberg upstream field renamed close_price → closing_price. Transform not updated.",
        "root_cause": "Bloomberg upstream renamed field `close_price` → `closing_price` in their v4.2 API. The transform in `transform_equity_data.py:142` uses the old field name. Historical incident CAMP-847 (Dec 2024) resolved the same issue in 18 minutes by switching to a `.get()` accessor.",
        "fix_file": "transform_equity_data.py",
        "fix_line": 142,
        "fix_diff": (
            "-        data['close'] = row['close_price']\n"
            "+        data['close'] = row.get('closing_price') or row.get('close_price')"
        ),
        "confluence_page": "airflow-runbook",
        "historical_incident": "CAMP-847",
        "commit_hash": "a3f92c1",
        "build_name": "market_data_pipeline",
        "source_file": "transform_equity_data.py",
        "source_line": 142,
        "source_function": "transform_equity_data",
        "source_dag": "market_data_ingestion",
        "notified": [
            "@airflow-oncall (Mattermost)",
            "#campbell-ops-alerts",
            "Automated monitoring alert",
        ],
        "resolution_steps": [
            "Kaji reads Airflow logs — confirms KeyError on field 'close_price'",
            "Kaji searches Confluence for 'Airflow Market Data Pipeline Runbook'",
            "Kaji searches incident history — finds CAMP-847 (Dec 2024, identical issue, 18 min fix)",
            "Kaji reads transform_equity_data.py:142 — identifies the failing field accessor",
            "Kaji generates patch: row['close_price'] → row.get('closing_price') or row.get('close_price')",
            "Kaji applies patch via /git/patch — commit a3f92c1",
            "TeamCity build market_data_pipeline triggered automatically",
            "All tests pass — build PASSED ✓",
            "Airflow DAG market_data_ingestion resumes on next poll cycle",
        ],
        "jira_ticket": {
            "id": "CAMP-1024",
            "url": "https://campbell.atlassian.net/browse/CAMP-1024",
            "title": "Airflow market_data_ingestion — KeyError close_price (Bloomberg schema change)",
            "status": "Done",
            "priority": "High",
            "assignee": "Jimmy Chen",
            "reporter": "Kaji (automated)",
            "sprint": "Sprint 23",
            "story_points": 2,
            "labels": ["airflow", "bloomberg", "data-pipeline", "production", "P1"],
            "time_to_fix_min": 13,
            "components": ["Market Data", "Airflow Infrastructure"],
            "description": "Bloomberg v4.2 API renamed field close_price → closing_price. transform_equity_data.py:142 uses old field name causing market_data_ingestion DAG to fail. Kaji auto-diagnosed and applied a one-line defensive accessor fix. Build passed. Service restored in 13 minutes.",
        },
        "roi_breakdown": {
            "summary": "$50,000 exposure",
            "calculation": "5+ hours stale data × $9,615/hr signal degradation",
            "components": [
                {"label": "Failure window", "value": "02:14 – 02:27 UTC (13 min)"},
                {"label": "Symbols affected", "value": "847 equities"},
                {"label": "Downstream models stale", "value": "3 trading strategies"},
                {"label": "Avg. impact/hr", "value": "$9,615"},
                {"label": "Max exposure (5h outage)", "value": "$50,000"},
            ],
            "mitigated_by": "Kaji fix in 13 min — exposure window capped at ~$2,100 actual",
            "actual_loss": "$2,100",
        },
        "related_issues": [
            {
                "id": "CAMP-847",
                "title": "Bloomberg field rename close_price Dec 2024",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-847",
            },
            {
                "id": "CAMP-791",
                "title": "Bloomberg API v4.1 upstream schema changes",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-791",
            },
            {
                "id": "CAMP-712",
                "title": "Airflow DAG market_data_ingestion failure Nov 2024",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-712",
            },
        ],
    },
    "bloomberg": {
        "display": "Campbell Compress (Bloomberg)",
        "icon": "📡",
        "error": "ConnectionTimeout: Bloomberg feed endpoint unreachable after 30s",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/opt/campbell/compress/bloomberg_feed_client.py", line 89, in connect\n'
            "    sock.connect((BLOOMBERG_HOST, BLOOMBERG_PORT), timeout=30)\n"
            "socket.timeout: timed out\n"
            "ConnectionError: Bloomberg feed endpoint 10.0.0.45:8194 unreachable after 30s"
        ),
        "impact": 75000,
        "scenario": "Bloomberg endpoint port changed from 8194 to 8196.",
        "root_cause": "Bloomberg updated their internal feed infrastructure. Port 8194 is now deprecated; all feeds now route through 8196. CAMP-891 (Jan 2025) recorded the same issue — took 45 minutes to find.",
        "fix_file": "bloomberg_feed_client.py",
        "fix_line": 12,
        "fix_diff": (
            "-BLOOMBERG_PORT = 8194\n"
            "+BLOOMBERG_PORT = 8196  # Updated per Bloomberg infrastructure change Jan/Mar 2025"
        ),
        "confluence_page": "bloomberg-troubleshooting",
        "historical_incident": "CAMP-891",
        "commit_hash": "b7d41e3",
        "build_name": "bloomberg_compress_service",
        "source_file": "bloomberg_feed_client.py",
        "source_line": 89,
        "source_function": "connect",
        "source_dag": "campbell_compress",
        "notified": [
            "@bloomberg-oncall (Mattermost)",
            "#campbell-ops-alerts",
            "PagerDuty P1 alert",
        ],
        "resolution_steps": [
            "Kaji reads Campbell Compress service logs — confirms repeated connection timeouts to port 8194",
            "Kaji searches Confluence for 'Campbell Compress Bloomberg Feed Troubleshooting'",
            "Kaji finds CAMP-891 (Jan 2025) — identical port change issue, 45 min resolution",
            "Kaji reads bloomberg_feed_client.py — identifies BLOOMBERG_PORT = 8194 on line 12",
            "Kaji checks Bloomberg portal changelog — confirms port migration 8194 → 8196",
            "Kaji applies patch: BLOOMBERG_PORT = 8194 → 8196 — commit b7d41e3",
            "Build bloomberg_compress_service triggered and passes",
            "Campbell Compress reconnects to Bloomberg feed within 30s of restart",
        ],
        "jira_ticket": {
            "id": "CAMP-1031",
            "url": "https://campbell.atlassian.net/browse/CAMP-1031",
            "title": "Campbell Compress — Bloomberg feed connection timeout (port 8194 deprecated)",
            "status": "Done",
            "priority": "Critical",
            "assignee": "Sarah Kim",
            "reporter": "Kaji (automated)",
            "sprint": "Sprint 23",
            "story_points": 3,
            "labels": [
                "bloomberg",
                "connectivity",
                "production",
                "P0",
                "real-time-feed",
            ],
            "time_to_fix_min": 28,
            "components": ["Campbell Compress", "Bloomberg Integration"],
            "description": "Bloomberg infrastructure migration deprecated port 8194. All feed connections now route through 8196. Kaji auto-detected the port change via Confluence changelog + incident history cross-reference. One-line config fix, service restored in 28 minutes.",
        },
        "roi_breakdown": {
            "summary": "$75,000 exposure",
            "calculation": "Real-time feed offline × stale position valuation risk",
            "components": [
                {"label": "Feed outage window", "value": "02:11 – 02:39 UTC (28 min)"},
                {"label": "Positions affected", "value": "~2,341 open positions"},
                {"label": "Avg. stale price risk", "value": "$32/position/min"},
                {
                    "label": "Regulatory revaluation exposure",
                    "value": "$75,000 at 28 min",
                },
            ],
            "mitigated_by": "Kaji fix in 28 min — limited exposure vs 45 min avg manual resolution",
            "actual_loss": "$14,000",
        },
        "related_issues": [
            {
                "id": "CAMP-891",
                "title": "Bloomberg port change 8194→8196 Jan 2025",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-891",
            },
            {
                "id": "CAMP-834",
                "title": "Bloomberg API key rotation failure Nov 2024",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-834",
            },
            {
                "id": "CAMP-756",
                "title": "Campbell Compress reconnect retry logic",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-756",
            },
        ],
    },
    "teamcity": {
        "display": "TeamCity CI/CD",
        "icon": "🔧",
        "error": "AssertionError: test_portfolio_risk_var_calculation in risk_calculator_test.py:87",
        "stack_trace": (
            "FAILED risk_calculator_test.py::test_portfolio_risk_var_calculation\n"
            '  File "/builds/risk/risk_calculator_test.py", line 87, in test_portfolio_risk_var_calculation\n'
            "    assert result == 0.0234\n"
            "AssertionError: assert {'var_95': 0.0234, 'var_99': 0.0312, 'method': 'historical'} == 0.0234\n"
            "+ where {'var_95': 0.0234, ...} = calculate_var(test_portfolio)"
        ),
        "impact": 25000,
        "scenario": "VaR calculation output format changed from float to dict. Test expects old format.",
        "root_cause": "Q4 2024 enhancement: VaR calculation now returns full dict `{var_95, var_99, method}` instead of single float. Test at line 87 still asserts `result == 0.0234` (expects float). Fix: assert `result['var_95'] == 0.0234`.",
        "fix_file": "risk_calculator_test.py",
        "fix_line": 87,
        "fix_diff": (
            "-    assert result == 0.0234\n"
            "+    assert result['var_95'] == 0.0234  # VaR dict format since Q4 2024"
        ),
        "confluence_page": "teamcity-build-failures",
        "historical_incident": "CAMP-834",
        "commit_hash": "c8e52f9",
        "build_name": "risk_model_pipeline",
        "source_file": "risk_calculator_test.py",
        "source_line": 87,
        "source_function": "test_portfolio_risk_var_calculation",
        "source_dag": "risk_model_pipeline build #4821",
        "notified": [
            "#campbell-ops-alerts",
            "@eng-oncall (Mattermost)",
            "TeamCity email notification",
        ],
        "resolution_steps": [
            "Kaji reads TeamCity build logs — identifies AssertionError on line 87",
            "Kaji searches Confluence for 'TeamCity Build Failures — Common Causes'",
            "Kaji reads risk_calculator_test.py:87 — confirms old float assertion vs new dict output",
            "Kaji searches incident history — finds CAMP-834 (Nov 2024), same assertion pattern",
            "Kaji generates patch: assert result == 0.0234 → assert result['var_95'] == 0.0234",
            "Kaji applies patch — commit c8e52f9",
            "TeamCity rebuild triggered — test_portfolio_risk_var_calculation now passes",
            "Build risk_model_pipeline PASSED — trading model deployment unblocked",
        ],
        "jira_ticket": {
            "id": "CAMP-1028",
            "url": "https://campbell.atlassian.net/browse/CAMP-1028",
            "title": "TeamCity build failure — VaR test assertion mismatch after Q4 2024 dict format change",
            "status": "Done",
            "priority": "Medium",
            "assignee": "Marcus Webb",
            "reporter": "Kaji (automated)",
            "sprint": "Sprint 23",
            "story_points": 1,
            "labels": ["teamcity", "unit-test", "risk-model", "ci-cd"],
            "time_to_fix_min": 8,
            "components": ["Risk Model CI", "TeamCity"],
            "description": "VaR calculate_var() changed return type from float to dict {var_95, var_99, method} in Q4 2024. Test assertion at risk_calculator_test.py:87 was not updated. Kaji matched to CAMP-834 pattern and applied a 1-line fix. Build passed in 8 minutes.",
        },
        "roi_breakdown": {
            "summary": "$25,000 exposure",
            "calculation": "Trading model deployment blocked × strategy update delay cost",
            "components": [
                {"label": "Build block window", "value": "02:14 – 02:22 UTC (8 min)"},
                {
                    "label": "Strategy updates blocked",
                    "value": "2 pending model deployments",
                },
                {"label": "Avg. strategy value/hr", "value": "$12,500"},
                {"label": "Max exposure (2hr manual fix)", "value": "$25,000"},
            ],
            "mitigated_by": "Kaji fix in 8 min — negligible actual impact",
            "actual_loss": "$0",
        },
        "related_issues": [
            {
                "id": "CAMP-834",
                "title": "TeamCity VaR test assertion pattern Nov 2024",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-834",
            },
            {
                "id": "CAMP-798",
                "title": "Risk model CI test brittleness review",
                "status": "In Progress",
                "url": "https://campbell.atlassian.net/browse/CAMP-798",
            },
        ],
    },
    "risk-calculator": {
        "display": "Risk Calculator Engine",
        "icon": "⚖️",
        "error": "NullPointerException: PortfolioRiskEngine.calculate() — positions is null",
        "stack_trace": (
            'Exception in thread "risk-calculator" java.lang.NullPointerException\n'
            "  at com.campbell.risk.PortfolioRiskEngine.calculate(PortfolioRiskEngine.java:234)\n"
            "  at com.campbell.risk.RiskService.runDaily(RiskService.java:89)\n"
            "  at com.campbell.scheduler.CronScheduler.execute(CronScheduler.java:45)\n"
            "Caused by: positions list is null — position feed timeout at 02:11 UTC"
        ),
        "impact": 100000,
        "scenario": "Position feed timeout causing null positions list passed to risk engine.",
        "root_cause": "Position feed service timed out at 02:11 UTC. `getPositions()` returned null instead of empty list. `PortfolioRiskEngine.calculate()` has no null guard at line 234. Fix: add null check with cached positions fallback. Compliance must be notified if risk engine is offline >4h during market hours.",
        "fix_file": "PortfolioRiskEngine.java",
        "fix_line": 234,
        "fix_diff": (
            " List<Position> positions = positionFeed.getPositions();\n"
            "-return calculateVar(positions);\n"
            "+if (positions == null) {\n"
            '+    log.error("Position feed unavailable, using cached positions");\n'
            "+    positions = positionCache.getLatest();\n"
            "+}\n"
            "+return calculateVar(positions);"
        ),
        "confluence_page": "risk-engine-known-issues",
        "historical_incident": "CAMP-812",
        "commit_hash": "d2a17b8",
        "build_name": "risk_calculator_service",
        "source_file": "PortfolioRiskEngine.java",
        "source_line": 234,
        "source_function": "PortfolioRiskEngine.calculate()",
        "source_dag": "risk_calculator daily job",
        "notified": [
            "compliance@campbell.com",
            "@risk-oncall (Mattermost)",
            "#campbell-ops-alerts",
            "PagerDuty P0",
        ],
        "resolution_steps": [
            "Kaji reads risk calculator service logs — confirms NPE at PortfolioRiskEngine.java:234",
            "Kaji searches Confluence for 'Risk Engine — Known Issues and Patches'",
            "Kaji identifies: position feed timeout at 02:11 UTC → getPositions() returns null",
            "Kaji searches CAMP-812 (Oct 2024) — same NPE, 67 min fix, compliance notified",
            "⚠️ Regulatory alert: if offline >4h during market hours, compliance must be notified",
            "Kaji generates patch: add null check + cached positions fallback at line 234",
            "Kaji applies patch to PortfolioRiskEngine.java — commit d2a17b8",
            "Build risk_calculator_service triggered and passes all tests",
            "Risk engine restarts with cached positions — regulatory exposure window closed",
            "Compliance notified: outage was 23 min, within acceptable threshold",
        ],
        "jira_ticket": {
            "id": "CAMP-1036",
            "url": "https://campbell.atlassian.net/browse/CAMP-1036",
            "title": "Risk Calculator NPE — PortfolioRiskEngine.calculate() null positions (position feed timeout)",
            "status": "Done",
            "priority": "Critical",
            "assignee": "Dr. Alex Chen",
            "reporter": "Kaji (automated)",
            "sprint": "Sprint 23",
            "story_points": 5,
            "labels": [
                "risk-engine",
                "java",
                "null-pointer",
                "P0",
                "compliance",
                "regulatory",
            ],
            "time_to_fix_min": 23,
            "components": ["Risk Calculator", "Position Feed", "Compliance"],
            "description": "Position feed service timed out at 02:11 UTC. PortfolioRiskEngine.calculate() received null positions list and threw NPE. Kaji auto-detected, cross-referenced CAMP-812 patch, and applied null-check with cached positions fallback. Engine restored in 23 min. Compliance notified — within 4h regulatory threshold.",
        },
        "roi_breakdown": {
            "summary": "$100,000 exposure",
            "calculation": "Risk engine offline × regulatory exposure + potential compliance penalty",
            "components": [
                {
                    "label": "Engine outage window",
                    "value": "02:11 – 02:34 UTC (23 min)",
                },
                {
                    "label": "Positions unmonitored",
                    "value": "2,341 positions ($847M notional)",
                },
                {
                    "label": "Regulatory threshold",
                    "value": "4h offline → compliance report required",
                },
                {
                    "label": "Compliance penalty risk",
                    "value": "$100,000 (23 min — within threshold)",
                },
                {
                    "label": "Cached positions accuracy",
                    "value": "~99.2% (3min stale cache)",
                },
            ],
            "mitigated_by": "Kaji fix in 23 min — regulatory threshold is 4h. Compliance notified proactively.",
            "actual_loss": "$0",
        },
        "related_issues": [
            {
                "id": "CAMP-812",
                "title": "PortfolioRiskEngine NPE Oct 2024 — same root cause",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-812",
            },
            {
                "id": "CAMP-778",
                "title": "Position feed timeout SLA improvement",
                "status": "In Progress",
                "url": "https://campbell.atlassian.net/browse/CAMP-778",
            },
            {
                "id": "CAMP-901",
                "title": "Add positions null-safety across risk engine",
                "status": "Open",
                "url": "https://campbell.atlassian.net/browse/CAMP-901",
            },
        ],
    },
    "price-feed": {
        "display": "Data Quality (Price Feed)",
        "icon": "📊",
        "error": "DataQualityException: AAPL close price deviation 7.3% > 5% threshold from reference",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/opt/feeds/price_feed_validator.py", line 312, in validate_close\n'
            "    raise DataQualityException(f'{ticker} deviation {deviation:.1%} > {threshold:.0%} threshold')\n"
            "DataQualityException: AAPL close price deviation 7.3% > 5% threshold from reference\n"
            "  Primary feed: $184.22  Reference (Refinitiv): $172.45"
        ),
        "impact": 60000,
        "scenario": "Bloomberg primary feed reported AAPL $184.22 vs Refinitiv reference $172.45.",
        "root_cause": "Bloomberg primary feed had a data spike for AAPL at market close. DataQualityException correctly caught the 7.3% deviation. Fix: upgrade alert from WARN to CRITICAL + enable automatic feed switch to Refinitiv backup on CRITICAL alerts.",
        "fix_file": "price_feed_validator.py",
        "fix_line": 15,
        "fix_diff": (
            "-PRICE_DEVIATION_THRESHOLD = 0.05\n"
            "-alert_level = 'warn'\n"
            "+PRICE_DEVIATION_THRESHOLD = 0.05\n"
            "+alert_level = 'critical'  # Halt + switch to backup feed\n"
            "+HALT_ON_CRITICAL = True\n"
            "+BACKUP_FEED = 'refinitiv'"
        ),
        "confluence_page": "data-quality-framework",
        "historical_incident": "CAMP-799",
        "commit_hash": "e9f03c2",
        "build_name": "price_feed_validator",
        "source_file": "price_feed_validator.py",
        "source_line": 312,
        "source_function": "validate_close",
        "source_dag": "market_close_validation job",
        "notified": [
            "@trading-desk (Mattermost)",
            "#campbell-ops-alerts",
            "@data-platform-oncall",
        ],
        "resolution_steps": [
            "Kaji reads price feed validator logs — confirms AAPL deviation 7.3% vs 5% threshold",
            "Kaji reads DataQualityException details: primary $184.22, reference $172.45",
            "Kaji searches Confluence for 'Data Quality Framework — Alerting Thresholds'",
            "Kaji identifies: Bloomberg primary had a data spike; validator correctly caught it",
            "Kaji searches CAMP-799 (Oct 2024) — MSFT deviation, 12 min fix via backup feed switch",
            "Kaji generates patch: upgrade alert_level to 'critical', enable HALT_ON_CRITICAL",
            "Kaji applies patch to price_feed_validator.py — commit e9f03c2",
            "System automatically switches AAPL price source to Refinitiv backup",
            "Trading desk notified: AAPL data issue resolved, positions re-valued with correct price",
        ],
        "jira_ticket": {
            "id": "CAMP-1019",
            "url": "https://campbell.atlassian.net/browse/CAMP-1019",
            "title": "Data Quality Alert — AAPL price deviation 7.3% vs Refinitiv reference (Bloomberg spike)",
            "status": "Done",
            "priority": "High",
            "assignee": "Priya Sharma",
            "reporter": "Kaji (automated)",
            "sprint": "Sprint 23",
            "story_points": 2,
            "labels": ["data-quality", "bloomberg", "equities", "price-feed", "AAPL"],
            "time_to_fix_min": 12,
            "components": ["Price Feed Validator", "Data Quality Framework"],
            "description": "Bloomberg primary feed had a bad close price for AAPL ($184.22 vs $172.45 reference). DataQualityException correctly halted downstream consumption. Kaji cross-referenced CAMP-799 resolution pattern and upgraded validator to halt + switch to Refinitiv backup automatically on critical deviations. Fix deployed in 12 minutes.",
        },
        "roi_breakdown": {
            "summary": "$60,000 exposure",
            "calculation": "Corrupted AAPL data × downstream fill impact × trading volume",
            "components": [
                {
                    "label": "Price discrepancy",
                    "value": "$184.22 vs $172.45 (7.3% error)",
                },
                {"label": "AAPL positions affected", "value": "~500 open positions"},
                {"label": "Avg. bad fill cost", "value": "$120/fill at 7.3% error"},
                {
                    "label": "Estimated fills prevented",
                    "value": "500 fills × $120 = $60,000",
                },
                {
                    "label": "Detection speed",
                    "value": "0 bad fills (caught before downstream)",
                },
            ],
            "mitigated_by": "DataQualityException halted consumption before any fills executed. $60k fully avoided.",
            "actual_loss": "$0",
        },
        "related_issues": [
            {
                "id": "CAMP-799",
                "title": "MSFT price deviation 6.1% Oct 2024",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-799",
            },
            {
                "id": "CAMP-834",
                "title": "Bloomberg feed quality SLA review",
                "status": "Closed",
                "url": "https://campbell.atlassian.net/browse/CAMP-834",
            },
            {
                "id": "CAMP-902",
                "title": "Automated feed failover for price deviations >5%",
                "status": "In Progress",
                "url": "https://campbell.atlassian.net/browse/CAMP-902",
            },
        ],
    },
}

CONFLUENCE_PAGES = {
    "airflow-runbook": {
        "id": "airflow-runbook",
        "title": "Airflow Market Data Pipeline — Runbook",
        "space": "OPS",
        "content": """## Airflow Market Data Pipeline — Runbook

### Overview
The `market_data_ingestion` DAG runs every 5 minutes, pulling equity prices from Bloomberg Terminal and transforming them for downstream trading models.

### Common Failures

#### KeyError: 'close_price'
**Root cause**: Bloomberg periodically renames feed fields.  
Most common: `close_price` → `closing_price`  
**Fix**: Update field accessor in `transform_equity_data.py` to use `.get()` pattern:
```python
data['close'] = row.get('closing_price') or row.get('close_price')
```
**History**: CAMP-847 (Dec 2024) — same issue, fixed in 18 minutes.

#### DAG timeout
Increase task timeout in `airflow_config.yaml` from 300s to 600s during high-load periods.

### Escalation
Page @airflow-oncall if DAG fails >3 times in 1 hour.""",
        "author": "Jimmy Chen",
        "updated": "2025-11-15",
    },
    "bloomberg-troubleshooting": {
        "id": "bloomberg-troubleshooting",
        "title": "Campbell Compress — Bloomberg Feed Troubleshooting",
        "space": "OPS",
        "content": """## Campbell Compress — Bloomberg Feed Troubleshooting

### Connection Issues

#### Port/Endpoint Changes
Bloomberg occasionally updates endpoint configs (typically with 2-week notice in BloombergConnect portal).  
Check `bloomberg_feed_client.py` for `BLOOMBERG_PORT` constant.  
Verify with Bloomberg terminal: `CONN <GO>`.

**Known port history**:
- Port 8192 (pre-2023) → 8194 (2023) → 8196 (Jan 2025)

#### Authentication
API key rotation happens quarterly. New key in `/etc/bloomberg/api.key`.

### Incident History
- CAMP-891 (Jan 2025): Port 8194 → 8196
- CAMP-834 (Nov 2024): API key rotation missed""",
        "author": "Sarah Kim",
        "updated": "2025-12-01",
    },
    "teamcity-build-failures": {
        "id": "teamcity-build-failures",
        "title": "TeamCity Build Failures — Common Causes",
        "space": "ENG",
        "content": """## TeamCity Build Failures — Common Causes

### Test Failures

#### risk_calculator_test.py failures
The VaR tests are most brittle — output format changed Q4 2024:

**Old format** (pre-Q4 2024):
```python
result = calculate_var(portfolio)
assert result == 0.0234  # float
```

**New format** (Q4 2024+):
```python
result = calculate_var(portfolio)
assert result['var_95'] == 0.0234  # dict
```

Update all VaR test assertions to use dict key access.

### Build Times
P50: 3 min | P95: 8 min | Alert threshold: >15 min""",
        "author": "Marcus Webb",
        "updated": "2025-10-20",
    },
    "risk-engine-known-issues": {
        "id": "risk-engine-known-issues",
        "title": "Risk Engine — Known Issues and Patches",
        "space": "QUANT",
        "content": """## Risk Engine — Known Issues and Patches

### NullPointerException in PortfolioRiskEngine.calculate()

**Root cause**: When position feed times out, `getPositions()` returns `null` instead of empty list.  
**Impact**: Risk engine offline until manual restart.  
**Mitigation**: Add null guard with cached positions fallback.

```java
List<Position> positions = positionFeed.getPositions();
if (positions == null) {
    log.error("Position feed unavailable, using cached positions");
    positions = positionCache.getLatest();
}
return calculateVar(positions);
```

### Regulatory Exposure
If risk engine is offline >4h during market hours, notify compliance immediately.  
Contact: compliance@campbell.com | @compliance-team""",
        "author": "Dr. Alex Chen",
        "updated": "2025-09-30",
    },
    "data-quality-framework": {
        "id": "data-quality-framework",
        "title": "Data Quality Framework — Alerting Thresholds",
        "space": "DATA",
        "content": """## Data Quality Framework — Alerting Thresholds

### Price Deviation Thresholds

| Asset Class | Warn | Critical (halt) |
|-------------|------|-----------------|
| Equities    | 3%   | 5%              |
| Fixed Income| 1%   | 2%              |
| Derivatives | 5%   | 10%             |

### Response Procedures

**Critical Alert (>threshold)**:
1. Halt data consumption immediately
2. Switch to backup feed (Refinitiv → ICE)
3. Alert `#campbell-ops-alerts`
4. Notify @trading-desk

### Reference Feeds
Primary: Bloomberg | Secondary: Refinitiv | Tertiary: ICE""",
        "author": "Data Platform Team",
        "updated": "2025-11-01",
    },
}

HISTORICAL_INCIDENTS = [
    {
        "id": "CAMP-847",
        "service": "airflow",
        "date": "2024-12-14",
        "error": "KeyError: 'close_price' in transform_equity_data.py:142",
        "root_cause": "Bloomberg renamed field close_price → closing_price",
        "resolution": "Updated field accessor to use .get() pattern in transform_equity_data.py:142",
        "time_to_fix_minutes": 18,
        "engineer": "Jimmy Chen",
        "impact_avoided": 50000,
        "status": "closed",
    },
    {
        "id": "CAMP-891",
        "service": "bloomberg",
        "date": "2025-01-08",
        "error": "ConnectionTimeout to Bloomberg feed after 30s",
        "root_cause": "Bloomberg endpoint port changed from 8194 to 8196",
        "resolution": "Updated BLOOMBERG_PORT constant and redeployed",
        "time_to_fix_minutes": 45,
        "engineer": "Sarah Kim",
        "impact_avoided": 75000,
        "status": "closed",
    },
    {
        "id": "CAMP-834",
        "service": "teamcity",
        "date": "2024-11-22",
        "error": "AssertionError in risk_calculator_test.py:87",
        "root_cause": "VaR calculation output format changed from float to dict",
        "resolution": "Updated test assertions to use dict['var_95'] key",
        "time_to_fix_minutes": 23,
        "engineer": "Marcus Webb",
        "impact_avoided": 25000,
        "status": "closed",
    },
    {
        "id": "CAMP-812",
        "service": "risk-calculator",
        "date": "2024-10-31",
        "error": "NullPointerException in PortfolioRiskEngine.calculate()",
        "root_cause": "Position feed timeout causes null positions list",
        "resolution": "Added null check with cached positions fallback",
        "time_to_fix_minutes": 67,
        "engineer": "Dr. Alex Chen",
        "impact_avoided": 100000,
        "status": "closed",
    },
    {
        "id": "CAMP-799",
        "service": "price-feed",
        "date": "2024-10-05",
        "error": "DataQualityException: MSFT close price deviation 6.1% > threshold",
        "root_cause": "Reference feed provider data error on MSFT close",
        "resolution": "Switched to backup Refinitiv feed, alerted data team",
        "time_to_fix_minutes": 12,
        "engineer": "Priya Sharma",
        "impact_avoided": 60000,
        "status": "closed",
    },
]

# Realistic log lines per service
LOG_TEMPLATES = {
    "airflow": [
        ("[INFO]", "DAG market_data_ingestion scheduled run started"),
        ("[INFO]", "Fetching Bloomberg equity feed — 847 symbols"),
        ("[INFO]", "Bloomberg feed received — 847 records"),
        ("[INFO]", "Starting transform_equity_data task"),
        ("[ERROR]", "KeyError: 'close_price' in transform_equity_data.py:142"),
        ("[ERROR]", "Task transform_equity_data FAILED — retrying (1/3)"),
        ("[ERROR]", "Task transform_equity_data FAILED — retrying (2/3)"),
        ("[CRITICAL]", "DAG market_data_ingestion FAILED after 3 retries"),
    ],
    "bloomberg": [
        ("[INFO]", "Campbell Compress feed monitor starting"),
        ("[INFO]", "Connecting to Bloomberg feed endpoint 10.0.0.45:8194"),
        ("[WARN]", "Connection attempt 1/5 to Bloomberg feed timed out (10s)"),
        ("[WARN]", "Connection attempt 2/5 to Bloomberg feed timed out (10s)"),
        ("[WARN]", "Connection attempt 3/5 to Bloomberg feed timed out (10s)"),
        ("[ERROR]", "All connection attempts exhausted — Bloomberg feed OFFLINE"),
        ("[CRITICAL]", "ConnectionError: Bloomberg feed unreachable after 30s"),
    ],
    "teamcity": [
        ("[INFO]", "Build risk_model_pipeline #4821 triggered"),
        ("[INFO]", "Installing Python dependencies..."),
        ("[INFO]", "Running test suite: risk_calculator_test.py"),
        ("[INFO]", "test_portfolio_risk_sharpe_ratio ... PASSED"),
        ("[INFO]", "test_portfolio_risk_beta ... PASSED"),
        ("[ERROR]", "test_portfolio_risk_var_calculation ... FAILED"),
        ("[ERROR]", "AssertionError: assert {'var_95': 0.0234, ...} == 0.0234"),
        ("[CRITICAL]", "Build FAILED: 1 test failure in risk_calculator_test.py:87"),
    ],
    "risk-calculator": [
        ("[INFO]", "PortfolioRiskEngine starting daily calculation run"),
        ("[INFO]", "Connecting to position feed service..."),
        ("[WARN]", "Position feed service slow to respond (2.1s)"),
        ("[ERROR]", "Position feed timeout after 30s — positions is null"),
        ("[ERROR]", "NullPointerException at PortfolioRiskEngine.java:234"),
        ("[CRITICAL]", "Risk calculation ABORTED — null positions"),
        (
            "[CRITICAL]",
            "REGULATORY ALERT: Risk engine offline — compliance notification required",
        ),
    ],
    "price-feed": [
        ("[INFO]", "Price feed validator started for market close"),
        ("[INFO]", "Validating 1,247 equity close prices"),
        ("[INFO]", "MSFT: $387.42 ✓  (deviation: 0.3%)"),
        ("[INFO]", "GOOGL: $178.91 ✓  (deviation: 0.1%)"),
        ("[WARN]", "AAPL: deviation approaching threshold (4.2%)"),
        (
            "[ERROR]",
            "AAPL: $184.22 vs reference $172.45 — deviation 7.3% > 5% threshold",
        ),
        ("[CRITICAL]", "DataQualityException raised for AAPL — halting downstream"),
    ],
}

FILE_CONTENTS = {
    "transform_equity_data.py": """# Market Data Transform — Bloomberg Equity Feed
import pandas as pd
from datetime import datetime

BLOOMBERG_FIELD_MAP = {
    'open': 'open_price',
    'high': 'high_price',
    'low': 'low_price',
    # Bloomberg field rename: was 'close_price', now 'closing_price'
}

def transform_equity_data(raw_records: list) -> list:
    transformed = []
    for row in raw_records:
        data = {
            'ticker': row['ticker'],
            'date': row['trade_date'],
            'open': row['open_price'],
            'high': row['high_price'],
            'low': row['low_price'],
        }
        # LINE 142 — Bloomberg renamed this field in v4.2 API
        data['close'] = row['close_price']  # KeyError here
        data['volume'] = row.get('volume', 0)
        transformed.append(data)
    return transformed
""",
    "bloomberg_feed_client.py": """# Campbell Compress — Bloomberg Feed Client
import socket
import logging

BLOOMBERG_HOST = '10.0.0.45'
BLOOMBERG_PORT = 8194  # LINE 12 — deprecated, use 8196
BLOOMBERG_TIMEOUT = 30
RECONNECT_ATTEMPTS = 5

log = logging.getLogger(__name__)

def connect():
    for attempt in range(1, RECONNECT_ATTEMPTS + 1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(BLOOMBERG_TIMEOUT)
            sock.connect((BLOOMBERG_HOST, BLOOMBERG_PORT))
            log.info(f"Connected to Bloomberg feed {BLOOMBERG_HOST}:{BLOOMBERG_PORT}")
            return sock
        except socket.timeout:
            log.warning(f"Connection attempt {attempt}/{RECONNECT_ATTEMPTS} timed out")
    raise ConnectionError(f"Bloomberg feed {BLOOMBERG_HOST}:{BLOOMBERG_PORT} unreachable after {BLOOMBERG_TIMEOUT}s")
""",
    "risk_calculator_test.py": """# Risk Calculator Test Suite
import pytest
from risk_engine import PortfolioRiskEngine, calculate_var

TEST_PORTFOLIO = [
    {'ticker': 'AAPL', 'weight': 0.25, 'position': 10000},
    {'ticker': 'MSFT', 'weight': 0.30, 'position': 15000},
    {'ticker': 'GOOGL', 'weight': 0.20, 'position': 8000},
    {'ticker': 'AMZN', 'weight': 0.25, 'position': 12000},
]

def test_portfolio_risk_sharpe_ratio():
    result = calculate_sharpe(TEST_PORTFOLIO)
    assert result > 0

def test_portfolio_risk_beta():
    result = calculate_beta(TEST_PORTFOLIO)
    assert 0.5 <= result <= 2.0

def test_portfolio_risk_var_calculation():
    result = calculate_var(TEST_PORTFOLIO)
    # LINE 87 — VaR now returns dict since Q4 2024 enhancement
    assert result == 0.0234  # Should be: assert result['var_95'] == 0.0234
""",
}


# ─────────────────────────── DB helpers ───────────────────────────
def get_db():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def db_execute(sql: str, params=None, fetch=False):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            if fetch:
                return cur.fetchall()
            conn.commit()


def log_audit(
    event_type: str,
    details: Dict,
    service: Optional[str] = None,
    incident_id: Optional[str] = None,
    source: str = "system",
    actor: Optional[str] = None,
    status: str = "success",
    duration_ms: Optional[int] = None,
):
    try:
        db_execute(
            """INSERT INTO campbell_audit(event_type, service, incident_id, source, actor, details, status, duration_ms)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                event_type,
                service,
                incident_id,
                source,
                actor,
                json.dumps(details),
                status,
                duration_ms,
            ],
        )
    except Exception as e:
        log.warning(f"Audit log failed: {e}")


# ─────────────────────────── SSE broadcast ───────────────────────────
async def broadcast(event_type: str, data: Dict):
    msg = {"type": event_type, "data": data, "ts": datetime.utcnow().isoformat()}
    dead = []
    for q in sse_subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            sse_subscribers.remove(q)
        except ValueError:
            pass


async def broadcast_log(service: str, level: str, message: str):
    entry = {
        "service": service,
        "level": level,
        "message": message,
        "ts": datetime.utcnow().isoformat(),
    }
    log_buffer[service].append(entry)
    if len(log_buffer[service]) > 200:
        log_buffer[service].pop(0)
    await broadcast("log", entry)


# ─────────────────────────── Background tasks ───────────────────────────
async def simulate_log_activity():
    """Continuously emit normal-looking logs for all services."""
    HEALTHY_LOGS = {
        "airflow": [
            ("[INFO]", "DAG scheduler heartbeat OK"),
            ("[INFO]", "DAG market_data_ingestion next run in 4m32s"),
            ("[INFO]", "Bloomberg feed latency: 12ms"),
        ],
        "bloomberg": [
            ("[INFO]", "Feed connection healthy — 847 symbols streaming"),
            ("[INFO]", "Feed latency: 8ms p50 / 22ms p99"),
            ("[INFO]", "Heartbeat OK — 1,247 price updates/sec"),
        ],
        "teamcity": [
            ("[INFO]", "No active builds"),
            ("[INFO]", "Build agent pool: 4/4 agents available"),
        ],
        "risk-calculator": [
            ("[INFO]", "Daily VaR calculation complete — no alerts"),
            ("[INFO]", "Position feed: 2,341 positions loaded"),
            ("[INFO]", "Risk metrics published to downstream consumers"),
        ],
        "price-feed": [
            ("[INFO]", "Validating prices — 1,247 equities"),
            ("[INFO]", "All prices within normal deviation bands"),
            ("[INFO]", "Feed validation complete ✓"),
        ],
    }
    while True:
        await asyncio.sleep(3)
        for svc, logs in HEALTHY_LOGS.items():
            if service_failures[svc] is None:  # Only emit healthy logs when no failure
                level, msg = random.choice(logs)
                await broadcast_log(svc, level, msg)


async def simulate_fix_flow(incident_id: str, service: str):
    """Simulate the fix→build→resolve pipeline."""
    cfg = SERVICES_CONFIG[service]

    await asyncio.sleep(1)
    await broadcast("incident_update", {"id": incident_id, "status": "fixing"})
    db_execute(
        "UPDATE campbell_incidents SET status='fixing', updated_at=NOW() WHERE id=%s",
        [incident_id],
    )

    # Log kaji activity: applying fix
    kaji_msg = f"Applying patch to {cfg['fix_file']} line {cfg['fix_line']}"
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "apply_code_fix",
            json.dumps({"file": cfg["fix_file"], "line": cfg["fix_line"]}),
            kaji_msg,
        ],
    )
    await broadcast("kaji_activity", {"tool": "apply_code_fix", "summary": kaji_msg})
    await broadcast_log(
        service, "[INFO]", f"Applying fix to {cfg['fix_file']} — patch applied"
    )

    await asyncio.sleep(2)
    commit = cfg["commit_hash"]
    await broadcast(
        "build_started",
        {"incident_id": incident_id, "build": cfg["build_name"], "commit": commit},
    )
    await broadcast_log(
        service, "[INFO]", f"Build {cfg['build_name']} triggered — commit {commit}"
    )

    # Simulate build steps
    steps = [
        f"Pulling commit {commit}...",
        "Installing dependencies...",
        "Running unit tests...",
        "All tests passed ✓",
        f"Build {cfg['build_name']} PASSED",
    ]
    for step in steps:
        await asyncio.sleep(1.5)
        await broadcast_log(service, "[INFO]", step)
        await broadcast("build_step", {"incident_id": incident_id, "step": step})

    await asyncio.sleep(1)
    db_execute(
        "UPDATE campbell_incidents SET status='resolved', updated_at=NOW() WHERE id=%s",
        [incident_id],
    )
    service_failures[service] = None
    await broadcast(
        "incident_resolved",
        {
            "id": incident_id,
            "service": service,
            "savings": cfg["impact"],
            "commit": commit,
            "build": cfg["build_name"],
        },
    )
    await broadcast_log(
        service, "[INFO]", f"✅ {service} service restored — all systems operational"
    )

    log_audit(
        "fix_applied",
        {
            "commit": commit,
            "build": cfg["build_name"],
            "savings": cfg["impact"],
            "service": service,
        },
        service=service,
        incident_id=incident_id,
        source="kaji",
        status="success",
    )
    await broadcast(
        "audit",
        {
            "event_type": "fix_applied",
            "service": service,
            "description": f"✅ Fix applied — commit `{commit}` | Build PASSED | ${cfg['impact']:,} saved",
            "source": "Kaji",
            "ts": datetime.utcnow().isoformat(),
        },
    )

    await post_mattermost(
        f"✅ **[{cfg['display']}]** Fix applied — commit `{commit}`\n"
        f"Build: `{cfg['build_name']}` — **PASSED** ✓\n"
        f"Savings: **${cfg['impact']:,}** recovered"
    )


# ─────────────────────────── Mattermost helper ───────────────────────────
async def post_mattermost(message: str, root_id: Optional[str] = None):
    payload: Dict[str, Any] = {"channel_id": MM_CHANNEL_ID, "message": message}
    if root_id:
        payload["root_id"] = root_id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{MM_URL}/api/v4/posts",
                headers={"Authorization": f"Bearer {MM_TOKEN}"},
                json=payload,
            )
            if r.status_code == 201:
                return r.json().get("id")
    except Exception as e:
        log.warning(f"Mattermost post failed: {e}")
    return None


# ─────────────────────────── Pydantic models ───────────────────────────
class InjectRequest(BaseModel):
    service: str


class PatchRequest(BaseModel):
    file: str
    patch: str
    incident_id: Optional[str] = None


class TicketRequest(BaseModel):
    incident_id: str
    assignee: Optional[str] = "Jimmy Chen"


# ─────────────────────────── API routes ───────────────────────────


@app.get("/api/health")
async def health():
    statuses = {}
    for svc in SERVICES_CONFIG:
        failure = service_failures.get(svc)
        statuses[svc] = {
            "healthy": failure is None,
            "display": SERVICES_CONFIG[svc]["display"],
            "icon": SERVICES_CONFIG[svc]["icon"],
            "last_check": datetime.utcnow().isoformat(),
            "error": failure.get("error") if failure else None,
        }
    return {"services": statuses, "ts": datetime.utcnow().isoformat()}


@app.get("/api/logs/{service}")
async def get_logs(service: str, since: str = "1h"):
    if service == "all":
        all_logs = []
        for svc_logs in log_buffer.values():
            all_logs.extend(svc_logs)
        all_logs.sort(key=lambda x: x.get("ts", ""))
        return {"logs": all_logs[-100:]}
    if service not in log_buffer:
        raise HTTPException(404, f"Unknown service: {service}")
    return {"service": service, "logs": log_buffer[service][-50:]}


@app.get("/api/logs/{service}/latest-error")
async def get_latest_error(service: str):
    if service not in SERVICES_CONFIG:
        raise HTTPException(404, f"Unknown service: {service}")
    failure = service_failures.get(service)
    if not failure:
        return {"service": service, "has_error": False}
    cfg = SERVICES_CONFIG[service]
    return {
        "service": service,
        "has_error": True,
        "error": cfg["error"],
        "stack_trace": cfg["stack_trace"],
        "timestamp": failure.get("injected_at"),
        "impact": cfg["impact"],
    }


@app.post("/api/logs/{service}/inject")
async def inject_failure(service: str, bg: BackgroundTasks):
    if service not in SERVICES_CONFIG:
        raise HTTPException(404, f"Unknown service: {service}")
    if service_failures[service] is not None:
        return {"status": "already_failing", "service": service}

    cfg = SERVICES_CONFIG[service]
    ts = datetime.utcnow().isoformat()
    service_failures[service] = {"error": cfg["error"], "injected_at": ts}

    # Emit error logs
    for level, msg in LOG_TEMPLATES.get(service, []):
        log_buffer[service].append(
            {"service": service, "level": level, "message": msg, "ts": ts}
        )
    await broadcast_log(service, "[CRITICAL]", cfg["error"])
    await broadcast(
        "service_failure",
        {"service": service, "error": cfg["error"], "impact": cfg["impact"]},
    )

    # Create incident in Supabase
    row = db_execute(
        """INSERT INTO campbell_incidents(service, error, savings_value, status, mattermost_thread)
           VALUES(%s,%s,%s,'open',%s) RETURNING id""",
        [service, cfg["error"], cfg["impact"], None],
        fetch=True,
    )
    incident_id = str(dict(row[0])["id"]) if row else None

    mm_message = (
        f"🚨 **[{cfg['display']}]** `{cfg['error'][:80]}`\n"
        f"Detected at {ts[:16]} UTC | 💰 **${cfg['impact']:,}** at risk"
    )
    post_id = await post_mattermost(mm_message)
    if incident_id and post_id:
        db_execute(
            "UPDATE campbell_incidents SET mattermost_thread=%s WHERE id=%s",
            [post_id, incident_id],
        )

    log_audit(
        "service_failure",
        {
            "service": service,
            "error": cfg["error"],
            "impact": cfg["impact"],
            "mattermost_post": post_id,
            "incident_id": incident_id,
        },
        service=service,
        incident_id=incident_id,
        source="system",
        actor="monitoring",
        status="detected",
    )

    await broadcast(
        "incident_created",
        {
            "id": incident_id,
            "service": service,
            "error": cfg["error"],
            "impact": cfg["impact"],
            "display": cfg["display"],
            "icon": cfg["icon"],
            "ts": ts,
            "mattermost_thread": post_id,
        },
    )
    await broadcast(
        "audit",
        {
            "event_type": "service_failure",
            "service": service,
            "description": f"🚨 {cfg['display']} failure detected — ${cfg['impact']:,} at risk",
            "source": "Monitoring",
            "ts": ts,
        },
    )
    return {
        "status": "injected",
        "incident_id": incident_id,
        "service": service,
        "mattermost_post": post_id,
    }


@app.get("/api/logs/all/latest-errors")
async def get_all_latest_errors():
    errors = []
    for service, failure in service_failures.items():
        if failure:
            cfg = SERVICES_CONFIG[service]
            errors.append(
                {
                    "service": service,
                    "display": cfg["display"],
                    "error": cfg["error"],
                    "impact": cfg["impact"],
                    "injected_at": failure.get("injected_at"),
                    "has_open_incident": True,
                }
            )
    return {"errors": errors, "count": len(errors), "ts": datetime.utcnow().isoformat()}


WIKIPEDIA_TOPICS = {
    "airflow": ["Apache Airflow", "Extract, transform, load", "Pipeline (computing)"],
    "bloomberg": ["Bloomberg Terminal", "Financial data vendor", "Market data"],
    "teamcity": ["Continuous integration", "Unit testing", "Test automation"],
    "risk-calculator": ["Value at risk", "Market risk", "Financial risk management"],
    "price-feed": ["Market data", "Data quality", "Financial market"],
}


@app.get("/api/public-kb/search")
async def public_kb_search(q: str = "", service: Optional[str] = None):
    results = []
    try:
        search_url = "https://en.wikipedia.org/w/api.php"
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                search_url,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": q,
                    "srlimit": 3,
                    "format": "json",
                    "srprop": "snippet|titlesnippet",
                },
            )
            if r.status_code == 200:
                items = r.json().get("query", {}).get("search", [])
                for item in items:
                    snippet = (
                        item.get("snippet", "")
                        .replace('<span class="searchmatch">', "**")
                        .replace("</span>", "**")
                    )
                    results.append(
                        {
                            "id": item.get("pageid"),
                            "title": item.get("title", ""),
                            "excerpt": snippet[:200],
                            "url": f"https://en.wikipedia.org/wiki/{item.get('title', '').replace(' ', '_')}",
                            "source": "Wikipedia",
                        }
                    )
    except Exception as e:
        log.warning(f"Wikipedia search failed: {e}")
    if service and not results:
        topics = WIKIPEDIA_TOPICS.get(service, [])
        results = [
            {
                "title": t,
                "url": f"https://en.wikipedia.org/wiki/{t.replace(' ', '_')}",
                "source": "Wikipedia",
            }
            for t in topics[:2]
        ]
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "search_public_kb",
            json.dumps({"query": q, "source": "Wikipedia"}),
            f"Wikipedia search: '{q}' → {len(results)} results",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "search_public_kb",
            "summary": f"Wikipedia: '{q}' → {len(results)} results",
        },
    )
    await broadcast(
        "kb_hit",
        {
            "page_id": "wiki",
            "title": f"Wikipedia: {q}",
            "space": "PUBLIC",
            "results": results,
        },
    )
    return {
        "query": q,
        "results": results,
        "source": "Wikipedia",
        "count": len(results),
    }


@app.get("/api/public-kb/article")
async def get_wiki_article(title: str):
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}"
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                result = {
                    "title": data.get("title"),
                    "description": data.get("description", ""),
                    "extract": data.get("extract", "")[:500],
                    "url": data.get("content_urls", {})
                    .get("desktop", {})
                    .get("page", ""),
                    "thumbnail": data.get("thumbnail", {}).get("source", ""),
                    "source": "Wikipedia",
                }
                await broadcast(
                    "kaji_activity",
                    {
                        "tool": "read_public_kb_article",
                        "summary": f"Read Wikipedia: {data.get('title')}",
                    },
                )
                await broadcast(
                    "kb_hit",
                    {
                        "page_id": f"wiki-{title}",
                        "title": data.get("title"),
                        "space": "PUBLIC",
                    },
                )
                return result
    except Exception as e:
        log.warning(f"Wikipedia article failed: {e}")
    raise HTTPException(404, f"Article not found: {title}")


@app.get("/api/confluence/search")
async def confluence_search(q: str = ""):
    results = []
    q_lower = q.lower()
    for page_id, page in CONFLUENCE_PAGES.items():
        if (
            q_lower in page["title"].lower()
            or q_lower in page["content"].lower()
            or q_lower in page_id.lower()
        ):
            excerpt = page["content"][:200].replace("\n", " ")
            results.append(
                {
                    "id": page_id,
                    "title": page["title"],
                    "space": page["space"],
                    "excerpt": excerpt + "...",
                    "author": page["author"],
                    "updated": page["updated"],
                }
            )
    # Log kaji activity
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "search_confluence",
            json.dumps({"query": q}),
            f"Found {len(results)} pages matching '{q}'",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "search_confluence",
            "summary": f"Searched Confluence: '{q}' → {len(results)} results",
            "params": {"q": q},
        },
    )
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/confluence/page/{page_id}")
async def confluence_page(page_id: str):
    page = CONFLUENCE_PAGES.get(page_id)
    if not page:
        raise HTTPException(404, f"Page not found: {page_id}")
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "read_confluence_page",
            json.dumps({"page_id": page_id}),
            f"Read page: {page['title']}",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "read_confluence_page",
            "summary": f"Read: {page['title']}",
            "params": {"page_id": page_id},
        },
    )
    await broadcast(
        "kb_hit", {"page_id": page_id, "title": page["title"], "space": page["space"]}
    )
    return page


@app.get("/api/incidents/history")
async def incidents_history(q: str = ""):
    results = HISTORICAL_INCIDENTS
    if q:
        q_lower = q.lower()
        results = [
            i
            for i in HISTORICAL_INCIDENTS
            if q_lower in i["error"].lower()
            or q_lower in i["root_cause"].lower()
            or q_lower in i["resolution"].lower()
            or q_lower in i["service"].lower()
            or q_lower in i.get("id", "").lower()
        ]
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "search_incident_history",
            json.dumps({"query": q}),
            f"Found {len(results)} historical incidents matching '{q}'",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "search_incident_history",
            "summary": f"Searched incident history: '{q}' → {len(results)} results",
        },
    )
    await broadcast(
        "incident_history_hit", {"query": q, "results": [r["id"] for r in results[:3]]}
    )
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/git/file/{path:path}")
async def git_file(path: str):
    content = FILE_CONTENTS.get(path)
    if not content:
        # Return generic placeholder
        content = f"# {path}\n# Source file not found in demo registry\n"
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        ["read_source_file", json.dumps({"path": path}), f"Read source: {path}"],
    )
    await broadcast(
        "kaji_activity", {"tool": "read_source_file", "summary": f"Read: {path}"}
    )
    return {"path": path, "content": content, "lines": len(content.splitlines())}


@app.post("/api/git/patch")
async def git_patch(req: PatchRequest):
    commit = "".join(random.choices(string.hexdigits[:16], k=7))
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "apply_code_fix",
            json.dumps({"file": req.file, "patch": req.patch[:100]}),
            f"Applied patch to {req.file} — commit {commit}",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "apply_code_fix",
            "summary": f"Applied patch to {req.file}",
            "params": {"file": req.file, "commit": commit},
        },
    )
    return {"commit": commit, "file": req.file, "status": "applied"}


# ─────────────────────────── Incident management ───────────────────────────
@app.get("/api/incidents")
async def list_incidents():
    rows = (
        db_execute(
            "SELECT * FROM campbell_incidents ORDER BY created_at DESC LIMIT 50",
            fetch=True,
        )
        or []
    )
    incidents = []
    for r in rows:
        inc = dict(r)
        svc_key: str = str(inc.get("service") or "")
        cfg = SERVICES_CONFIG.get(svc_key, {})
        inc["display"] = cfg.get("display", str(inc.get("service") or ""))
        inc["icon"] = cfg.get("icon", "⚙️")
        inc["source_file"] = cfg.get("source_file", "")
        inc["source_line"] = cfg.get("source_line", 0)
        inc["source_function"] = cfg.get("source_function", "")
        inc["source_dag"] = cfg.get("source_dag", "")
        inc["notified"] = cfg.get("notified", [])
        inc["resolution_steps"] = cfg.get("resolution_steps", [])
        inc["stack_trace"] = cfg.get("stack_trace", "")
        inc["historical_incident"] = cfg.get("historical_incident", "")
        inc["commit_hash"] = cfg.get("commit_hash", "")
        inc["build_name"] = cfg.get("build_name", "")
        inc["jira_ticket"] = cfg.get("jira_ticket")
        inc["roi_breakdown"] = cfg.get("roi_breakdown")
        inc["related_issues"] = cfg.get("related_issues", [])
        incidents.append(inc)
    return {
        "incidents": incidents,
        "total_savings": sum(
            dict(r)["savings_value"]
            for r in rows
            if dict(r).get("status") == "resolved"
        ),
    }


@app.post("/api/incidents/{incident_id}/diagnose")
async def diagnose_incident(incident_id: str, bg: BackgroundTasks):
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        raise HTTPException(404, "Incident not found")
    inc = dict(row[0])
    service = inc["service"]
    if inc.get("status") not in ("open",):
        return {"status": inc.get("status"), "message": "Already processed"}
    bg.add_task(simulate_diagnosis_flow, incident_id, service)
    return {"status": "diagnosis_started", "incident_id": incident_id}


async def simulate_diagnosis_flow(incident_id: str, service: str):
    cfg = SERVICES_CONFIG.get(service, {})

    def emit_step(step: str, tool: str = ""):
        asyncio.create_task(
            broadcast(
                "diagnosis_step",
                {"incident_id": incident_id, "step": step, "tool": tool},
            )
        )

    await asyncio.sleep(0.5)
    emit_step(f"📋 Reading {cfg.get('display', service)} error logs...", "read_logs")
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "read_logs",
            json.dumps({"service": service}),
            f"Reading {service} logs — confirming error",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "read_logs",
            "summary": f"Confirmed: {cfg.get('error', '')[:80]}",
            "params": {"service": service},
        },
    )
    await asyncio.sleep(1.5)

    emit_step(f"🔍 Searching Confluence: '{service} runbook'...", "search_confluence")
    conf_page = cfg.get("confluence_page", "")
    conf_title = CONFLUENCE_PAGES.get(conf_page, {}).get("title", conf_page)
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "search_confluence",
            json.dumps({"query": f"{service} runbook"}),
            f"Searching Confluence: '{service} runbook'",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "search_confluence",
            "summary": f"Found: {conf_title}",
            "params": {"q": f"{service} runbook"},
        },
    )
    await asyncio.sleep(1.5)

    if conf_page:
        emit_step(f"📚 Reading '{conf_title}'...", "read_confluence_page")
        await broadcast(
            "kb_hit",
            {
                "page_id": conf_page,
                "title": conf_title,
                "space": CONFLUENCE_PAGES.get(conf_page, {}).get("space", "OPS"),
            },
        )
        await broadcast(
            "kaji_activity",
            {"tool": "read_confluence_page", "summary": f"Read: {conf_title}"},
        )
        await asyncio.sleep(1.5)

    await asyncio.sleep(0.8)
    wiki_queries = {
        "airflow": "Apache Airflow ETL pipeline",
        "bloomberg": "Bloomberg Terminal financial data API",
        "teamcity": "continuous integration testing",
        "risk-calculator": "Value at risk portfolio risk management",
        "price-feed": "financial data quality validation",
    }
    wiki_q = wiki_queries.get(service, f"{service} operations")
    emit_step(f"🌐 Searching public KB: '{wiki_q}'...", "search_public_kb")
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            wiki_r = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": wiki_q,
                    "srlimit": 2,
                    "format": "json",
                },
            )
            if wiki_r.status_code == 200:
                for item in wiki_r.json().get("query", {}).get("search", [])[:2]:
                    wiki_title = item.get("title", "")
                    await broadcast(
                        "kb_hit",
                        {
                            "page_id": f"wiki-{item.get('pageid')}",
                            "title": wiki_title,
                            "space": "WIKIPEDIA",
                        },
                    )
                    await broadcast(
                        "kaji_activity",
                        {
                            "tool": "search_public_kb",
                            "summary": f"Wikipedia: {wiki_title}",
                        },
                    )
    except Exception as e:
        log.warning(f"Wikipedia step failed: {e}")
    await asyncio.sleep(1)

    hist = cfg.get("historical_incident", "")
    if hist:
        emit_step(
            f"🕰 Cross-referencing incident history: {hist}...",
            "search_incident_history",
        )
        await broadcast("incident_history_hit", {"results": [hist], "query": service})
        await broadcast(
            "kaji_activity",
            {
                "tool": "search_incident_history",
                "summary": f"Found: {hist} — identical issue, {next((i.get('time_to_fix_minutes') for i in HISTORICAL_INCIDENTS if i.get('id') == hist), '?')} min fix",
            },
        )
        await asyncio.sleep(1.5)

    emit_step(
        f"📝 Reading source: {cfg.get('source_file', '')}:{cfg.get('source_line', '')}...",
        "read_source_file",
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "read_source_file",
            "summary": f"Read {cfg.get('source_file', '')}:{cfg.get('source_line', '')} — found the failing accessor",
        },
    )
    await asyncio.sleep(1.2)

    emit_step("🧠 Generating fix patch...", "generate_patch")
    await broadcast(
        "kaji_activity",
        {
            "tool": "generate_patch",
            "summary": f"Patch generated for {cfg.get('fix_file', '')}",
        },
    )
    await asyncio.sleep(1)

    diagnosis = cfg.get("root_cause", "Unknown root cause")
    diff = cfg.get("fix_diff", "")
    db_execute(
        "UPDATE campbell_incidents SET status='diagnosed', diagnosis=%s, code_diff=%s, updated_at=NOW() WHERE id=%s",
        [diagnosis, diff, incident_id],
    )
    await broadcast(
        "incident_diagnosed",
        {
            "id": incident_id,
            "service": service,
            "diagnosis": diagnosis,
            "code_diff": diff,
            "confluence_page": conf_page,
            "historical_incident": hist,
        },
    )
    emit_step("✅ Diagnosis complete — ready for human review", "complete")
    await broadcast(
        "kaji_activity",
        {"tool": "diagnose_complete", "summary": f"{service}: {diagnosis[:100]}"},
    )


@app.post("/api/incidents/{incident_id}/apply-fix")
async def apply_fix(incident_id: str, bg: BackgroundTasks):
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        raise HTTPException(404, "Incident not found")
    inc = dict(row[0])
    service = inc["service"]
    if inc.get("status") in ("resolved",):
        return {"status": "already_resolved"}
    bg.add_task(simulate_fix_flow, incident_id, service)
    return {"status": "fix_started", "incident_id": incident_id}


@app.post("/api/incidents/{incident_id}/request-review")
async def request_review(incident_id: str):
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        raise HTTPException(404, "Incident not found")
    inc = dict(row[0])
    service = inc["service"]
    cfg = SERVICES_CONFIG.get(service, {})
    approve_url = f"{DEMO_URL}/approve/{incident_id}"
    reject_url = f"{DEMO_URL}/reject/{incident_id}"
    diff_text = cfg.get("fix_diff", "no diff available")
    review_text = (
        f"🔍 **Code Review Required — {cfg.get('display', service)}**\n\n"
        f"**Error**: `{cfg.get('error', '')[:80]}`\n"
        f"**File**: `{cfg.get('source_file', '')}:{cfg.get('source_line', '')}`\n"
        f"**Root Cause**: {cfg.get('root_cause', '')[:200]}\n\n"
        f"```diff\n{diff_text}\n```\n\n"
        f"💰 **${cfg.get('impact', 0):,}** at risk | Risk: ⚠️ High — Production trading infrastructure\n"
        f"Ref: **{cfg.get('historical_incident', 'N/A')}**\n\n"
        f"---\n"
        f"**[✅ Approve & Apply]({approve_url})** · **[❌ Reject — Retry]({reject_url})**\n\n"
        f'_"Kaji finds the fix. You hold the key. Nobody touched a server without sign-off."_'
    )
    msg_payload: Dict[str, Any] = {
        "channel_id": MM_CHANNEL_ID,
        "message": review_text,
        "props": {
            "attachments": [
                {
                    "color": "#C9A84C",
                    "fallback": f"Code review required for {service} incident",
                    "fields": [
                        {
                            "title": "Service",
                            "value": cfg.get("display", service),
                            "short": True,
                        },
                        {
                            "title": "File:Line",
                            "value": f"`{cfg.get('source_file', '')}:{cfg.get('source_line', '')}`",
                            "short": True,
                        },
                        {
                            "title": "Business Impact",
                            "value": f"💰 **${cfg.get('impact', 0):,}** at risk",
                            "short": True,
                        },
                        {
                            "title": "Historical Ref",
                            "value": cfg.get("historical_incident", "N/A"),
                            "short": True,
                        },
                    ],
                    "actions": [
                        {
                            "id": "approve",
                            "name": "✅ Approve & Apply",
                            "type": "button",
                            "style": "good",
                            "integration": {
                                "url": approve_url,
                                "context": {
                                    "incident_id": incident_id,
                                    "action": "approve",
                                    "service": service,
                                },
                            },
                        },
                        {
                            "id": "reject",
                            "name": "❌ Reject — Retry",
                            "type": "button",
                            "style": "danger",
                            "integration": {
                                "url": reject_url,
                                "context": {
                                    "incident_id": incident_id,
                                    "action": "reject",
                                    "service": service,
                                },
                            },
                        },
                    ],
                }
            ]
        },
    }
    post_id = None
    n8n_execution_id = None
    n8n_wf3_url = "http://n8n-v2.hyperplane-n8n-v2.svc.cluster.local:80/webhook-test/campbell-code-review"
    n8n_payload = {
        "incident_id": incident_id,
        "service": service,
        "display": cfg.get("display", service),
        "error": cfg.get("error", ""),
        "impact": cfg.get("impact", 0),
        "root_cause": cfg.get("root_cause", ""),
        "fix_diff": cfg.get("fix_diff", ""),
        "source_file": cfg.get("source_file", ""),
        "source_line": cfg.get("source_line", ""),
        "historical_incident": cfg.get("historical_incident", ""),
        "approve_url": approve_url,
        "reject_url": reject_url,
    }
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            n8n_r = await client.post(n8n_wf3_url, json=n8n_payload)
            if n8n_r.status_code in (200, 201):
                n8n_execution_id = str(n8n_r.json().get("executionId", ""))
                log_audit(
                    "n8n_wf3_triggered",
                    {"execution_id": n8n_execution_id},
                    source="n8n",
                    incident_id=incident_id,
                )
                await broadcast(
                    "audit",
                    {
                        "event_type": "n8n_wf3_triggered",
                        "description": f"n8n WF3 triggered for {cfg.get('display', service)}",
                        "source": "n8n",
                        "ts": datetime.utcnow().isoformat(),
                    },
                )
    except Exception as e:
        log.warning(f"n8n WF3 trigger failed (using direct MM): {e}")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{MM_URL}/api/v4/posts",
                headers={"Authorization": f"Bearer {MM_TOKEN}"},
                json=msg_payload,
            )
            if r.status_code == 201:
                post_id = r.json().get("id")
    except Exception as e:
        log.warning(f"Review request MM post failed: {e}")
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "request_human_review",
            json.dumps({"service": service, "incident_id": incident_id}),
            f"Code review sent to #campbell-ops-alerts — awaiting approval from ops team",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "request_human_review",
            "summary": f"Code review pending: {cfg.get('display', service)} — waiting for ops team sign-off",
        },
    )
    await broadcast("incident_update", {"id": incident_id, "status": "review_pending"})
    db_execute(
        "UPDATE campbell_incidents SET status='review_pending', updated_at=NOW() WHERE id=%s",
        [incident_id],
    )
    return {
        "status": "review_requested",
        "mattermost_post": post_id,
        "n8n_execution": n8n_execution_id,
    }


@app.post("/api/webhooks/approve/{incident_id}")
async def webhook_approve(incident_id: str, request: Request, bg: BackgroundTasks):
    try:
        body = await request.json()
        user_name = body.get("user_name", "ops-team")
        user_id = body.get("user_id", "")
    except Exception:
        user_name = "ops-team"
        user_id = ""
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        return JSONResponse({"ephemeral_text": "Incident not found"})
    inc = dict(row[0])
    service = inc["service"]
    cfg = SERVICES_CONFIG.get(service, {})
    commit = cfg.get("commit_hash", "auto")
    log_audit(
        "mm_button_approve",
        {
            "user_name": user_name,
            "user_id": user_id,
            "commit": commit,
            "service": service,
        },
        service=service,
        incident_id=incident_id,
        source="mattermost",
        actor=user_name,
    )
    await broadcast(
        "audit",
        {
            "event_type": "mm_button_approve",
            "service": service,
            "description": f"✅ @{user_name} clicked Approve in Mattermost — applying fix",
            "source": "Mattermost",
            "actor": user_name,
            "ts": datetime.utcnow().isoformat(),
        },
    )
    await post_mattermost(
        f"✅ **Fix approved by @{user_name}**\n"
        f"Applying to `{cfg.get('fix_file', '')}` — commit `{commit}` → build starting...\n"
        f'_"Detected, diagnosed, fixed, CI verified. One button. The engineer didn\'t write a line of code."_'
    )
    bg.add_task(simulate_fix_flow, incident_id, service)
    return JSONResponse(
        {
            "ephemeral_text": "✅ Approved! Fix is being applied. Check #campbell-ops-alerts for build status."
        }
    )


@app.post("/api/webhooks/reject/{incident_id}")
async def webhook_reject(incident_id: str, request: Request):
    try:
        body = await request.json()
        user_name = body.get("user_name", "ops-team")
    except Exception:
        user_name = "ops-team"
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if row:
        db_execute(
            "UPDATE campbell_incidents SET status='diagnosed', updated_at=NOW() WHERE id=%s",
            [incident_id],
        )
    await post_mattermost(
        f"❌ **Fix rejected by @{user_name}**\n"
        f"@kaji — please suggest an alternative approach for this incident."
    )
    await broadcast("incident_update", {"id": incident_id, "status": "diagnosed"})
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "fix_rejected",
            json.dumps({"incident_id": incident_id}),
            f"Fix rejected by {user_name} — rediagnosing",
        ],
    )
    await broadcast(
        "kaji_activity",
        {
            "tool": "fix_rejected",
            "summary": f"Fix rejected by {user_name} — will retry with alternative approach",
        },
    )
    log_audit(
        "mm_button_reject",
        {"user_name": user_name, "incident_id": incident_id},
        incident_id=incident_id,
        source="mattermost",
        actor=user_name,
    )
    await broadcast(
        "audit",
        {
            "event_type": "mm_button_reject",
            "description": f"❌ @{user_name} rejected fix in Mattermost — Kaji will retry",
            "source": "Mattermost",
            "actor": user_name,
            "ts": datetime.utcnow().isoformat(),
        },
    )
    return JSONResponse(
        {"ephemeral_text": "Fix rejected. Kaji will retry with a different approach."}
    )


@app.post("/api/incidents/{incident_id}/create-ticket")
async def create_ticket(incident_id: str, req: TicketRequest):
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        raise HTTPException(404, "Incident not found")
    inc = dict(row[0])
    service = inc["service"]
    cfg = SERVICES_CONFIG.get(service, {})

    # Create real ClickUp ticket
    ticket_url = None
    assignee = req.assignee if req and req.assignee else "Jimmy Chen"
    ticket_name = f"🚨 [{cfg.get('display', service)}] {cfg.get('error', '')[:60]}"
    md_desc = (
        f"## Campbell Ops Co-Pilot — Auto-Generated Incident\n\n"
        f"**Service**: {cfg.get('display', service)}  \n"
        f"**Error**: `{cfg.get('error', '')}`  \n"
        f"**File**: `{cfg.get('source_file', '')}:{cfg.get('source_line', '')}`  \n"
        f"**Root Cause**: {cfg.get('root_cause', '')}  \n"
        f"**Business Impact**: ${cfg.get('impact', 0):,} at risk  \n"
        f"**Historical Ref**: {cfg.get('historical_incident', 'N/A')}  \n\n"
        f"### Kaji Fix\n```diff\n{cfg.get('fix_diff', '')}\n```\n\n"
        f"**Commit**: `{cfg.get('commit_hash', '')}`  \n"
        f"**Build**: `{cfg.get('build_name', '')}` — PASSED ✓  \n\n"
        f"*Created automatically by Kaji via [Campbell Ops Co-Pilot]({DEMO_URL})*"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.clickup.com/api/v2/list/{CLICKUP_LIST_ID}/task",
                headers={
                    "Authorization": CLICKUP_TOKEN,
                    "Content-Type": "application/json",
                },
                json={
                    "name": ticket_name,
                    "markdown_description": md_desc,
                    "priority": 2,
                    "status": "to do",
                    "tags": ["campbell-ops", "kaji", service],
                },
            )
            if r.status_code in (200, 201):
                data = r.json()
                ticket_url = (
                    data.get("url") or f"https://app.clickup.com/t/{data.get('id')}"
                )
                log.info(f"ClickUp ticket created: {ticket_url}")
    except Exception as e:
        log.warning(f"ClickUp ticket creation failed: {e}")

    if not ticket_url:
        ticket_url = f"https://app.clickup.com/90131266176/v/l/901320600795"

    if ticket_url:
        db_execute(
            "UPDATE campbell_incidents SET clickup_url=%s, updated_at=NOW() WHERE id=%s",
            [ticket_url, incident_id],
        )
        await broadcast(
            "ticket_created",
            {"incident_id": incident_id, "url": ticket_url, "name": ticket_name},
        )
        await broadcast(
            "kaji_activity",
            {
                "tool": "create_clickup_ticket",
                "summary": f"Created ticket: {ticket_name}",
                "url": ticket_url,
            },
        )

    return {"status": "created", "url": ticket_url, "name": ticket_name}


# ─────────────────────────── Kaji activity ───────────────────────────
@app.get("/api/kaji-activity")
async def get_kaji_activity():
    rows = (
        db_execute(
            "SELECT * FROM campbell_kaji_activity ORDER BY timestamp DESC LIMIT 50",
            fetch=True,
        )
        or []
    )
    return {"activity": [dict(r) for r in rows]}


@app.post("/api/incidents/{incident_id}/scan-related")
async def scan_related_issues(incident_id: str):
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        raise HTTPException(404, "Incident not found")
    inc = dict(row[0])
    service = inc["service"]
    cfg = SERVICES_CONFIG.get(service, {})
    related = cfg.get("related_issues", [])
    summary = f"Scanned codebase for issues related to {cfg.get('source_file', '')}:{cfg.get('source_line', '')} — found {len(related)} related tickets"
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [
            "scan_related_issues",
            json.dumps({"service": service, "file": cfg.get("source_file")}),
            summary,
        ],
    )
    await broadcast(
        "kaji_activity", {"tool": "scan_related_issues", "summary": summary}
    )
    await broadcast(
        "feed_scan",
        {
            "incident_id": incident_id,
            "service": service,
            "related": related,
            "count": len(related),
        },
    )
    return {
        "incident_id": incident_id,
        "related_issues": related,
        "count": len(related),
        "summary": summary,
    }


@app.post("/api/kaji-activity")
async def post_kaji_activity(data: Dict):
    tool = data.get("tool", "unknown")
    summary = data.get("summary", "")
    params = data.get("params", {})
    db_execute(
        "INSERT INTO campbell_kaji_activity(tool, params, summary) VALUES(%s,%s,%s)",
        [tool, json.dumps(params), summary],
    )
    await broadcast("kaji_activity", {"tool": tool, "summary": summary})
    return {"status": "logged"}


@app.get("/api/audit")
async def get_audit(limit: int = 100, event_type: Optional[str] = None):
    where = "WHERE 1=1"
    params: List = []
    if event_type:
        where += " AND event_type = %s"
        params.append(event_type)
    rows = (
        db_execute(
            f"SELECT * FROM campbell_audit {where} ORDER BY timestamp DESC LIMIT %s",
            params + [limit],
            fetch=True,
        )
        or []
    )
    return {"audit": [dict(r) for r in rows], "count": len(rows)}


@app.post("/api/audit/log")
async def post_audit(data: Dict):
    log_audit(
        event_type=data.get("event_type", "external"),
        details=data.get("details", {}),
        service=data.get("service"),
        incident_id=data.get("incident_id"),
        source=data.get("source", "external"),
        actor=data.get("actor"),
        status=data.get("status", "success"),
    )
    await broadcast(
        "audit",
        {
            "event_type": data.get("event_type"),
            "source": data.get("source"),
            "description": data.get("details", {}).get("summary", ""),
            "ts": datetime.utcnow().isoformat(),
        },
    )
    return {"status": "logged"}


@app.post("/api/admin/n8n-config")
async def set_n8n_config(data: Dict):
    global N8N_WF3_WEBHOOK
    wf3_url = data.get("wf3_webhook_url", "")
    if wf3_url:
        N8N_WF3_WEBHOOK = wf3_url
        log_audit("n8n_configured", {"wf3_webhook_url": wf3_url}, source="admin")
        await broadcast(
            "audit",
            {
                "event_type": "n8n_configured",
                "description": f"WF3 webhook set: {wf3_url}",
                "source": "Admin",
                "ts": datetime.utcnow().isoformat(),
            },
        )
    return {"status": "ok", "wf3_webhook_url": N8N_WF3_WEBHOOK}


@app.get("/api/admin/n8n-config")
async def get_n8n_config():
    return {
        "wf3_webhook_url": N8N_WF3_WEBHOOK,
        "n8n_ui": "https://n8n-v2.dev.hyperplane.dev",
    }


# ─────────────────────────── SSE stream ───────────────────────────
@app.get("/api/stream")
async def event_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    sse_subscribers.append(q)

    async def generate():
        try:
            # Send initial state
            yield f"data: {json.dumps({'type': 'connected', 'ts': datetime.utcnow().isoformat()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(msg, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            try:
                sse_subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────── Demo control endpoints ───────────────────────────
@app.post("/api/demo/reset")
async def demo_reset():
    """Reset all incidents and service failures for a fresh demo run."""
    for svc in service_failures:
        service_failures[svc] = None
    for svc in log_buffer:
        log_buffer[svc].clear()
    db_execute("DELETE FROM campbell_incidents")
    db_execute("DELETE FROM campbell_kaji_activity")
    await broadcast("demo_reset", {"ts": datetime.utcnow().isoformat()})
    return {"status": "reset"}


@app.post("/api/demo/simulate-random")
async def simulate_random(bg: BackgroundTasks):
    healthy = [svc for svc, f in service_failures.items() if f is None]
    if not healthy:
        return {
            "status": "all_failing",
            "message": "All services already have active failures",
        }

    chosen = None
    reason = ""
    try:
        if ANTHROPIC_KEY:
            import httpx as _httpx

            services_context = "\n".join(
                f"- {k}: {SERVICES_CONFIG[k]['display']} (impact ${SERVICES_CONFIG[k]['impact']:,})"
                for k in healthy
            )
            prompt = (
                f"You are an ops simulation AI for Campbell & Company, a quantitative trading firm.\n"
                f"Available healthy services to simulate a failure on:\n{services_context}\n\n"
                f"Pick the MOST INTERESTING and REALISTIC failure to simulate right now for a live demo.\n"
                f"Consider: business impact, demo flow variety, narrative fit for a trading firm.\n"
                f"Respond with ONLY the service key (one of: {', '.join(healthy)}) and a one-sentence reason.\n"
                f"Format: <service_key>|<reason>"
            )
            async with _httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 64,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code == 200:
                    text = resp.json().get("content", [{}])[0].get("text", "").strip()
                    if "|" in text:
                        parts = text.split("|", 1)
                        candidate = parts[0].strip().lower()
                        if candidate in healthy:
                            chosen = candidate
                            reason = parts[1].strip()
    except Exception as e:
        log.warning(f"AI simulate-random failed, falling back to random: {e}")

    if not chosen:
        import random

        chosen = random.choice(healthy)
        reason = f"Simulating {SERVICES_CONFIG[chosen]['display']} failure — ${SERVICES_CONFIG[chosen]['impact']:,} at risk"

    await broadcast(
        "kaji_activity",
        {
            "tool": "simulate_random",
            "summary": f"AI selected: {SERVICES_CONFIG[chosen]['display']} — {reason}",
        },
    )

    ts = datetime.utcnow().isoformat()
    cfg = SERVICES_CONFIG[chosen]
    service_failures[chosen] = {"error": cfg["error"], "injected_at": ts}
    for level, msg in LOG_TEMPLATES.get(chosen, []):
        log_buffer[chosen].append(
            {"service": chosen, "level": level, "message": msg, "ts": ts}
        )
    await broadcast_log(chosen, "[CRITICAL]", cfg["error"])
    await broadcast(
        "service_failure",
        {
            "service": chosen,
            "error": cfg["error"],
            "impact": cfg["impact"],
            "ai_reason": reason,
        },
    )

    row = db_execute(
        """INSERT INTO campbell_incidents(service, error, savings_value, status, mattermost_thread)
           VALUES(%s,%s,%s,'open',%s) RETURNING id""",
        [chosen, cfg["error"], cfg["impact"], None],
        fetch=True,
    )
    incident_id = str(dict(row[0])["id"]) if row else None
    mm_message = (
        f"🎲 **[AI Simulation]** {cfg['display']}\n"
        f"`{cfg['error'][:80]}`\n"
        f"💰 **${cfg['impact']:,}** at risk | _Reason: {reason}_"
    )
    post_id = await post_mattermost(mm_message)
    if incident_id and post_id:
        db_execute(
            "UPDATE campbell_incidents SET mattermost_thread=%s WHERE id=%s",
            [post_id, incident_id],
        )

    await broadcast(
        "incident_created",
        {
            "id": incident_id,
            "service": chosen,
            "error": cfg["error"],
            "impact": cfg["impact"],
            "display": cfg["display"],
            "icon": cfg["icon"],
            "ts": ts,
            "ai_reason": reason,
            "mattermost_thread": post_id,
        },
    )
    return {
        "status": "simulated",
        "service": chosen,
        "reason": reason,
        "incident_id": incident_id,
    }


@app.get("/api/demo/summary")
async def demo_summary():
    rows = (
        db_execute(
            "SELECT status, SUM(savings_value) as total FROM campbell_incidents GROUP BY status",
            fetch=True,
        )
        or []
    )
    rows_d = [dict(r) for r in rows]
    total_savings = sum(r["total"] for r in rows_d if r["status"] == "resolved")
    return {
        "total_savings": total_savings,
        "incidents_by_status": {r["status"]: int(r["total"] or 0) for r in rows_d},
    }


# ─────────────────────────── Static files ───────────────────────────
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=FileResponse)
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/.well-known/skills/campbell-ops/SKILL.md")
async def skill_md():
    skill_path = Path(__file__).parent / "SKILL.md"
    if skill_path.exists():
        return FileResponse(skill_path, media_type="text/markdown")
    raise HTTPException(404, "SKILL.md not found")


@app.get("/approve/{incident_id}", response_class=HTMLResponse)
async def approve_page(incident_id: str, bg: BackgroundTasks):
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        return HTMLResponse(
            "<html><body style='font-family:system-ui;padding:40px;background:#0A1628;color:#E2E8F0'><h2>❌ Incident not found</h2><p>This approval link may have expired.</p></body></html>",
            status_code=404,
        )
    inc = dict(row[0])
    if inc.get("status") in ("resolved",):
        return HTMLResponse(
            f"<html><body style='font-family:system-ui;padding:40px;background:#0A1628;color:#E2E8F0;text-align:center'><div style='max-width:500px;margin:0 auto;padding:40px;background:#112038;border-radius:12px;border:1px solid #1E3A5F'><div style='font-size:3rem;margin-bottom:16px'>✅</div><h2 style='color:#22C55E;margin-bottom:8px'>Already Resolved</h2><p style='color:#94A3B8'>This incident has already been resolved.</p><a href='{DEMO_URL}' style='display:inline-block;margin-top:24px;padding:12px 24px;background:#C9A84C;color:#0A1628;border-radius:6px;text-decoration:none;font-weight:700'>View Dashboard</a></div></body></html>"
        )
    service = inc["service"]
    cfg = SERVICES_CONFIG.get(service, {})
    bg.add_task(simulate_fix_flow, incident_id, service)
    log_audit(
        "mm_button_approve",
        {"incident_id": incident_id, "source": "browser_link"},
        service=service,
        incident_id=incident_id,
        source="mattermost_link",
        actor="Jimmy Chen",
    )
    await broadcast(
        "audit",
        {
            "event_type": "mm_button_approve",
            "description": "✅ Jimmy Chen approved fix via Mattermost link",
            "source": "Mattermost",
            "actor": "Jimmy Chen",
            "ts": datetime.utcnow().isoformat(),
        },
    )
    return HTMLResponse(f"""<html><head><meta http-equiv="refresh" content="3;url={DEMO_URL}"></head>
<body style='font-family:system-ui;padding:40px;background:#0A1628;color:#E2E8F0;text-align:center'>
<div style='max-width:500px;margin:0 auto;padding:40px;background:#112038;border-radius:12px;border:1px solid #22C55E'>
<div style='font-size:3rem;margin-bottom:16px'>✅</div>
<h2 style='color:#22C55E;margin-bottom:8px'>Fix Approved!</h2>
<p style='color:#94A3B8;margin-bottom:4px'>Applying fix to <strong style='color:#E2E8F0'>{cfg.get("display", service)}</strong></p>
<p style='color:#94A3B8;margin-bottom:24px'>Build running... redirecting to dashboard in 3 seconds.</p>
<a href='{DEMO_URL}' style='display:inline-block;padding:12px 24px;background:#C9A84C;color:#0A1628;border-radius:6px;text-decoration:none;font-weight:700'>View Dashboard →</a>
</div></body></html>""")


@app.get("/reject/{incident_id}", response_class=HTMLResponse)
async def reject_page(incident_id: str):
    row = db_execute(
        "SELECT * FROM campbell_incidents WHERE id=%s", [incident_id], fetch=True
    )
    if not row:
        return HTMLResponse(
            "<html><body style='font-family:system-ui;padding:40px'>❌ Incident not found</body></html>",
            status_code=404,
        )
    inc = dict(row[0])
    service = inc["service"]
    db_execute(
        "UPDATE campbell_incidents SET status='diagnosed', updated_at=NOW() WHERE id=%s",
        [incident_id],
    )
    await post_mattermost(
        f"❌ **Fix rejected** — incident back to diagnosed state. @kaji will suggest an alternative approach."
    )
    await broadcast("incident_update", {"id": incident_id, "status": "diagnosed"})
    log_audit(
        "mm_button_reject",
        {"incident_id": incident_id},
        service=service,
        incident_id=incident_id,
        source="mattermost_link",
        actor="Jimmy Chen",
    )
    await broadcast(
        "audit",
        {
            "event_type": "mm_button_reject",
            "description": "❌ Jimmy Chen rejected fix via Mattermost link",
            "source": "Mattermost",
            "actor": "Jimmy Chen",
            "ts": datetime.utcnow().isoformat(),
        },
    )
    return HTMLResponse(f"""<html><head><meta http-equiv="refresh" content="3;url={DEMO_URL}"></head>
<body style='font-family:system-ui;padding:40px;background:#0A1628;color:#E2E8F0;text-align:center'>
<div style='max-width:500px;margin:0 auto;padding:40px;background:#112038;border-radius:12px;border:1px solid #EF4444'>
<div style='font-size:3rem;margin-bottom:16px'>❌</div>
<h2 style='color:#EF4444;margin-bottom:8px'>Fix Rejected</h2>
<p style='color:#94A3B8;margin-bottom:24px'>Kaji will suggest an alternative approach. Redirecting in 3 seconds.</p>
<a href='{DEMO_URL}' style='display:inline-block;padding:12px 24px;background:#C9A84C;color:#0A1628;border-radius:6px;text-decoration:none;font-weight:700'>View Dashboard →</a>
</div></body></html>""")


@app.get("/{path:path}")
async def catch_all(path: str):
    f = STATIC_DIR / path
    if f.exists() and f.is_file():
        return FileResponse(f)
    return FileResponse(STATIC_DIR / "index.html")


# ─────────────────────────── Startup ───────────────────────────
@app.on_event("startup")
async def startup():
    log.info("Campbell Ops Co-Pilot starting...")
    asyncio.create_task(simulate_log_activity())
    asyncio.create_task(setup_n8n_workflows())
    for svc in log_buffer:
        for _level, _msg in LOG_TEMPLATES.get(svc, [])[:3]:
            log_buffer[svc].append(
                {
                    "service": svc,
                    "level": "[INFO]",
                    "message": f"[Startup] Service {svc} healthy",
                    "ts": datetime.utcnow().isoformat(),
                }
            )
    log.info("Campbell Ops Co-Pilot ready on :8787")


async def setup_n8n_workflows():
    await asyncio.sleep(5)
    n8n_internal = os.getenv(
        "N8N_INTERNAL_URL", "http://n8n-v2.hyperplane-n8n-v2.svc.cluster.local:80"
    )
    n8n_key = N8N_KEY
    demo_url = (
        "http://hyperplane-service-1c01c4.hyperplane-pipelines.svc.cluster.local:8787"
    )
    mm_url = MM_URL
    mm_token = MM_TOKEN
    mm_channel = MM_CHANNEL_ID

    watcher_workflow = {
        "name": "Campbell Log Watcher",
        "active": True,
        "nodes": [
            {
                "id": "1",
                "name": "Schedule",
                "type": "n8n-nodes-base.scheduleTrigger",
                "position": [240, 300],
                "parameters": {
                    "rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}
                },
            },
            {
                "id": "2",
                "name": "Get Health",
                "type": "n8n-nodes-base.httpRequest",
                "position": [440, 300],
                "parameters": {
                    "method": "GET",
                    "url": f"{demo_url}/api/health",
                    "responseFormat": "json",
                },
            },
            {
                "id": "3",
                "name": "Get Errors",
                "type": "n8n-nodes-base.httpRequest",
                "position": [640, 300],
                "parameters": {
                    "method": "GET",
                    "url": f"{demo_url}/api/logs/all/latest-errors",
                    "responseFormat": "json",
                },
            },
            {
                "id": "4",
                "name": "Mattermost Alert",
                "type": "n8n-nodes-base.httpRequest",
                "position": [840, 300],
                "parameters": {
                    "method": "POST",
                    "url": f"{mm_url}/api/v4/posts",
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [
                            {"name": "Authorization", "value": f"Bearer {mm_token}"}
                        ]
                    },
                    "sendBody": True,
                    "bodyParameters": {
                        "parameters": [
                            {"name": "channel_id", "value": mm_channel},
                            {
                                "name": "message",
                                "value": "🔍 Campbell Ops Watcher: Checking all services...",
                            },
                        ]
                    },
                },
            },
        ],
        "connections": {
            "Schedule": {
                "main": [[{"node": "Get Health", "type": "main", "index": 0}]]
            },
            "Get Health": {
                "main": [[{"node": "Get Errors", "type": "main", "index": 0}]]
            },
            "Get Errors": {
                "main": [[{"node": "Mattermost Alert", "type": "main", "index": 0}]]
            },
        },
    }

    daily_workflow = {
        "name": "Campbell Daily Ops Digest",
        "active": True,
        "nodes": [
            {
                "id": "1",
                "name": "Schedule 9am",
                "type": "n8n-nodes-base.scheduleTrigger",
                "position": [240, 300],
                "parameters": {
                    "rule": {
                        "interval": [
                            {"field": "cronExpression", "expression": "0 9 * * *"}
                        ]
                    }
                },
            },
            {
                "id": "2",
                "name": "Get Incidents",
                "type": "n8n-nodes-base.httpRequest",
                "position": [440, 300],
                "parameters": {
                    "method": "GET",
                    "url": f"{demo_url}/api/incidents",
                    "responseFormat": "json",
                },
            },
            {
                "id": "3",
                "name": "Daily Digest Post",
                "type": "n8n-nodes-base.httpRequest",
                "position": [640, 300],
                "parameters": {
                    "method": "POST",
                    "url": f"{mm_url}/api/v4/posts",
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [
                            {"name": "Authorization", "value": f"Bearer {mm_token}"}
                        ]
                    },
                    "sendBody": True,
                    "bodyParameters": {
                        "parameters": [
                            {"name": "channel_id", "value": mm_channel},
                            {
                                "name": "message",
                                "value": "📊 **Campbell Daily Ops Digest** — Good morning! Here is your 24-hour ops summary.",
                            },
                        ]
                    },
                },
            },
        ],
        "connections": {
            "Schedule 9am": {
                "main": [[{"node": "Get Incidents", "type": "main", "index": 0}]]
            },
            "Get Incidents": {
                "main": [[{"node": "Daily Digest Post", "type": "main", "index": 0}]]
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for wf in [watcher_workflow, daily_workflow]:
                r = await client.post(
                    f"{n8n_internal}/api/v1/workflows",
                    headers={
                        "X-N8N-API-KEY": n8n_key,
                        "Content-Type": "application/json",
                    },
                    json=wf,
                )
                if r.status_code in (200, 201):
                    log.info(f"n8n workflow created: {wf['name']}")
                else:
                    log.warning(
                        f"n8n workflow creation failed ({r.status_code}): {wf['name']}"
                    )
    except Exception as e:
        log.warning(f"n8n setup skipped: {e}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8787, reload=False)
