"""Hash chain: append, verify, find the first broken link.

Every entry carries ``prev_hash`` (the hash of the entry before it, or
"GENESIS") and ``hash`` (SHA-256 over the canonical JSON of everything except
``hash`` and ``signature``). Changing any field of any entry breaks its own
hash; re-hashing it breaks its signature and the next entry's ``prev_hash``.

Owner: person B
"""

from __future__ import annotations

import hashlib
import json

from backend.records.signing import sign, verify

GENESIS = "GENESIS"

_UNHASHED_FIELDS = ("hash", "signature")


def canonical_json(obj) -> str:
    """One byte-exact serialization: sorted keys, no whitespace, ASCII only."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def compute_hash(entry: dict) -> str:
    """SHA-256 of the canonical serialization of everything except hash/signature."""
    body = {k: v for k, v in entry.items() if k not in _UNHASHED_FIELDS}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def seal(entry: dict, prev_hash: str, signing_key: str | None = None) -> dict:
    """Return a copy of *entry* linked to *prev_hash*, hashed and signed."""
    sealed = {k: v for k, v in entry.items() if k not in _UNHASHED_FIELDS}
    sealed["prev_hash"] = prev_hash
    sealed["hash"] = compute_hash(sealed)
    sealed["signature"] = sign(sealed["hash"], signing_key)
    return sealed


def verify_entry(entry: dict, signing_key: str | None = None) -> bool:
    """True when the entry's hash and signature both match its contents."""
    try:
        return entry.get("hash") == compute_hash(entry) and verify(
            entry["hash"], entry.get("signature"), signing_key
        )
    except (TypeError, ValueError, AttributeError):
        return False


def first_broken_link(
    entries: list[dict],
    upto_id: str | None = None,
    signing_key: str | None = None,
) -> str | None:
    """Walk *entries* (oldest first) from genesis; return the id of the first
    broken one, or None when the chain is intact.

    An entry is broken when its ``prev_hash`` is not the hash of the entry
    before it, or its own hash or signature does not match its contents.
    Stops after the entry whose id is *upto_id*, when given.
    """
    prev_hash = GENESIS
    for entry in entries:
        if entry.get("prev_hash") != prev_hash or not verify_entry(entry, signing_key):
            return str(entry.get("id"))
        if upto_id is not None and entry.get("id") == upto_id:
            break
        prev_hash = entry["hash"]
    return None
