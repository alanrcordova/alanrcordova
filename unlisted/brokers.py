"""Broker registry: where to look and how to opt out."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from .profile import Profile, home_dir


@dataclass
class Broker:
    id: str
    name: str
    category: str
    optout: dict
    search_url: str | None = None
    verify_domains: list[str] = field(default_factory=list)
    relist_days: int = 90
    priority: int = 2
    last_verified: str | None = None

    @property
    def method(self) -> str:
        return self.optout["method"]

    def search_url_for(self, profile: Profile) -> str | None:
        if not self.search_url:
            return None
        return self.search_url.format(**profile.search_vars())


def load_brokers(path: Path | None = None) -> list[Broker]:
    text = Path(path).read_text() if path else (
        resources.files("unlisted.data").joinpath("brokers.yaml").read_text()
    )
    brokers = {b["id"]: Broker(**b) for b in yaml.safe_load(text)["brokers"]}
    if path is None:
        # Your own additions/overrides, e.g. brokers with privacy@ addresses
        # taken from the CPPA data broker registry.
        local = home_dir() / "brokers.local.yaml"
        if local.exists():
            brokers.update({b["id"]: Broker(**b) for b in yaml.safe_load(local.read_text())["brokers"]})
    return sorted(brokers.values(), key=lambda b: (b.priority, b.id))


def broker_for_domain(brokers: list[Broker], domain: str) -> Broker | None:
    domain = domain.lower()
    for b in brokers:
        if any(domain == d or domain.endswith("." + d) for d in b.verify_domains):
            return b
    return None
