"""Current tier, reasons and the one next action.

Owner: person A
"""

import os

from fastapi import APIRouter, Depends, HTTPException

from backend.api.state import AppState, get_state
from backend.pipelines.d_llm.feedback import current_feedback
from backend.records.handoff import review_arrival

router = APIRouter()


@router.get("/{astronaut_id}")
def status(astronaut_id: str, state: AppState = Depends(get_state)) -> dict:
    """Latest verdict for one astronaut. No raw readings in the response.

    ``disagreement_status`` tells the astronaut whether the assessments behind
    the verdict were unanimous; it never changes the tier.
    """
    record = state.store.latest(astronaut_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no records for astronaut {astronaut_id!r}")
    verdict = record["verdict"]
    return {
        "tier": verdict["tier"],
        "action": verdict["action"],
        "additional_actions": verdict.get("additional_actions", []),
        "known_severity": verdict.get("known_severity"),
        "disagreement_status": verdict.get("disagreement_status"),
        "reasons": verdict["reasons"],
        "record_id": record["id"],
        "ts": record["ts"],
        "autonomy": _autonomy(state, record),
        "ground_review": _ground_review(state, astronaut_id),
        "advisor": _advisor(state, record),
    }


def _advisor(state: AppState, record: dict) -> dict:
    """The onboard advisor (pipeline D) as the HUD shows it: on or off, what it
    said for this record, and its current trust from the control centre's
    corrections. It never carries the tier; the tier above is the Checker's."""
    manifest = record.get("execution_manifest") or {}
    llm = manifest.get("llm") or {}
    enabled = os.environ.get("LLM_ENABLED", "0") == "1"
    said = None
    for p in record.get("proposals") or []:
        if p.get("pipeline_id") == "d_llm":
            said = p.get("tier")
    now = current_feedback(state.store)["summary"] if enabled else None
    return {
        "enabled": enabled,
        "said": said,                      # None: produced nothing, withheld, or off
        "shown_at_decision": llm.get("feedback"),
        "trust": now,                      # live trust, after the latest review
        "role": "advisory: may raise a tier, never lower one; never a vote",
    }


def _autonomy(state: AppState, record: dict) -> dict | None:
    """The handoff logged for this record, or None if none was logged."""
    entries = state.store.handoffs(record["id"])
    if not entries:
        return None
    h = entries[-1]
    return {k: h[k] for k in ("mode", "earth_answer_s", "action_deadline_s", "link",
                              "verdict_reaches_earth_at", "earliest_ground_answer_at")}


def _ground_review(state: AppState, astronaut_id: str) -> dict | None:
    """The latest ground review of this astronaut's verdicts, and whether it has
    reached the crew yet given the light delay. Reviews are simulated."""
    found = state.store.latest_review_for(astronaut_id)
    if found is None:
        return None
    review, reviewed = found
    arrival = review_arrival(review, state.link["one_way_delay_s"])
    return {
        "record_id": review["record_id"],
        "outcome": review["outcome"],
        "reviewer": review["reviewer"],
        "simulated": review.get("simulated", True),
        "reviewed_at": review["ts"],
        "arrives_at": arrival["arrives_at"],
        "arrived": arrival["arrived"],
        "record_ts": reviewed["ts"],
        "record_tier": reviewed["verdict"]["tier"],
        "record_action": reviewed["verdict"]["action"],
    }
