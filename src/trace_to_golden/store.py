"""SQLite store for redacted traces and the review queue.

`add_traces` takes `RedactedTrace` only, so raw ingester output cannot be
written by mistake. Records are stored as pydantic JSON in one column: the
schema stays flat and every read goes back through model validation. Triage
results are not stored: they live in the queued candidates' flags and are
recomputed on each `ttg triage` run.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path

from trace_to_golden.models import GoldenCandidate, RedactedTrace, ReviewStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    record_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    record_id TEXT PRIMARY KEY REFERENCES traces(record_id),
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""
"""Idempotent DDL run on every open; `status` is a column only so the queue can filter on it."""


class Store:
    """Thin wrapper over one SQLite file."""

    def __init__(self, path: Path) -> None:
        """Create the tables on first use."""
        self._path = path
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        """One connection per call, committed on success and always closed."""
        db = sqlite3.connect(self._path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_traces(self, traces: Iterable[RedactedTrace]) -> int:
        """Insert new traces; a record seen before is skipped. Returns how many were new."""
        with self._connect() as db:
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO traces (record_id, payload_json) VALUES (?, ?)",
                [(t.record.record_id, t.model_dump_json()) for t in traces],
            )
            return db.total_changes - before

    def traces(self) -> list[RedactedTrace]:
        """All stored traces, in insertion order."""
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM traces ORDER BY rowid").fetchall()
        return [RedactedTrace.model_validate_json(row[0]) for row in rows]

    def enqueue(self, candidates: Iterable[GoldenCandidate]) -> int:
        """Add new candidates; one already in the queue keeps its review state."""
        with self._connect() as db:
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO candidates (record_id, status, payload_json)"
                " VALUES (?, ?, ?)",
                [(c.record_id, c.status.value, c.model_dump_json()) for c in candidates],
            )
            return db.total_changes - before

    def save_candidate(self, candidate: GoldenCandidate) -> None:
        """Write a reviewed candidate back."""
        with self._connect() as db:
            db.execute(
                "UPDATE candidates SET status = ?, payload_json = ? WHERE record_id = ?",
                (candidate.status.value, candidate.model_dump_json(), candidate.record_id),
            )

    def candidate(self, record_id: str) -> GoldenCandidate | None:
        """One candidate, or None if it is not in the queue."""
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM candidates WHERE record_id = ?", (record_id,)
            ).fetchone()
        return GoldenCandidate.model_validate_json(row[0]) if row else None

    def candidates(self, status: ReviewStatus | None = None) -> list[GoldenCandidate]:
        """Queue content, optionally filtered by status, oldest first."""
        query = "SELECT payload_json FROM candidates"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        with self._connect() as db:
            rows = db.execute(query + " ORDER BY rowid", params).fetchall()
        return [GoldenCandidate.model_validate_json(row[0]) for row in rows]
