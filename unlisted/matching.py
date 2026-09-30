"""Decide whether a fetched page is about *you* rather than a namesake.

The name is required. Every other signal adds confidence; a phone number or
email match is close to conclusive, a city match alone is not.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from .profile import Profile, digits

WEIGHTS = {
    "name": 0.25,
    "city": 0.15,
    "street": 0.25,
    "phone": 0.35,
    "email": 0.35,
    "age": 0.10,
    "relative": 0.15,
}


@dataclass
class Match:
    score: float
    signals: list[str] = field(default_factory=list)

    def label(self, likely: float, possible: float) -> str:
        if self.score >= likely:
            return "likely"
        if self.score >= possible:
            return "possible"
        return "none"


def page_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).lower()


def _has(text: str, phrase: str) -> bool:
    return bool(phrase) and re.search(r"\b" + re.escape(phrase.lower()) + r"\b", text) is not None


def score(profile: Profile, text: str, today_year: int) -> Match:
    signals: list[str] = []
    if not any(_has(text, n) for n in profile.names):
        return Match(0.0)
    signals.append("name")

    if any(_has(text, a.city) for a in profile.addresses if a.city):
        signals.append("city")
    if any(_has(text, a.street) for a in profile.addresses if a.street):
        signals.append("street")

    text_digits = digits(text)
    if any(p in text_digits for p in profile.phone_digits):
        signals.append("phone")
    if any(e.lower() in text for e in profile.emails):
        signals.append("email")

    if profile.birth_year:
        age = today_year - profile.birth_year
        if re.search(rf"\b(age|aged)\s*:?\s*({age - 1}|{age}|{age + 1})\b", text):
            signals.append("age")

    if any(_has(text, r) for r in profile.relatives):
        signals.append("relative")

    return Match(min(1.0, sum(WEIGHTS[s] for s in signals)), signals)
