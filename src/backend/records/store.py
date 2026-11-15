"""SQLite append-only store. Log first, display second.

Several chains live here: decision Records, plus ground Reviews, acknowledgements
and delay-aware handoffs, each in a chain of its own (none of them ever rewrites
the Record it is about). The class only ever
inserts; there is no update or delete. That is a convention, not a defence:
whoever can open the database file can edit it, which is exactly what the hash
chain and signatures exist to reveal.

Owner: person B
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

from backend.records.chain import GENESIS, first_broken_link, seal, verify_entry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    astronaut_id TEXT NOT NULL,
    body         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS records_by_astronaut ON records (astronaut_id, seq);
CREATE TABLE IF NOT EXISTS reviews (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    body      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS acks (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    body      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoffs (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    astronaut_id TEXT NOT NULL,
    body      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS handoffs_by_astronaut ON handoffs (astronaut_id, seq);
CREATE TABLE IF NOT EXISTS downlink_pending (
    arrival   INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL,
    body      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS downlink_anchors (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    body      TEXT NOT NULL
);
"""


class RecordStore:
    """Append-only store. ``path=None`` keeps everything in memory."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        if path is not None:
            parent = os.path.dirname(os.fspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        # One connection shared across the API's worker threads, guarded by a lock.
        self._conn = sqlite3.connect(
            os.fspath(path) if path is not None else ":memory:", check_same_thread=False
        )
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- helpers --------------------------------------------------------------

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [json.loads(row[0]) for row in self._conn.execute(sql, params)]

    def _head_hash(self, table: str) -> str:
        row = self._conn.execute(f"SELECT body FROM {table} ORDER BY seq DESC LIMIT 1").fetchone()
        return json.loads(row[0])["hash"] if row else GENESIS

    # -- records --------------------------------------------------------------

    def append_with(self, build) -> dict:
        """Append the Record returned by ``build(prev_hash)``.

        Reading the chain head and inserting happen under one lock, so two
        concurrent check-ins can never link to the same previous record.
        """
        with self._lock:
            head = self._head_hash("records")
            record = build(head)
            if record.get("prev_hash") != head:
                raise ValueError(
                    f"record {record.get('id')!r} does not link to the chain head: "
                    f"prev_hash={record.get('prev_hash')!r}, head={head!r}"
                )
            with self._conn:
                self._conn.execute(
                    "INSERT INTO records (id, astronaut_id, body) VALUES (?, ?, ?)",
                    (record["id"], record["astronaut_id"], json.dumps(record, sort_keys=True)),
                )
            return record

    def all(self) -> list[dict]:
        """Every record, oldest first."""
        return self._rows("SELECT body FROM records ORDER BY seq")

    def get(self, record_id: str) -> dict | None:
        rows = self._rows("SELECT body FROM records WHERE id = ?", (record_id,))
        return rows[0] if rows else None

    def latest(self, astronaut_id: str) -> dict | None:
        rows = self._rows(
            "SELECT body FROM records WHERE astronaut_id = ? ORDER BY seq DESC LIMIT 1",
            (astronaut_id,),
        )
        return rows[0] if rows else None

    def list(self, astronaut_id: str | None = None, limit: int | None = None) -> list[dict]:
        """Records, most recent first, optionally filtered and limited."""
        sql, params = "SELECT body FROM records", []
        if astronaut_id is not None:
            sql += " WHERE astronaut_id = ?"
            params.append(astronaut_id)
        sql += " ORDER BY seq DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self._rows(sql, tuple(params))

    def verify_chain(self, upto_record_id: str | None = None) -> tuple[bool, str | None]:
        """(valid, id of the first broken record) for the Record chain."""
        broken_at = first_broken_link(self.all(), upto_id=upto_record_id)
        return broken_at is None, broken_at

    # -- reviews --------------------------------------------------------------

    def add_review(self, review: dict, signing_key: str | None = None) -> dict:
        """Seal *review* into the review chain and store it."""
        with self._lock:
            sealed = seal(review, self._head_hash("reviews"), signing_key=signing_key)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO reviews (record_id, body) VALUES (?, ?)",
                    (sealed["record_id"], json.dumps(sealed, sort_keys=True)),
                )
            return sealed

    def reviews(self, record_id: str | None = None) -> list[dict]:
        """Reviews, oldest first, optionally for one Record."""
        if record_id is None:
            return self._rows("SELECT body FROM reviews ORDER BY seq")
        return self._rows("SELECT body FROM reviews WHERE record_id = ? ORDER BY seq", (record_id,))

    def verify_reviews(self) -> tuple[bool, int | None]:
        """(valid, position of the first broken review) for the review chain."""
        prev_hash = GENESIS
        for position, review in enumerate(self.reviews()):
            if review.get("prev_hash") != prev_hash or not verify_entry(review):
                return False, position
            prev_hash = review["hash"]
        return True, None

    # -- acknowledgements ------------------------------------------------------

    def add_ack(self, ack: dict, signing_key: str | None = None) -> dict:
        """Seal *ack* into the acknowledgement chain and store it."""
        with self._lock:
            sealed = seal(ack, self._head_hash("acks"), signing_key=signing_key)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO acks (record_id, body) VALUES (?, ?)",
                    (sealed["record_id"], json.dumps(sealed, sort_keys=True)),
                )
            return sealed

    def acks(self, record_id: str | None = None) -> list[dict]:
        """Acknowledgements, oldest first, optionally for one Record."""
        if record_id is None:
            return self._rows("SELECT body FROM acks ORDER BY seq")
        return self._rows("SELECT body FROM acks WHERE record_id = ? ORDER BY seq", (record_id,))

    def verify_acks(self) -> tuple[bool, int | None]:
        """(valid, position of the first broken ack) for the acknowledgement chain."""
        prev_hash = GENESIS
        for position, ack in enumerate(self.acks()):
            if ack.get("prev_hash") != prev_hash or not verify_entry(ack):
                return False, position
            prev_hash = ack["hash"]
        return True, None

    # -- handoffs (delay-aware autonomy) -----------------------------------------

    def add_handoff(self, handoff: dict, signing_key: str | None = None) -> dict:
        """Seal *handoff* into the handoff chain and store it."""
        with self._lock:
            sealed = seal(handoff, self._head_hash("handoffs"), signing_key=signing_key)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO handoffs (record_id, astronaut_id, body) VALUES (?, ?, ?)",
                    (sealed["record_id"], sealed["astronaut_id"], json.dumps(sealed, sort_keys=True)),
                )
            return sealed

    def handoffs(self, record_id: str | None = None) -> list[dict]:
        """Handoffs, oldest first, optionally for one Record."""
        if record_id is None:
            return self._rows("SELECT body FROM handoffs ORDER BY seq")
        return self._rows("SELECT body FROM handoffs WHERE record_id = ? ORDER BY seq", (record_id,))

    def latest_handoff(self, astronaut_id: str) -> dict | None:
        rows = self._rows(
            "SELECT body FROM handoffs WHERE astronaut_id = ? ORDER BY seq DESC LIMIT 1", (astronaut_id,)
        )
        return rows[0] if rows else None

    def verify_handoffs(self) -> tuple[bool, int | None]:
        """(valid, position of the first broken handoff) for the handoff chain."""
        prev_hash = GENESIS
        for position, entry in enumerate(self.handoffs()):
            if entry.get("prev_hash") != prev_hash or not verify_entry(entry):
                return False, position
            prev_hash = entry["hash"]
        return True, None

    def latest_review_for(self, astronaut_id: str) -> tuple[dict, dict] | None:
        """(review, record) for the most recent review of any of this astronaut's records."""
        with self._lock:
            row = self._conn.execute(
                "SELECT rv.body, rc.body FROM reviews rv JOIN records rc ON rc.id = rv.record_id "
                "WHERE rc.astronaut_id = ? ORDER BY rv.seq DESC LIMIT 1",
                (astronaut_id,),
            ).fetchone()
        return (json.loads(row[0]), json.loads(row[1])) if row else None

    # -- downlink queue persistence -------------------------------------------

    def downlink_load(self) -> tuple[list[tuple[int, dict]], list[dict]]:
        """((arrival, summary) rows oldest first, anchors oldest first)."""
        with self._lock:
            pending = [
                (row[0], json.loads(row[1]))
                for row in self._conn.execute(
                    "SELECT arrival, body FROM downlink_pending ORDER BY arrival"
                )
            ]
        anchors = self._rows("SELECT body FROM downlink_anchors ORDER BY seq")
        return pending, anchors

    def downlink_add(self, arrival: int, summary: dict, anchor: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO downlink_pending (arrival, record_id, body) VALUES (?, ?, ?)",
                (arrival, summary["record_id"], json.dumps(summary, sort_keys=True)),
            )
            self._conn.execute(
                "INSERT INTO downlink_anchors (body) VALUES (?)",
                (json.dumps(anchor, sort_keys=True),),
            )

    def downlink_remove(self, record_ids: list[str]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "DELETE FROM downlink_pending WHERE record_id = ?",
                [(record_id,) for record_id in record_ids],
            )
