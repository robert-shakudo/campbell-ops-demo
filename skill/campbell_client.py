#!/usr/bin/env python3
"""
Campbell Ops Co-Pilot — CLI Client

Lets Kaji (or a developer) trigger Campbell Ops API actions from the terminal.
Used by Kaji's bash tool, or for scripting demo scenarios.

Usage:
  python skill/campbell_client.py <command> [options]

Environment:
  CAMPBELL_OPS_URL  Base URL of the Campbell Ops app
                    Default: https://campbell-ops-demo.dev.hyperplane.dev
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error

BASE_URL = os.environ.get(
    "CAMPBELL_OPS_URL", "https://campbell-ops-demo.dev.hyperplane.dev"
).rstrip("/")


def _get(path: str) -> dict:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _post(path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body or {}).encode() if body else b"{}"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _print(data: dict | list, indent: bool = True) -> None:
    print(json.dumps(data, indent=2 if indent else None))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_health(_args) -> None:
    """Check health of all 5 services."""
    result = _get("/api/health")
    services = result.get("services", {})
    print(f"\n{'Service':<22} {'Status':<10} {'Last Checked'}")
    print("-" * 55)
    for name, info in services.items():
        status = info.get("status", "unknown")
        icon = "✅" if status == "healthy" else "🔴"
        ts = info.get("last_checked", "—")
        print(f"{icon} {name:<20} {status:<10} {ts}")
    print()


def cmd_list(_args) -> None:
    """List all active incidents."""
    result = _get("/api/incidents")
    incidents = result.get("incidents", [])
    if not incidents:
        print("No active incidents. All systems healthy.")
        return
    print(f"\n{'ID':<15} {'Service':<18} {'Status':<12} {'Impact'}")
    print("-" * 65)
    for inc in incidents:
        inc_id = inc.get("id", "")[:13]
        service = inc.get("service", "")
        status = inc.get("status", "")
        impact = f"${inc.get('savings_value', 0):,}"
        print(f"{inc_id:<15} {service:<18} {status:<12} {impact}")
    print()


def cmd_inject(args) -> None:
    """Inject a failure into a service."""
    services = ["airflow", "bloomberg", "teamcity", "risk-calculator", "price-feed"]
    if args.service not in services:
        print(f"❌ Unknown service: {args.service}")
        print(f"   Valid services: {', '.join(services)}")
        sys.exit(1)
    print(f"Injecting failure into {args.service}...")
    result = _post(f"/api/logs/{args.service}/inject")
    print(f"✅ {result.get('message', 'Failure injected')}")
    if "incident_id" in result:
        print(f"   Incident ID: {result['incident_id']}")


def cmd_diagnose(args) -> None:
    """Run Kaji diagnosis on an incident."""
    print(f"Running diagnosis on incident {args.id}...")
    result = _post(f"/api/incidents/{args.id}/diagnose")
    diagnosis = result.get("diagnosis", {})
    print(f"\n🔍 Root Cause:\n  {diagnosis.get('root_cause', '—')}")
    print(f"\n📚 Confluence Source:\n  {diagnosis.get('confluence_source', '—')}")
    print(f"\n📁 Historical Ref:\n  {diagnosis.get('historical_ref', '—')}")
    fix = diagnosis.get("recommended_fix", {})
    if fix:
        print(f"\n🔧 Recommended Fix ({fix.get('file', '')}):")
        print(f"  Before: {fix.get('before', '')}")
        print(f"  After:  {fix.get('after', '')}")
    print()


def cmd_fix(args) -> None:
    """Apply the fix for an incident."""
    print(f"Applying fix for incident {args.id}...")
    result = _post(f"/api/incidents/{args.id}/apply-fix")
    print(f"✅ {result.get('message', 'Fix applied')}")
    if "commit_hash" in result:
        print(f"   Commit: {result['commit_hash']}")
    if "savings_value" in result:
        print(f"   Value protected: ${result['savings_value']:,}")


def cmd_ticket(args) -> None:
    """Create a ClickUp ticket for an incident."""
    print(f"Creating ClickUp ticket for incident {args.id}...")
    result = _post(f"/api/incidents/{args.id}/create-ticket")
    print(f"✅ Ticket created: {result.get('ticket_url', result.get('message', ''))}")


def cmd_search_confluence(args) -> None:
    """Search the Confluence knowledge base."""
    result = _get(f"/api/confluence/search?q={args.query}")
    pages = result.get("results", [])
    if not pages:
        print(f"No results for: {args.query}")
        return
    for page in pages:
        print(f"\n📄 {page.get('title', '—')}")
        print(f"   {page.get('excerpt', '')[:200]}")
    print()


def cmd_history(args) -> None:
    """Search historical incident records."""
    result = _get(f"/api/incidents/history?q={args.query}")
    incidents = result.get("results", [])
    if not incidents:
        print(f"No historical incidents found for: {args.query}")
        return
    for inc in incidents:
        print(f"\n🗂  {inc.get('id', '—')} — {inc.get('title', '—')}")
        print(
            f"   Status: {inc.get('status', '—')} | Fix time: {inc.get('time_to_fix_minutes', '—')} min"
        )
        print(f"   Resolution: {inc.get('resolution_summary', '')[:200]}")
    print()


def cmd_reset(_args) -> None:
    """Reset all incidents — returns all services to healthy."""
    print("Resetting demo state...")
    result = _post("/api/demo/reset")
    print(f"✅ {result.get('message', 'Demo reset complete')}")


def cmd_scan(args) -> None:
    """Scan an incident for related code issues."""
    print(f"Scanning for related issues in incident {args.id}...")
    result = _post(f"/api/incidents/{args.id}/scan-related")
    findings = result.get("findings", [])
    if not findings:
        print("No related issues found.")
        return
    for f in findings:
        print(
            f"  🔍 {f.get('file', '')}:{f.get('line', '')} — {f.get('description', '')}"
        )
    print()


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Campbell Ops Co-Pilot — CLI Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="Check health of all 5 services")
    sub.add_parser("list", help="List all active incidents")
    sub.add_parser("reset", help="Reset demo — clear all incidents")

    p_inject = sub.add_parser("inject", help="Inject a failure into a service")
    p_inject.add_argument(
        "service",
        choices=["airflow", "bloomberg", "teamcity", "risk-calculator", "price-feed"],
        help="Service to inject failure into",
    )

    p_diagnose = sub.add_parser("diagnose", help="Run Kaji diagnosis on an incident")
    p_diagnose.add_argument("id", help="Incident ID")

    p_fix = sub.add_parser("fix", help="Apply the fix for an incident")
    p_fix.add_argument("id", help="Incident ID")

    p_ticket = sub.add_parser("ticket", help="Create ClickUp ticket for an incident")
    p_ticket.add_argument("id", help="Incident ID")

    p_scan = sub.add_parser("scan", help="Scan incident for related code issues")
    p_scan.add_argument("id", help="Incident ID")

    p_confluence = sub.add_parser("confluence", help="Search Confluence knowledge base")
    p_confluence.add_argument("query", help="Search query")

    p_history = sub.add_parser("history", help="Search historical incident records")
    p_history.add_argument("query", help="Search query")

    args = parser.parse_args()

    dispatch = {
        "health": cmd_health,
        "list": cmd_list,
        "inject": cmd_inject,
        "diagnose": cmd_diagnose,
        "fix": cmd_fix,
        "ticket": cmd_ticket,
        "scan": cmd_scan,
        "confluence": cmd_search_confluence,
        "history": cmd_history,
        "reset": cmd_reset,
    }

    try:
        dispatch[args.command](args)
    except urllib.error.URLError as e:
        print(f"❌ Connection error: {e}")
        print(f"   Is the app running at {BASE_URL}?")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
