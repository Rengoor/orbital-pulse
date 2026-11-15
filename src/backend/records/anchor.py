"""Chain checkpoints: a signed copy of the latest chain hash, kept somewhere else.

The hash chain alone cannot notice two things: the newest records being cut
off the end (what is left still verifies), and a complete rewrite by someone
who holds the signing key. A checkpoint that left the vehicle earlier, in a
downlink or an exported file, exposes both: the chain on board must still
contain that exact hash at that exact position.

Owner: person B
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.records.chain import GENESIS, canonical_json
from backend.records.signing import key_id, sign, verify


def build_anchor(records: list[dict], now: datetime | None = None, signing_key: str | None = None) -> dict:
    """Signed checkpoint of the chain as it stands: how long it is and its head hash."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    anchor = {
        "record_count": len(records),
        "head_hash": records[-1]["hash"] if records else GENESIS,
        "head_record_id": records[-1]["id"] if records else None,
        "ts": now.isoformat() + "Z",
        "key_id": key_id(signing_key),
    }
    anchor["signature"] = sign(canonical_json(anchor), signing_key)
    return anchor


def check_against_anchor(records: list[dict], anchor: dict, signing_key: str | None = None) -> dict:
    """Compare a chain (oldest first) with a checkpoint taken earlier.

    Returns ``{"valid": bool, "reason": str}``. Valid means the checkpoint is
    genuine and the chain still holds the checkpointed hash at the checkpointed
    position; records added since then are expected and fine.
    """
    try:
        unsigned = {k: v for k, v in anchor.items() if k != "signature"}
        if not verify(canonical_json(unsigned), anchor.get("signature"), signing_key):
            return {"valid": False, "reason": "checkpoint signature does not verify"}
        count = int(anchor["record_count"])
        head_hash = anchor["head_hash"]
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"valid": False, "reason": "checkpoint is malformed"}

    if count < 0:
        return {"valid": False, "reason": "checkpoint is malformed"}
    if len(records) < count:
        return {
            "valid": False,
            "reason": f"chain has {len(records)} record(s) but the checkpoint saw {count}: records were removed",
        }
    actual = records[count - 1]["hash"] if count else GENESIS
    if actual != head_hash:
        return {"valid": False, "reason": f"record {count} no longer has the checkpointed hash: history was rewritten"}
    return {"valid": True, "reason": f"chain still contains the checkpoint at record {count}"}
