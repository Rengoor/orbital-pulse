"""POST a check-in or sensor reading.

Owner: person A
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.orchestrator import _READING_VALIDATOR, decide

router = APIRouter()


class CheckinRequest(BaseModel):
    astronaut_id: str
    readings: list[dict[str, Any]] = []


@router.post("")
def checkin(body: CheckinRequest, state: AppState = Depends(get_state)) -> dict:
    """Validate the readings, decide, log the Record, then return the verdict.

    Every reading is checked against reading.schema.json before decide() is
    called; any failure is HTTP 422 and nothing is recorded.
    """
    readings = [{"astronaut_id": body.astronaut_id, **r} for r in body.readings]

    errors = []
    for i, reading in enumerate(readings):
        for error in _READING_VALIDATOR.iter_errors(reading):
            errors.append(
                {
                    "loc": ["body", "readings", i, *error.absolute_path],
                    "msg": error.message,
                    "type": "schema_validation",
                }
            )
        if reading.get("astronaut_id") != body.astronaut_id:
            errors.append(
                {
                    "loc": ["body", "readings", i, "astronaut_id"],
                    "msg": f"does not match the check-in astronaut_id {body.astronaut_id!r}",
                    "type": "astronaut_mismatch",
                }
            )
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Log first, display second: the signed Record is in the store before the
    # verdict leaves this function.
    record = state.store.append_with(
        lambda prev_hash: decide(
            readings=readings,
            baselines=state.baselines,
            rules=state.rules,
            now=now,
            prev_hash=prev_hash,
            astronaut_id=body.astronaut_id,
            signing_key=state.signing_key,
        )
    )
    # Automatically enqueue the downlink summary and chain anchor on every check-in.
    state.queue.enqueue(record, signing_key=state.signing_key)

    # Verdict summary only, never the full Record: keeps the downlink payload small.
    return {"record_id": record["id"], "verdict": record["verdict"]}
