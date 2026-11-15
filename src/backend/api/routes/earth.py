"""Earth-side verify, replay, review, rule-change test.

Thin handlers: each one looks up its inputs and delegates to backend/earth/.

Owner: person A
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.earth.replay import replay
from backend.earth.review import build_review
from backend.earth.rulechange import rulechange
from backend.earth.verify import verify_chain
from backend.records.anchor import build_anchor, check_against_anchor

router = APIRouter()

_BAD_RULES = (ValueError, OSError, KeyError, TypeError, AttributeError)


def _require_record(state: AppState, record_id: str) -> dict:
    record = state.store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no record {record_id!r}")
    return record


def _rules_with(state: AppState, override: dict | None) -> dict:
    return {**state.rules, **(override or {})}


@router.get("/verify/{record_id}")
def verify(record_id: str, state: AppState = Depends(get_state)) -> dict:
    """Walk the hash chain from genesis to this record."""
    _require_record(state, record_id)
    return verify_chain(state.store.all(), upto_record_id=record_id, signing_key=state.signing_key)


@router.get("/anchor")
def anchor(state: AppState = Depends(get_state)) -> dict:
    """A signed checkpoint of the chain head, to be kept somewhere else.

    Whoever holds it can later prove that records were removed or history was
    rewritten, even by someone with the signing key.
    """
    return build_anchor(state.store.all(), datetime.now(timezone.utc))


@router.post("/anchor/verify")
def anchor_verify(checkpoint: dict[str, Any], state: AppState = Depends(get_state)) -> dict:
    """Check the current chain against a checkpoint taken earlier."""
    return check_against_anchor(state.store.all(), checkpoint)


class ReplayRequest(BaseModel):
    record_id: str
    rules_override: dict[str, Any] | None = None


@router.post("/replay")
def replay_record(body: ReplayRequest, state: AppState = Depends(get_state)) -> dict:
    """Re-run decide() on the stored inputs of a Record; returns the new Record.

    With no override the result equals the stored Record byte for byte. The
    replayed Record is returned for comparison and is not stored.
    """
    record = _require_record(state, body.record_id)
    try:
        return replay(
            record,
            state.baselines,
            _rules_with(state, body.rules_override),
            signing_key=state.signing_key,
        )
    except _BAD_RULES as exc:
        raise HTTPException(status_code=422, detail=f"rules override is not usable: {exc}") from exc


class ReviewRequest(BaseModel):
    record_id: str
    cmo_note: str = ""
    outcome: Literal["AGREE", "DISAGREE", "FOLLOW_UP"] = "FOLLOW_UP"
    reviewer: str = "simulated_flight_surgeon"


@router.post("/review")
def review(body: ReviewRequest, state: AppState = Depends(get_state)) -> dict:
    """Attach a signed, simulated ground review to a Record (in the review chain)."""
    _require_record(state, body.record_id)
    return state.store.add_review(
        build_review(
            body.record_id,
            body.outcome,
            note=body.cmo_note,
            reviewer=body.reviewer,
            signing_key=state.signing_key,
        ),
        signing_key=state.signing_key,
    )


@router.get("/handoffs")
def handoffs(state: AppState = Depends(get_state)) -> dict:
    """Every delay-aware handoff, oldest first: which decisions the crew had to own
    alone because Earth could not answer in time. Never changes a decision."""
    entries = state.store.handoffs()
    valid, broken_at = state.store.verify_handoffs()
    counts = {m: 0 for m in ("GROUND_IN_LOOP", "ONBOARD_AUTHORITY", "ROUTINE")}
    for e in entries:
        counts[e["mode"]] = counts.get(e["mode"], 0) + 1
    return {
        "handoffs": entries,
        "counts": counts,
        "link": state.link,
        "chain": {"valid": valid, "broken_at": broken_at},
    }


@router.get("/reviews")
def reviews(record_id: str | None = None, state: AppState = Depends(get_state)) -> dict:
    """The review log, oldest first, with whether the review chain is intact."""
    valid, broken_at = state.store.verify_reviews()
    return {
        "reviews": state.store.reviews(record_id),
        "chain": {"valid": valid, "broken_at": broken_at},
    }


_REDTEAM_RESULTS = Path(__file__).resolve().parents[3] / "evidence" / "results" / "redteam.json"


@router.get("/governance-checks")
def governance_checks() -> dict:
    """Results of the last red-team run: each attack and whether it was blocked.

    Produced by ``python -m evidence.redteam.run_redteam``. This route only
    reports the saved results; it does not run the attacks.
    """
    if not _REDTEAM_RESULTS.is_file():
        raise HTTPException(
            status_code=404,
            detail="no red-team results yet. Run: python -m evidence.redteam.run_redteam",
        )
    results = json.loads(_REDTEAM_RESULTS.read_text(encoding="utf-8"))
    return {
        "total": len(results),
        "blocked": sum(r["blocked"] for r in results),
        "unsafe_approvals": sum(not r["blocked"] for r in results),
        "results": results,
    }


class RuleChangeRequest(BaseModel):
    rules_override: dict[str, Any]
    astronaut_id: str | None = None


@router.post("/rulechange")
def rulechange_diff(body: RuleChangeRequest, state: AppState = Depends(get_state)) -> dict:
    """Apply a proposed rule change to past records and report what would differ."""
    records = [
        r for r in state.store.all() if body.astronaut_id is None or r["astronaut_id"] == body.astronaut_id
    ]
    try:
        return rulechange(records, state.baselines, _rules_with(state, body.rules_override))
    except _BAD_RULES as exc:
        raise HTTPException(status_code=422, detail=f"rules override is not usable: {exc}") from exc


@router.get("/downlink")
def downlink_pending(state: AppState = Depends(get_state)) -> dict:
    """Return pending downlink summaries (urgent first) and automatically produced chain anchors."""
    return {
        "pending": state.queue.pending(),
        "anchors": state.queue.anchors(),
    }


class DownlinkReleaseRequest(BaseModel):
    one_way_delay_s: float = 0.0
    max_items: int | None = None
    flush: bool = False


@router.post("/downlink/release")
def downlink_release(body: DownlinkReleaseRequest, state: AppState = Depends(get_state)) -> dict:
    """Release sendable downlink summaries for the given link delay, along with the latest chain anchor."""
    if body.one_way_delay_s < 0:
        raise HTTPException(status_code=422, detail="one_way_delay_s must be non-negative")
    sent = state.queue.release(
        one_way_delay_s=body.one_way_delay_s,
        max_items=body.max_items,
        flush=body.flush,
    )
    return {
        "sent": sent,
        "pending_count": len(state.queue),
        "latest_anchor": state.queue.latest_anchor(),
    }
