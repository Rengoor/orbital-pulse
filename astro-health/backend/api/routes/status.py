"""Current tier, reasons and the one next action.

Owner: person A
"""

from fastapi import APIRouter, Depends, HTTPException

from backend.api.state import AppState, get_state

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
    }
