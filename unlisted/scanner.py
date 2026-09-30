"""Find where you're listed: registry broker searches plus optional web search."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

import requests

from .brokers import Broker, broker_for_domain
from .matching import Match, page_text, score
from .profile import Profile

USER_AGENT = "Mozilla/5.0 (compatible; unlisted-privacy-check/0.1; personal opt-out tool)"
BLOCKED_STATUSES = {401, 403, 429, 503}


@dataclass
class ScanResult:
    broker_id: str
    url: str
    label: str        # likely | possible | none | blocked | error | discovered
    match: Match | None = None
    detail: str = ""


def fetch(url: str, timeout: int = 20) -> tuple[int, str]:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    return resp.status_code, resp.text


def looks_blocked(status: int, body: str) -> bool:
    if status in BLOCKED_STATUSES:
        return True
    lowered = body[:5000].lower()
    return any(s in lowered for s in ("captcha", "cf-challenge", "are you a human", "access denied"))


def scan_broker(broker: Broker, profile: Profile, fetcher=fetch) -> ScanResult | None:
    url = broker.search_url_for(profile)
    if not url:
        return None
    try:
        status, body = fetcher(url)
    except requests.RequestException as exc:
        return ScanResult(broker.id, url, "error", detail=str(exc))
    if looks_blocked(status, body):
        return ScanResult(broker.id, url, "blocked", detail=f"HTTP {status}")
    s = profile.settings
    m = score(profile, page_text(body), date.today().year)
    return ScanResult(broker.id, url, m.label(s["min_likely_score"], s["min_possible_score"]), m)


def scan_all(brokers: list[Broker], profile: Profile, fetcher=fetch) -> list[ScanResult]:
    results = []
    for broker in brokers:
        result = scan_broker(broker, profile, fetcher)
        if result is not None:
            results.append(result)
            time.sleep(profile.settings["request_delay_seconds"])
    return results


def discover(profile: Profile, brokers: list[Broker]) -> list[ScanResult]:
    """Web-search for pages that mention you, including sites not in the registry.

    Uses the Brave Search API when an API key is configured; otherwise returns
    nothing (discovery is optional).
    """
    key = os.environ.get(profile.settings["brave_api_key_env"])
    if not key:
        return []
    a = profile.primary_address
    queries = [f'"{profile.full_name}" "{a.city}"'] + [f'"{p}"' for p in profile.phones]
    queries += [f'"{e}"' for e in profile.emails]
    results: dict[str, ScanResult] = {}
    for q in queries:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": q, "count": 20},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        for hit in resp.json().get("web", {}).get("results", []):
            url = hit["url"]
            domain = urlparse(url).hostname or ""
            known = broker_for_domain(brokers, domain)
            snippet = f"{hit.get('title', '')} {hit.get('description', '')}".lower()
            m = score(profile, snippet, date.today().year)
            if m.score == 0:
                continue
            results[url] = ScanResult(known.id if known else f"web:{domain}", url, "discovered", m, q)
        time.sleep(1)
    return list(results.values())
