"""Simulated AGREE / DISAGREE / FOLLOW_UP reviews, signed, kept in a separate chain.

Owner: person B
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.common.schema_check import validate
from backend.records.chain import canonical_json
from backend.records.signing import sign

OUTCOMES = ("AGREE", "DISAGREE", "FOLLOW_UP")
TIERS = ("GREEN", "YELLOW", "RED", "GREY")

_REVIEW_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "schemas" / "review.schema.json"


def build_review(
    record_id: str,
    outcome: str,
    note: str = "",
    reviewer: str = "simulated_flight_surgeon",
    now: datetime | None = None,
    signing_key: str | None = None,
    confirmed_tier: str | None = None,
) -> dict:
    """Return a signed, schema-valid Review of one Record.

    Reviews are always labelled ``simulated``: no real flight surgeon is in
    this loop. The caller appends the result to the review chain; the Record
    under review is never modified.

    ``confirmed_tier`` is what the control centre says the tier should have
    been. It is required to turn a DISAGREE into a lesson for the onboard
    advisor (backend/pipelines/d_llm/feedback.py); an AGREE confirms the
    recorded tier by itself. It never changes the Record.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if confirmed_tier is not None and confirmed_tier not in TIERS:
        raise ValueError(f"confirmed_tier must be one of {TIERS}, got {confirmed_tier!r}")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    review = {
        "record_id": record_id,
        "reviewer": reviewer,
        "outcome": outcome,
        "simulated": True,
        "note": note,
        "ts": now.isoformat() + "Z",
    }
    if confirmed_tier is not None:
        review["confirmed_tier"] = confirmed_tier
    review["signature"] = sign(canonical_json(review), signing_key)
    validate(review, str(_REVIEW_SCHEMA_PATH))
    return review
