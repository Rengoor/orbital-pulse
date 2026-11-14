"""Earth-side verify, replay, review, rule-change test.

Thin handlers: each one looks up its inputs and delegates to backend/earth/.

Owner: person A
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.earth.replay import replay
from backend.earth.review import build_review
from backend.earth.rulechange import rulechange
from backend.earth.verify import verify_chain

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
    return verify_chain(state.store.all(), upto_record_id=record_id)


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
        return replay(record, state.baselines, _rules_with(state, body.rules_override))
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
        build_review(body.record_id, body.outcome, note=body.cmo_note, reviewer=body.reviewer)
    )


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
