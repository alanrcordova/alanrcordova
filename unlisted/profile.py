"""Load the user's profile and settings, and derive search variants."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

DEFAULT_SETTINGS = {
    "scan_every_days": 7,
    "discover_every_days": 30,
    "min_likely_score": 0.6,
    "min_possible_score": 0.3,
    "request_delay_seconds": 5,
    "auto_send": False,
    "proactive": True,  # send requests to every registry broker, not only where found
    "auto_open_verify_links": False,
    "smtp": {},
    "imap": {},
    "brave_api_key_env": "BRAVE_API_KEY",
}


def home_dir() -> Path:
    return Path(os.environ.get("UNLISTED_HOME", Path.home() / ".unlisted"))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


@dataclass
class Address:
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""

    def one_line(self) -> str:
        return ", ".join(p for p in (self.street, self.city, f"{self.state} {self.zip}".strip()) if p)


@dataclass
class Profile:
    full_name: str
    contact_email: str
    aliases: list[str] = field(default_factory=list)
    birth_year: int | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    addresses: list[Address] = field(default_factory=list)
    relatives: list[str] = field(default_factory=list)
    california_resident: bool = True
    settings: dict = field(default_factory=dict)

    @property
    def first(self) -> str:
        return self.full_name.split()[0]

    @property
    def last(self) -> str:
        return self.full_name.split()[-1]

    @property
    def names(self) -> list[str]:
        """All name forms to look for: full, first+last, and aliases."""
        forms = [self.full_name, f"{self.first} {self.last}", *self.aliases]
        return list(dict.fromkeys(f for f in forms if f))

    @property
    def phone_digits(self) -> list[str]:
        return [d[-10:] for d in map(digits, self.phones) if len(d) >= 10]

    @property
    def primary_address(self) -> Address:
        return self.addresses[0] if self.addresses else Address()

    def search_vars(self, address: Address | None = None) -> dict[str, str]:
        a = address or self.primary_address
        return {
            "first": slug(self.first),
            "last": slug(self.last),
            "full_slug": slug(self.full_name),
            "city_slug": slug(a.city),
            "state": a.state.upper(),
            "state_name_slug": slug(STATE_NAMES.get(a.state.upper(), a.state)),
            "phone_digits": self.phone_digits[0] if self.phone_digits else "",
        }


def load_profile(path: Path | None = None) -> Profile:
    path = path or home_dir() / "profile.yaml"
    raw = yaml.safe_load(Path(path).read_text()) or {}
    user_settings = {k: v for k, v in (raw.pop("settings", None) or {}).items() if v is not None}
    settings = {**DEFAULT_SETTINGS, **user_settings}
    addresses = [Address(**a) for a in raw.pop("addresses", None) or []]
    if not raw.get("full_name") or not raw.get("contact_email"):
        raise ValueError(f"{path}: full_name and contact_email are required")
    return Profile(addresses=addresses, settings=settings, **raw)
