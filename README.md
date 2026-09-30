# Unlisted

**Find where your personal information is published online, and get it
taken down, on autopilot.**

Data brokers and "people-search" sites publish home addresses, phone numbers,
ages and relatives' names. Removing yourself is tedious, and the data tends to
come back. Unlisted runs on a schedule on your own computer and:

1. **Finds you.** Checks the major people-search sites weekly. With a Brave
   Search API key, it also searches the web monthly for other pages.
2. **Tells you apart from namesakes.** A listing only counts as you when your
   name appears *with* other details (your city, phone, email, age or
   relatives).
3. **Asks for removal.** It drafts (or sends) California privacy-law deletion
   requests and fills in opt-out forms. Where it can't finish on its own, such
   as a CAPTCHA or a phone check, it gives you a short to-do with the exact link
   and the text to paste.
4. **Holds sites to the deadline.** California law gives businesses 45 days to
   respond. When a site misses the deadline, Unlisted drafts a second notice.
   After a second miss, it drafts a complaint to the California Privacy
   Protection Agency for you to review. It never files a complaint for you.
5. **Watches for relisting.** It re-checks removed listings and starts over if
   you reappear.

It starts with **California's DROP**, the state's one-stop request that
reaches every registered data broker. Registered brokers have had to honor it
since August 2026.

→ How it works and the legal basis: [docs/DESIGN.md](docs/DESIGN.md)

## Quick start

```sh
pip install .                     # or: pip install ".[forms]" for browser form-filling
unlisted init                     # creates ~/.unlisted/profile.yaml — fill it in
unlisted run                      # first sweep: scan, request removals, write a report
```

Then schedule `unlisted run` daily. It works out for itself what's due, so
daily runs only scan weekly and web-search monthly:

- **Linux:** `deploy/unlisted.service` + `deploy/unlisted.timer` (systemd), or `deploy/crontab.example`
- **macOS:** `deploy/com.unlisted.run.plist` (launchd)

## Day to day

| Command | What it does |
|---|---|
| `unlisted run` | The scheduled job. Checks the inbox, scans if due, sends requests and follow-ups, and writes a report to `~/.unlisted/reports/`. |
| `unlisted run --interactive` | Also opens a browser and fills opt-out forms that have a recipe. You solve any CAPTCHAs. |
| `unlisted status` | Shows where things stand. |
| `unlisted mark spokeo submitted` | Records that you did a to-do. The 45-day clock starts now. |
| `unlisted mark spokeo dismiss` | That listing isn't you. |
| `unlisted letter web:example.com` | Prints a removal request for any site. |
| `unlisted verify-registry` | Checks that each broker's opt-out link still works. |

## Optional automation

- **Send emails automatically:** set `auto_send: true` plus the `smtp` settings.
- **Confirm verification emails automatically:** set the `imap` settings and
  `auto_open_verify_links: true`. Only links from that broker's own domain are
  ever opened.
- **Web discovery:** export `BRAVE_API_KEY`.
- **More brokers:** add entries to `~/.unlisted/brokers.local.yaml` (same format as
  `unlisted/data/brokers.yaml`). The CPPA's public data-broker registry lists
  privacy contact emails you can use.

Put passwords and keys in `~/.unlisted/env` (`chmod 600`). Never put them in the profile.

## Privacy of the tool itself

Everything personal stays in `~/.unlisted/`: your profile, database, letters
and reports. None of it goes in this repo (see `.gitignore`). Use a dedicated
email alias for opt-outs.

## Caveats

- The broker list in `unlisted/data/brokers.yaml` is a starting set and is
  **unverified**. Broker sites change URLs and forms often. Run
  `unlisted verify-registry` and update entries.
- Many search pages block automated checks. Those are listed in the report as
  "open these yourself".
- The letters cite California law (CCPA/CPRA and the Delete Act). Set
  `california_resident: false` to get a plain request instead. **This is not
  legal advice.**

## Development

```sh
python -m unittest discover -s tests
```
