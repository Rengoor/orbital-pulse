"""SQLite append-only store. Log first, display second.

Two chains live here: decision Records, and ground Reviews in a chain of their
own (a review never rewrites the Record it is about). The class only ever
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
