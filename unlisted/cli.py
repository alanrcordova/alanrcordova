"""Command line: `unlisted run` is the one to schedule."""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, timedelta
from importlib import resources

import requests

from . import letters, planner, report, scanner
from .brokers import Broker, load_brokers
from .inbox import check_inbox
from .profile import home_dir, load_profile
from .store import Store, iso, now


def _setup():
    home = home_dir()
    profile = load_profile(home / "profile.yaml")
    return home, profile, load_brokers(), Store(home / "state.db")


def record_scan(store: Store, results: list[scanner.ScanResult]) -> None:
    for r in results:
        if r.label in ("likely", "possible", "discovered"):
            store.record_finding(r.broker_id, r.url, r.label, r.match.score, r.match.signals)
        elif r.label == "none":
            store.mark_absent(r.broker_id)


def cmd_init(args) -> None:
    home = home_dir()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = home / "profile.yaml"
    if target.exists():
        print(f"{target} already exists.")
        return
    with resources.as_file(resources.files("unlisted.data").joinpath("profile.example.yaml")) as src:
        shutil.copy(src, target)
    target.chmod(0o600)
    print(f"Created {target}. Fill in your details, then run `unlisted run`.")


def cmd_scan(args) -> None:
    home, profile, brokers, store = _setup()
    results = scanner.scan_all(brokers, profile)
    if args.discover:
        results += scanner.discover(profile, brokers)
    record_scan(store, results)
    for r in results:
        extra = f" [{', '.join(r.match.signals)}]" if r.match and r.match.signals else ""
        print(f"{r.label:10} {r.broker_id:25} {r.url}{extra}")


def cmd_run(args) -> None:
    home, profile, brokers, store = _setup()
    s = profile.settings
    scan: list[scanner.ScanResult] = []
    outcome = planner.Outcome()

    for ev in check_inbox(s["imap"], brokers, s["auto_open_verify_links"]):
        if ev.opened:
            outcome.done.append(f"Opened confirmation link from {ev.broker_id}: {ev.opened[0]}")
        elif ev.verify_links:
            outcome.for_you.append(f"Confirm your opt-out at {ev.broker_id}: {ev.verify_links[0]}")

    if args.force or store.due("scan", s["scan_every_days"]):
        scan = scanner.scan_all(brokers, profile)
        store.mark_run("scan")
    if args.force or store.due("discover", s["discover_every_days"]):
        scan += scanner.discover(profile, brokers)
        store.mark_run("discover")
    record_scan(store, scan)

    acted = planner.plan_and_act(store, profile, brokers, home / "outbox", args.interactive)
    outcome.done += acted.done
    outcome.for_you += acted.for_you

    text = report.render(store, brokers, outcome, scan)
    reports = home / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"{date.today():%Y-%m-%d}.md"
    path.write_text(text)
    print(text)
    print(f"\nReport saved to {path}")


def cmd_status(args) -> None:
    home, profile, brokers, store = _setup()
    print(report.render(store, brokers, planner.Outcome()))


def cmd_mark(args) -> None:
    home, profile, brokers, store = _setup()
    req = store.open_request(args.broker)
    if args.state == "submitted":
        if not req:
            sys.exit(f"No open request for {args.broker}.")
        # The 45-day clock starts when you actually submit.
        due = iso(now() + timedelta(days=planner.RESPONSE_DAYS)) if req["due_at"] else None
        store.db.execute("UPDATE requests SET status='sent', due_at=?, notes='submitted by you'"
                         " WHERE id=?", (due, req["id"]))
        store.db.commit()
    elif args.state == "confirmed":
        store.mark_absent(args.broker)
    elif args.state == "dismiss":
        store.set_finding_status(args.broker, "dismissed")
        if req:
            store.set_request_status(req["id"], "closed")
    elif args.state == "confirm-listing":
        store.db.execute("UPDATE findings SET label='likely' WHERE broker_id=? AND label='possible'",
                         (args.broker,))
        store.db.commit()
    print(f"{args.broker}: marked {args.state}.")


def cmd_letter(args) -> None:
    home, profile, brokers, store = _setup()
    broker = next((b for b in brokers if b.id == args.broker), None)
    if broker is None:  # a site found by web search, or any site you name
        name = args.broker.removeprefix("web:")
        broker = Broker(id=args.broker, name=name, category="other", optout={"method": "email"})
    urls = [f["url"] for f in store.findings() if f["broker_id"] == args.broker]
    print(letters.removal_request(profile, broker, urls))


def cmd_verify_registry(args) -> None:
    for b in load_brokers():
        for url in filter(None, [b.optout.get("url")]):
            try:
                r = requests.get(url, headers={"User-Agent": scanner.USER_AGENT}, timeout=20)
                status = str(r.status_code) + (f" -> {r.url}" if r.url != url else "")
            except requests.RequestException as exc:
                status = f"ERROR {exc.__class__.__name__}"
            print(f"{b.id:25} {status:12} {url}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="unlisted", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create ~/.unlisted/profile.yaml").set_defaults(func=cmd_init)
    sp = sub.add_parser("scan", help="check broker sites for your listings now")
    sp.add_argument("--discover", action="store_true", help="also web-search for other sites")
    sp.set_defaults(func=cmd_scan)
    rp = sub.add_parser("run", help="the scheduled job: inbox, scan if due, act, report")
    rp.add_argument("--interactive", action="store_true", help="drive opt-out forms in a browser")
    rp.add_argument("--force", action="store_true", help="scan now even if not due")
    rp.set_defaults(func=cmd_run)
    sub.add_parser("status", help="show the current report").set_defaults(func=cmd_status)
    mp = sub.add_parser("mark", help="record something you did or saw")
    mp.add_argument("broker")
    mp.add_argument("state", choices=["submitted", "confirmed", "dismiss", "confirm-listing"])
    mp.set_defaults(func=cmd_mark)
    lp = sub.add_parser("letter", help="print a removal request for a site")
    lp.add_argument("broker")
    lp.set_defaults(func=cmd_letter)
    sub.add_parser("verify-registry", help="check opt-out URLs still resolve").set_defaults(
        func=cmd_verify_registry)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
