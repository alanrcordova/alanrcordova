"""Decide and carry out the next removal step for each broker, and track deadlines."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import letters
from .actions import forms, mailer
from .brokers import Broker
from .profile import Profile
from .store import Store, now

RESPONSE_DAYS = 45      # Civ. Code § 1798.130(a)(2)
FOLLOW_UP_DAYS = 15     # grace period we give after the second notice


@dataclass
class Outcome:
    done: list[str] = field(default_factory=list)       # things the tool did
    for_you: list[str] = field(default_factory=list)    # things that need you


def _listing_urls(store: Store, broker_id: str) -> list[str]:
    return [f["url"] for f in store.findings("open", "relisted", "requested")
            if f["broker_id"] == broker_id and f["label"] in ("likely", "discovered")]


def needs_action(store: Store, broker: Broker, proactive: bool) -> bool:
    if store.open_request(broker.id):
        return False
    if any(f["broker_id"] == broker.id and f["label"] in ("likely", "discovered")
           for f in store.findings("open", "relisted")):
        return True
    confirmed = store.last_confirmed(broker.id)
    if confirmed is None:
        return proactive
    # Brokers whose listings we can't scan get re-requested every relist interval.
    age = now() - datetime.fromisoformat(confirmed["created_at"])
    return not broker.search_url and age > timedelta(days=broker.relist_days)


def act_on_broker(store: Store, profile: Profile, broker: Broker, outbox: Path,
                  interactive: bool, out: Outcome) -> None:
    urls = _listing_urls(store, broker.id)
    text = letters.removal_request(profile, broker, urls)
    subject, body = letters.split_subject(text)
    stem = f"{now():%Y%m%d}-{broker.id}"
    method = broker.method
    url = broker.optout.get("url", "")

    if method == "email":
        msg = mailer.build_message(profile, broker.optout["email"], subject, body)
        path = mailer.write_draft(msg, outbox, stem)
        if profile.settings["auto_send"] and profile.settings["smtp"].get("host"):
            mailer.send(msg, profile.settings["smtp"])
            store.add_request(broker.id, "initial", method, "sent", RESPONSE_DAYS, str(path))
            out.done.append(f"Emailed a removal request to {broker.name}.")
        else:
            store.add_request(broker.id, "initial", method, "drafted", RESPONSE_DAYS, str(path))
            out.for_you.append(f"Send the drafted request to {broker.name}: {path}")

    elif method == "web_form" and interactive and broker.optout.get("recipe"):
        try:
            steps = forms.load_recipe(broker.optout["recipe"])
            values = forms.recipe_vars(profile, url, urls[0] if urls else "")
            receipt = forms.run_recipe(steps, values, outbox / "receipts")
        except forms.RecipeUnavailable as exc:
            return _task(store, broker, outbox, stem, text, urls, out, note=str(exc))
        store.add_request(broker.id, "initial", method, "sent", RESPONSE_DAYS, str(receipt))
        out.done.append(f"Submitted the opt-out form at {broker.name} (receipt: {receipt}).")

    else:
        _task(store, broker, outbox, stem, text, urls, out)

    store.set_finding_status(broker.id, "requested")


def _task(store: Store, broker: Broker, outbox: Path, stem: str, letter: str,
          urls: list[str], out: Outcome, note: str = "") -> None:
    """Record a step that needs you, with everything you need to do it quickly."""
    outbox.mkdir(parents=True, exist_ok=True)
    path = outbox / f"{stem}.txt"
    path.write_text(letter)
    # DROP and account-based tools (e.g. Google) carry no CCPA response deadline.
    due = RESPONSE_DAYS if broker.method in ("email", "web_form") else None
    store.add_request(broker.id, "initial", broker.method, "pending_user", due, str(path), note or None)
    where = broker.optout.get("url", "")
    extra = f" Listing(s): {', '.join(urls)}." if urls else ""
    tips = broker.optout.get("notes", "").strip()
    out.for_you.append(
        f"{broker.name}: open {where} and submit an opt-out.{extra}"
        + (f" Note: {tips}" if tips else "")
        + f" (Request text to paste, if the form has a message box: {path})"
    )


def follow_ups(store: Store, profile: Profile, brokers: dict[str, Broker], outbox: Path,
               out: Outcome) -> None:
    for req in store.overdue_requests():
        broker = brokers.get(req["broker_id"])
        if broker is None:
            continue
        store.set_request_status(req["id"], "overdue")
        urls = _listing_urls(store, broker.id)
        stem = f"{now():%Y%m%d}-{broker.id}"
        if req["kind"] == "initial":
            text = letters.follow_up(profile, broker, urls, req["created_at"][:10])
            subject, body = letters.split_subject(text)
            if broker.method == "email":
                msg = mailer.build_message(profile, broker.optout["email"], subject, body)
                path = mailer.write_draft(msg, outbox, stem + "-followup")
            else:
                path = outbox / f"{stem}-followup.txt"
                path.write_text(text)
            store.add_request(broker.id, "follow_up", broker.method, "pending_user",
                              FOLLOW_UP_DAYS, str(path))
            out.for_you.append(
                f"{broker.name} missed the 45-day deadline. Second notice drafted: {path}")
        elif req["kind"] == "follow_up":
            history = "; ".join(f"{r['kind']} {r['created_at'][:10]}"
                                for r in store.requests() if r["broker_id"] == broker.id)
            relisted = any(f["broker_id"] == broker.id for f in store.findings("relisted"))
            path = outbox / f"{stem}-cppa-complaint.txt"
            path.write_text(letters.complaint_draft(profile, broker, urls, history, relisted))
            store.add_request(broker.id, "complaint_draft", "cppa", "pending_user", None, str(path))
            out.for_you.append(
                f"{broker.name} ignored two requests. A CPPA complaint is drafted for your review: {path}")


def plan_and_act(store: Store, profile: Profile, brokers: list[Broker], outbox: Path,
                 interactive: bool = False) -> Outcome:
    out = Outcome()
    follow_ups(store, profile, {b.id: b for b in brokers}, outbox, out)
    found = {f["broker_id"] for f in store.findings("open", "relisted")}
    for broker in sorted(brokers, key=lambda b: (b.method != "drop", b.id not in found)):
        if needs_action(store, broker, profile.settings["proactive"]):
            act_on_broker(store, profile, broker, outbox, interactive, out)
    # Sites found by web search that aren't in the registry.
    for f in store.findings("open", "relisted"):
        if f["broker_id"].startswith("web:"):
            out.for_you.append(
                f"Review {f['url']} (found by web search, signals: {f['signals']}). "
                "If it's you, look for the site's privacy/removal page, or run "
                f"`unlisted letter {f['broker_id']}` for a request you can send.")
    return out
