"""SQLite state: findings, removal requests and deadlines, run history."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    broker_id TEXT NOT NULL,
    url TEXT NOT NULL,
    label TEXT NOT NULL,          -- likely | possible | blocked | discovered
    score REAL NOT NULL DEFAULT 0,
    signals TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | requested | removed | relisted | dismissed
    times_relisted INTEGER NOT NULL DEFAULT 0,
    UNIQUE (broker_id, url)
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY,
    broker_id TEXT NOT NULL,
    kind TEXT NOT NULL,           -- initial | follow_up | complaint_draft | task
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL,         -- drafted | sent | pending_user | confirmed | overdue | closed
    artifact TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    step TEXT PRIMARY KEY,
    last_run TEXT NOT NULL
);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- run cadence -------------------------------------------------------
    def due(self, step: str, every_days: float) -> bool:
        row = self.db.execute("SELECT last_run FROM runs WHERE step=?", (step,)).fetchone()
        return row is None or now() - datetime.fromisoformat(row[0]) >= timedelta(days=every_days)

    def mark_run(self, step: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (step, iso(now())))
        self.db.commit()

    # --- findings ----------------------------------------------------------
    def record_finding(self, broker_id: str, url: str, label: str, score: float = 0,
                       signals: list[str] | None = None) -> str:
        """Upsert a finding. Returns its status after the update.

        A finding that had been removed and shows up again becomes 'relisted'.
        """
        ts = iso(now())
        row = self.db.execute(
            "SELECT id, status FROM findings WHERE broker_id=? AND url=?", (broker_id, url)
        ).fetchone()
        sig = ",".join(signals or [])
        if row is None:
            self.db.execute(
                "INSERT INTO findings (broker_id, url, label, score, signals, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?)", (broker_id, url, label, score, sig, ts, ts))
            status = "open"
        else:
            relisted = row["status"] == "removed"
            status = "relisted" if relisted else row["status"]
            self.db.execute(
                "UPDATE findings SET label=?, score=?, signals=?, last_seen=?, status=?,"
                " times_relisted = times_relisted + ? WHERE id=?",
                (label, score, sig, ts, status, int(relisted), row["id"]))
        self.db.commit()
        return status

    def mark_absent(self, broker_id: str) -> None:
        """Broker scanned and you were not found: requested listings count as removed."""
        self.db.execute(
            "UPDATE findings SET status='removed' WHERE broker_id=? AND status IN ('requested','relisted')",
            (broker_id,))
        self.db.execute(
            "UPDATE requests SET status='confirmed' WHERE broker_id=? AND status IN ('drafted','sent','pending_user','overdue')",
            (broker_id,))
        self.db.commit()

    def set_finding_status(self, broker_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE findings SET status=? WHERE broker_id=? AND status IN ('open','relisted')",
            (status, broker_id))
        self.db.commit()

    def relisted_brokers(self) -> set[str]:
        rows = self.db.execute("SELECT DISTINCT broker_id FROM findings WHERE times_relisted > 0")
        return {r[0] for r in rows}

    def findings(self, *statuses: str) -> list[sqlite3.Row]:
        q = "SELECT * FROM findings"
        if statuses:
            q += f" WHERE status IN ({','.join('?' * len(statuses))})"
        return self.db.execute(q + " ORDER BY broker_id", statuses).fetchall()

    # --- requests ----------------------------------------------------------
    def add_request(self, broker_id: str, kind: str, method: str, status: str,
                    due_in_days: int | None = None, artifact: str | None = None,
                    notes: str | None = None) -> int:
        created = now()
        due = iso(created + timedelta(days=due_in_days)) if due_in_days else None
        cur = self.db.execute(
            "INSERT INTO requests (broker_id, kind, method, created_at, due_at, status, artifact, notes)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (broker_id, kind, method, iso(created), due, status, artifact, notes))
        self.db.commit()
        return cur.lastrowid

    def open_request(self, broker_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM requests WHERE broker_id=? AND status IN ('drafted','sent','pending_user','overdue')"
            " ORDER BY id DESC LIMIT 1", (broker_id,)).fetchone()

    def last_confirmed(self, broker_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM requests WHERE broker_id=? AND status='confirmed' ORDER BY id DESC LIMIT 1",
            (broker_id,)).fetchone()

    def overdue_requests(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM requests WHERE status IN ('sent','pending_user') AND due_at IS NOT NULL AND due_at < ?",
            (iso(now()),)).fetchall()

    def set_request_status(self, request_id: int, status: str) -> None:
        self.db.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
        self.db.commit()

    def requests(self, *statuses: str) -> list[sqlite3.Row]:
        q = "SELECT * FROM requests"
        if statuses:
            q += f" WHERE status IN ({','.join('?' * len(statuses))})"
        return self.db.execute(q + " ORDER BY created_at", statuses).fetchall()
