"""SQLite-backed job queue, webhook event dedupe and credit ledger.

Single-instance by design (docs/architecture.md §4). On Render Free the file is
ephemeral; correctness relies on HubSpot status properties, not on this store.
"""

import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.credits import CreditBudgetExceeded

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_events (
    event_key TEXT PRIMARY KEY,
    received_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    run_after REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_unique
    ON jobs (kind, object_id) WHERE status IN ('queued', 'running');
CREATE TABLE IF NOT EXISTS credit_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cost INTEGER NOT NULL,
    operation TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


@dataclass
class Job:
    id: int
    kind: str
    object_id: str
    status: str
    attempts: int
    last_error: str | None
    created_at: float
    updated_at: float


class JobStore:
    def __init__(self, path: str, clock: Callable[[], float] = time.time):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def ping(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1").fetchone()[0] == 1

    # --- webhook event dedupe ---------------------------------------------------

    def record_event(self, event_key: str) -> bool:
        """Remember an event; True if it was not seen before."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO processed_events (event_key, received_at) VALUES (?, ?)",
                (event_key, self._clock()),
            )
            return cursor.rowcount == 1

    # --- jobs -------------------------------------------------------------------

    def enqueue(self, kind: str, object_id: str) -> int | None:
        """Queue a job; returns None if the same job is already queued or running."""
        now = self._clock()
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "INSERT INTO jobs (kind, object_id, status, run_after, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (kind, object_id, QUEUED, now, now, now),
                )
            except sqlite3.IntegrityError:
                return None
            return cursor.lastrowid

    def claim_next(self) -> Job | None:
        now = self._clock()
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM jobs WHERE status = ? AND run_after <= ? ORDER BY run_after, id LIMIT 1",
                (QUEUED, now),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE jobs SET status = ?, attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (RUNNING, now, row["id"]),
            )
            return self._get(row["id"])

    def complete(self, job_id: int) -> None:
        self._set(job_id, status=DONE, last_error=None)

    def fail(self, job_id: int, error: str, *, retry_delay: float | None, max_attempts: int) -> bool:
        """Record a failure; requeue after retry_delay unless attempts are exhausted.

        Returns True when the failure is final.
        """
        job = self.get(job_id)
        final = retry_delay is None or job.attempts >= max_attempts
        if final:
            self._set(job_id, status=FAILED, last_error=error[:500])
        else:
            self._set(job_id, status=QUEUED, last_error=error[:500], run_after=self._clock() + retry_delay)
        return final

    def requeue_stale(self, lease_seconds: float) -> int:
        now = self._clock()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE jobs SET status = ?, run_after = ?, updated_at = ? WHERE status = ? AND updated_at < ?",
                (QUEUED, now, now, RUNNING, now - lease_seconds),
            )
            return cursor.rowcount

    def get(self, job_id: int) -> Job:
        with self._lock:
            return self._get(job_id)

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        counts = {QUEUED: 0, RUNNING: 0, DONE: 0, FAILED: 0}
        counts.update({row["status"]: row["n"] for row in rows})
        return counts

    def recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_job(row) for row in rows]

    # --- credit ledger storage ----------------------------------------------------

    def add_credit_entry(self, cost: int, operation: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO credit_ledger (cost, operation, created_at) VALUES (?, ?, ?)",
                (cost, operation, self._clock()),
            )

    def credit_totals(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT operation, SUM(cost) AS total FROM credit_ledger GROUP BY operation ORDER BY operation"
            ).fetchall()
        return {row["operation"]: row["total"] for row in rows}

    # --- internals ------------------------------------------------------------------

    def _get(self, job_id: int) -> Job:
        return _job(self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def _set(self, job_id: int, **fields) -> None:
        fields["updated_at"] = self._clock()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))


def _job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        kind=row["kind"],
        object_id=row["object_id"],
        status=row["status"],
        attempts=row["attempts"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqliteCreditLedger:
    """CreditLedger whose spend survives process restarts (while the file exists)."""

    def __init__(self, store: JobStore, budget: int):
        self._store = store
        self.budget = budget

    @property
    def spent(self) -> int:
        return sum(self._store.credit_totals().values())

    @property
    def remaining(self) -> int:
        return self.budget - self.spent

    def ensure_available(self, cost: int) -> None:
        remaining = self.remaining
        if cost > remaining:
            raise CreditBudgetExceeded(
                f"Forager credit budget exhausted: need {cost}, {remaining} of {self.budget} left"
            )

    def record(self, cost: int, operation: str) -> None:
        if cost > 0:
            self._store.add_credit_entry(cost, operation)

    def summary(self) -> dict:
        totals = self._store.credit_totals()
        spent = sum(totals.values())
        return {"budget": self.budget, "spent": spent, "remaining": self.budget - spent, "by_operation": totals}
