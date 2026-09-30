import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ["UNLISTED_HOME"] = tempfile.mkdtemp()

from unlisted import letters, planner, report, scanner  # noqa: E402
from unlisted.brokers import Broker, broker_for_domain, load_brokers  # noqa: E402
from unlisted.inbox import verification_links  # noqa: E402
from unlisted.matching import page_text, score  # noqa: E402
from unlisted.profile import DEFAULT_SETTINGS, Address, Profile  # noqa: E402
from unlisted.store import Store, iso, now  # noqa: E402

YEAR = date.today().year


def make_profile(**kw) -> Profile:
    base = dict(
        full_name="Jane Q Public", contact_email="optouts@example.com",
        aliases=["Jane Public"], birth_year=YEAR - 46,
        emails=["jane@example.com"], phones=["(555) 555-0100"],
        addresses=[Address("123 Main St", "San Diego", "CA", "92101")],
        relatives=["John Public"],
        settings={**DEFAULT_SETTINGS, "request_delay_seconds": 0},
    )
    base.update(kw)
    return Profile(**base)


class MatchingTests(unittest.TestCase):
    def test_namesake_elsewhere_is_not_likely(self):
        m = score(make_profile(), page_text("<p>Jane Public, age 30, Boston MA</p>"), YEAR)
        self.assertLess(m.score, 0.6)

    def test_strong_match(self):
        html = "<div>Jane Public, Age: 46</div><div>San Diego, CA</div><div>555-555-0100</div>"
        m = score(make_profile(), page_text(html), YEAR)
        self.assertEqual(set(m.signals), {"name", "city", "phone", "age"})
        self.assertGreaterEqual(m.score, 0.6)

    def test_name_required(self):
        m = score(make_profile(), "someone in san diego 5555550100", YEAR)
        self.assertEqual(m.score, 0)


class RegistryTests(unittest.TestCase):
    def test_registry_loads_and_drop_first(self):
        brokers = load_brokers()
        self.assertEqual(brokers[0].id, "ca_drop")
        self.assertTrue(all(b.optout.get("url") or b.optout.get("email") for b in brokers))

    def test_search_url(self):
        spokeo = next(b for b in load_brokers() if b.id == "spokeo")
        self.assertEqual(spokeo.search_url_for(make_profile()),
                         "https://www.spokeo.com/jane-public/california/san-diego")

    def test_domain_lookup(self):
        self.assertEqual(broker_for_domain(load_brokers(), "mail.spokeo.com").id, "spokeo")
        self.assertIsNone(broker_for_domain(load_brokers(), "notspokeo.com"))


class LetterTests(unittest.TestCase):
    broker = Broker(id="x", name="ExampleBroker", category="people_search",
                    optout={"method": "email", "email": "privacy@example.org"})

    def test_ccpa_letter(self):
        text = letters.removal_request(make_profile(), self.broker, ["https://ex.org/p/1"])
        subject, body = letters.split_subject(text)
        self.assertIn("CCPA", subject)
        for s in ("§ 1798.105", "§ 1798.120", "ExampleBroker", "https://ex.org/p/1", "45 days"):
            self.assertIn(s, body)

    def test_non_california_letter_makes_no_ccpa_claims(self):
        text = letters.removal_request(make_profile(california_resident=False), self.broker, [])
        self.assertNotIn("1798", text)


class ScanTests(unittest.TestCase):
    def test_blocked_and_found(self):
        brokers = [b for b in load_brokers() if b.id in ("spokeo", "radaris")]

        def fake_fetch(url):
            if "spokeo" in url:
                return 403, "Access denied"
            return 200, "<h1>Jane Public</h1> San Diego, CA 555-555-0100 relatives: John Public"

        results = {r.broker_id: r for r in scanner.scan_all(brokers, make_profile(), fake_fetch)}
        self.assertEqual(results["spokeo"].label, "blocked")
        self.assertEqual(results["radaris"].label, "likely")


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = Store(":memory:")
        self.profile = make_profile()
        self.email_broker = Broker(id="mail", name="MailBroker", category="people_search",
                                   optout={"method": "email", "email": "privacy@mail.example"},
                                   search_url="https://mail.example/{first}-{last}")
        self.brokers = load_brokers() + [self.email_broker]

    def test_first_run_creates_requests_everywhere(self):
        out = planner.plan_and_act(self.store, self.profile, self.brokers, self.tmp)
        self.assertEqual(len(self.store.requests()), len(self.brokers))
        drop = self.store.open_request("ca_drop")
        self.assertIsNone(drop["due_at"])
        self.assertTrue(any("MailBroker" in t for t in out.for_you))
        self.assertTrue(any(self.tmp.glob("*-mail.eml")))
        # Idempotent: a second run doesn't duplicate.
        planner.plan_and_act(self.store, self.profile, self.brokers, self.tmp)
        self.assertEqual(len(self.store.requests()), len(self.brokers))

    def test_overdue_escalates_to_follow_up_then_complaint(self):
        self.store.add_request("mail", "initial", "email", "sent", 45)
        past = iso(now() - timedelta(days=1))
        self.store.db.execute("UPDATE requests SET due_at=?", (past,))
        planner.plan_and_act(self.store, self.profile, [self.email_broker], self.tmp)
        kinds = [r["kind"] for r in self.store.requests()]
        self.assertEqual(kinds, ["initial", "follow_up"])

        self.store.db.execute("UPDATE requests SET due_at=? WHERE kind='follow_up'", (past,))
        out = planner.plan_and_act(self.store, self.profile, [self.email_broker], self.tmp)
        self.assertIn("complaint_draft", [r["kind"] for r in self.store.requests()])
        self.assertTrue(any("CPPA" in t for t in out.for_you))

    def test_relisting_detected_and_re_requested(self):
        self.store.record_finding("mail", "https://mail.example/p/1", "likely", 0.9, ["name"])
        planner.plan_and_act(self.store, self.profile, [self.email_broker], self.tmp)
        self.store.mark_absent("mail")                   # later scan: gone
        self.assertEqual(self.store.findings()[0]["status"], "removed")
        status = self.store.record_finding("mail", "https://mail.example/p/1", "likely", 0.9)
        self.assertEqual(status, "relisted")
        planner.plan_and_act(self.store, self.profile, [self.email_broker], self.tmp)
        self.assertEqual(len([r for r in self.store.requests() if r["kind"] == "initial"]), 2)
        text = report.render(self.store, [self.email_broker], planner.Outcome())
        self.assertIn("Came back after removal (ever):** 1", text)


class InboxTests(unittest.TestCase):
    def test_only_broker_domain_confirm_links(self):
        broker = next(b for b in load_brokers() if b.id == "spokeo")
        body = ("Click https://www.spokeo.com/optout/confirm?t=abc to confirm. "
                "Ads: https://evil.example/confirm https://www.spokeo.com/pricing")
        self.assertEqual(verification_links(body, broker),
                         ["https://www.spokeo.com/optout/confirm?t=abc"])


if __name__ == "__main__":
    unittest.main()
