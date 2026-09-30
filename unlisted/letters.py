"""Render removal letters from templates."""
from __future__ import annotations

from datetime import date
from importlib import resources
from string import Template

from .brokers import Broker
from .profile import Profile


def _template(name: str) -> Template:
    return Template(resources.files("unlisted.templates").joinpath(f"{name}.txt").read_text())


def _fields(profile: Profile, broker_name: str, listing_urls: list[str]) -> dict[str, str]:
    listing_block = ""
    if listing_urls:
        listing_block = "\nListing(s) on your site:\n" + "".join(f"  {u}\n" for u in listing_urls)
    return {
        "full_name": profile.full_name,
        "aliases_line": f" (also: {', '.join(profile.aliases)})" if profile.aliases else "",
        "addresses": "; ".join(a.one_line() for a in profile.addresses) or "—",
        "phones": ", ".join(profile.phones) or "—",
        "emails": ", ".join(profile.emails) or "—",
        "contact_email": profile.contact_email,
        "broker_name": broker_name,
        "listing_block": listing_block,
        "date": date.today().strftime("%B %d, %Y"),
    }


def split_subject(text: str) -> tuple[str, str]:
    first, _, body = text.partition("\n")
    return first.removeprefix("Subject:").strip(), body.lstrip("\n")


def removal_request(profile: Profile, broker: Broker, listing_urls: list[str]) -> str:
    name = "ccpa_request" if profile.california_resident else "generic_request"
    return _template(name).substitute(_fields(profile, broker.name, listing_urls))


def follow_up(profile: Profile, broker: Broker, listing_urls: list[str], original_date: str) -> str:
    if not profile.california_resident:
        return removal_request(profile, broker, listing_urls)
    return _template("ccpa_follow_up").substitute(
        _fields(profile, broker.name, listing_urls), original_date=original_date)


def complaint_draft(profile: Profile, broker: Broker, listing_urls: list[str],
                    request_history: str, relisted: bool) -> str:
    relist = ("republished my information after previously removing it."
              if relisted else "continues to display my information.")
    return _template("cppa_complaint").substitute(
        broker_name=broker.name,
        optout_url=broker.optout.get("url") or broker.optout.get("email", "—"),
        request_history=request_history,
        listing_urls=", ".join(listing_urls) or "—",
        relist_sentence=relist,
    )
