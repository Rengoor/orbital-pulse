"""Signed acknowledgements: an astronaut confirming they have seen a verdict.

An acknowledgement never changes the verdict, the tier or the Record it
refers to. It only states, in its own hash-linked chain, that a named person
saw the decision at a given time, so Earth can later tell "the crew was
shown this" apart from "the crew confirmed seeing this".
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.common.schema_check import validate
from backend.records.chain import canonical_json
from backend.records.signing import sign

_ACK_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "schemas" / "ack.schema.json"


def build_ack(
    record_id: str,
    acknowledged_by: str,
    note: str = "",
    now: datetime | None = None,
    signing_key: str | None = None,
) -> dict:
    """Return a signed, schema-valid acknowledgement of one Record."""
    if not acknowledged_by or not acknowledged_by.strip():
        raise ValueError("acknowledged_by must name who confirmed the verdict")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    ack = {
        "record_id": record_id,
        "acknowledged_by": acknowledged_by.strip(),
        "note": note,
        "ts": now.isoformat() + "Z",
    }
    ack["signature"] = sign(canonical_json(ack), signing_key)
    validate(ack, str(_ACK_SCHEMA_PATH))
    return ack
