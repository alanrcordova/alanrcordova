# Unlisted — Design

A personal tool that finds where your personal information is published online
and works, on a schedule, to get it removed — using California privacy law
where it applies.

> Not legal advice. The legal references below are a starting point; verify
> them against current statute and regulations before relying on them.

---

## 1. The problem in plain terms

Hundreds of "people-search" and data-broker companies compile profiles —
name, age, home address, phone, email, relatives — and sell or display them.
Removing yourself is tedious for three reasons:

1. **Discovery.** You don't know which sites have you.
2. **Friction.** Every site has its own opt-out: a web form, an email, an
   account portal, a CAPTCHA, an email confirmation link.
3. **Relisting.** Brokers routinely re-acquire your data and republish it
   weeks or months later. A one-time cleanup decays.

So the tool has to **find → request → verify → re-check**, in a loop.

## 2. The biggest lever: California's DROP

The California **Delete Act** (SB 362, Civ. Code §1798.99.80 et seq.) created
the **Delete Request and Opt-out Platform (DROP)**, run by the California
Privacy Protection Agency (CPPA). One request through DROP reaches *every data
broker registered in California*.

- Consumers can submit through DROP starting **January 1, 2026**.
- Registered brokers must start processing DROP requests **August 1, 2026**,
  and must check DROP **at least every 45 days** after that, delete matching
  records, and stop collecting/selling going forward.

As of this design (Sept 2026), DROP is live and brokers are obliged to process
it. The tool therefore treats DROP as **step zero** and the per-site work as
cleanup for what DROP misses:

- Sites that aren't registered brokers (some people-search sites claim the
  data is "public records" or operate offshore).
- Search-engine results that point to old listings.
- Non-broker sites (forums, old directories, personal pages).

## 3. Architecture

```
               ┌───────────────────────── unlisted run (cron/systemd/launchd) ──────────────────────────┐
               │                                                                                         │
 profile.yaml ─┤  1. Inbox        2. Scan              3. Plan             4. Act              5. Report │
 (local only)  │  confirm links → broker search +  →  decide per-site  →  email letters /  →  markdown   │
               │  from brokers    web search          action + due date    forms / tasks       summary    │
               │                                                                                         │
               └──────────────────────────────── state.db (SQLite) ──────────────────────────────────────┘
                                                        ▲
                                    brokers.yaml registry + recipes/*.yaml
```

| Module | Job |
|---|---|
| `profile.py` | Loads your details and derives search variants (name forms, phone digits). |
| `brokers.py` + `data/brokers.yaml` | Registry of ~20 major brokers: search URL pattern, opt-out method, parent company, relist interval. |
| `scanner.py` | Fetches each broker's search page politely and scores whether *you* are on it. Optional web-search discovery (Brave Search API) for sites not in the registry. |
| `matching.py` | Scores a page: name is required; city, phone, email, birth year and relatives add confidence. Avoids flagging namesakes. |
| `store.py` | SQLite: findings, removal requests, deadlines, run history. |
| `planner.py` | For each finding, decides the next action and tracks legal deadlines (45 days to respond, follow-up, escalation). Detects relisting. |
| `letters.py` + `templates/` | Renders CCPA deletion / opt-out requests, follow-ups, and a CPPA complaint draft. |
| `actions/` | `mailer.py` writes `.eml` drafts (optionally sends via SMTP); `forms.py` drives a real browser through opt-out forms with human hand-off at CAPTCHAs. |
| `inbox.py` | Watches IMAP for broker confirmation emails and opens verification links, only from allow-listed broker domains. |
| `report.py` | Plain-language report: where you were found, what was done, what needs you. |

### Why local, not cloud

The tool necessarily holds the exact data you're trying to remove. It runs
on your own machine; `profile.yaml`, the database and outgoing letters live in
`~/.unlisted/` (never in the git repo). Use a **dedicated email alias** for
opt-outs so brokers don't get your primary inbox and so the inbox watcher only
sees privacy mail.

## 4. The removal pipeline

For each broker where you're found (or proactively, for every broker):

