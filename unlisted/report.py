"""Plain-language markdown report of where you're listed and what's happening."""
from __future__ import annotations

from collections import Counter
from datetime import date

from .brokers import Broker
from .planner import Outcome
from .scanner import ScanResult
from .store import Store

STATUS_WORDS = {
    "drafted": "drafted, not yet sent",
    "sent": "sent, waiting for the site",
    "pending_user": "waiting on you",
    "overdue": "deadline missed",
    "confirmed": "removed",
    "closed": "closed",
}


def render(store: Store, brokers: list[Broker], outcome: Outcome,
           scan: list[ScanResult] | None = None) -> str:
    names = {b.id: b.name for b in brokers}
    lines = [f"# Privacy sweep — {date.today():%B %d, %Y}", ""]

    listed = store.findings("open", "requested", "relisted")
    removed = store.findings("removed")
    lines += [
        "## At a glance", "",
        f"- **Currently listed on:** {len({f['broker_id'] for f in listed})} site(s)",
        f"- **Confirmed removed from:** {len({f['broker_id'] for f in removed})} site(s)",
        f"- **Came back after removal (ever):** {len(store.relisted_brokers())} site(s)",
        "",
    ]

    if outcome.for_you:
        lines += ["## Needs you", ""] + [f"- [ ] {t}" for t in outcome.for_you] + [""]
    if outcome.done:
        lines += ["## Done automatically this run", ""] + [f"- {t}" for t in outcome.done] + [""]

    if scan:
        counts = Counter(r.label for r in scan)
        lines += ["## This scan", "",
                  f"Checked {len(scan)} sites: {counts['likely']} likely match, "
                  f"{counts['possible']} possible, {counts['blocked']} blocked automated checks, "
                  f"{counts['none']} not found"
                  + (f", {counts['error']} unreachable" if counts["error"] else "") + ".", ""]
        possible = [r for r in scan if r.label == "possible"]
        blocked = [r for r in scan if r.label == "blocked"]
        if possible:
            lines += ["Possible matches (could be a namesake — check, then run "
                      "`unlisted mark <site> confirm-listing` or `dismiss`):", ""]
            lines += [f"- {names.get(r.broker_id, r.broker_id)}: {r.url} "
                      f"(matched: {', '.join(r.match.signals)})" for r in possible] + [""]
        if blocked:
            lines += ["Sites that blocked the automated check — open these yourself:", ""]
            lines += [f"- {names.get(r.broker_id, r.broker_id)}: {r.url}" for r in blocked] + [""]

    reqs = store.requests()
    if reqs:
        lines += ["## Removal requests", "", "| Site | Step | Started | Due | Status |",
                  "|---|---|---|---|---|"]
        for r in reqs:
            lines.append(
                f"| {names.get(r['broker_id'], r['broker_id'])} | {r['kind'].replace('_', ' ')} "
                f"| {r['created_at'][:10]} | {(r['due_at'] or '—')[:10]} "
                f"| {STATUS_WORDS.get(r['status'], r['status'])} |")
        lines.append("")
    return "\n".join(lines)