| Opt-out method | What the tool does | Your involvement |
|---|---|---|
| `drop` | Creates a one-time task with the DROP link and records the date. | ~10 minutes, once. |
| `email` | Renders a CCPA deletion + opt-out letter to `outbox/`. Sends via SMTP if `auto_send: true`. | None (auto) or one click (draft). |
| `web_form` with recipe | Opens a browser, fills the form, submits. Pauses for you when a CAPTCHA appears. | Solve CAPTCHAs. |
| `web_form` without recipe | Creates a checklist task with the exact URL, the listing URL and the fields to enter. | A few minutes per site. |
| Confirmation email | Inbox watcher clicks the verification link if it's from that broker's domain. | None. |

**On CAPTCHAs:** the tool does not attempt to defeat them. They are the
point where automation stops and hands the browser to you. This keeps the
tool within sites' terms and avoids being blocked.

### Deadlines and escalation (CCPA, Civ. Code §1798.100 et seq.)

| Event | Timing | Source |
|---|---|---|
| Business confirms receipt of deletion request | 10 business days | CCPA regs §7021 |
| Business responds to deletion request | 45 calendar days, extendable once by 45 with notice | §1798.130(a)(2) |
| Business acts on opt-out of sale/sharing | 15 business days | CCPA regs §7026 |

The planner records `due_at` on every request. When a deadline passes with
no confirmation, it drafts a **follow-up letter**; after a second miss it
drafts a **complaint to the CPPA** (and flags it for you — it never files a
complaint on its own).

### Relisting

After a request is confirmed, the site is re-scanned on its `relist_days`
interval (default 90). If you reappear, the finding is marked `relisted`, a
fresh request goes out, and the report calls it out — useful evidence if you
later complain to the CPPA.

## 5. Schedule

`unlisted run` is idempotent — safe to run as often as you like; each step
checks whether it's due.

| Step | Default cadence | Setting |
|---|---|---|
| Inbox check (confirmation links) | every run | — |
| Scan registry brokers | weekly | `scan_every_days: 7` |
| Web-search discovery | monthly | `discover_every_days: 30` |
| Follow-ups on overdue requests | every run | — |
| Re-check confirmed removals | per broker, ~90 days | `relist_days` in registry |

Recommended: run daily via cron/systemd/launchd (examples in `deploy/`). The
cadences above keep actual web traffic at weekly/monthly levels.

## 6. Legal basis the letters rely on

- **Right to delete** — Civ. Code §1798.105.
- **Right to opt out of sale/sharing** — §1798.120.
- **Right to limit use of sensitive personal information** — §1798.121
  (precise location, SSN, etc.).
- **Right to know** what's held (optional in the letter) — §1798.110.
- **Data broker duties / DROP** — §1798.99.80 et seq.
- **Authorized agent** — §1798.135 and CCPA regs §7063, if someone files on
  your behalf.

**Known pushback and how the letter handles it:** Brokers often claim the
data is "publicly available" and exempt. The CCPA's exemption covers
information lawfully made available from *government records*; it does not
cover profiles assembled from commercial sources, inferences, or phone/email
data bought from other businesses. The letter asks the broker to delete all
non-exempt data and to identify the specific exemption they rely on for
anything they keep.

**Applicability:** CCPA rights apply to California residents and to
businesses that meet its thresholds (most data brokers do). If
`california_resident` is false, the tool switches to a generic removal-request
template without statutory claims.

## 7. Limitations (honest ones)

- **Broker sites change constantly.** URLs, form fields and anti-bot defences
  change. The registry has a `last_verified` date per entry, and
  `unlisted verify-registry` checks that each URL still resolves. Expect to
  maintain it.
- **Many search pages block automated fetches.** When blocked, the scanner
  records `blocked` and creates a "check manually" task with the exact search
  URL rather than guessing.
- **Matching isn't perfect.** Common names produce namesakes. Only "likely"
  matches trigger automatic action; "possible" ones go to the review list.
- **Some removals need ID or a phone call.** Those become tasks.
- **Legal leverage stops at California law and the site's willingness.**
  Offshore sites may ignore letters; search-engine removal
  (Google's *Results about you*) is the fallback.

## 8. Possible extensions

- Fetch the CPPA data-broker registry CSV and generate email requests for
  every registered broker automatically.
- Hook `mailer.py` to the Gmail API to create real drafts instead of `.eml`
  files.
- Google *Results about you* monitoring (Google already emails when new
  results appear; the inbox watcher could ingest those).
- Encrypt `profile.yaml` at rest (e.g. with `age`/`sops`).
