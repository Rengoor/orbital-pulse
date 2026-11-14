"""POST a check-in or sensor reading.

Owner: person A
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.orchestrator import _READING_VALIDATOR, decide
from backend.orchestrator import decide as _failsafe

logger = logging.getLogger(__name__)

router = APIRouter()


class CheckinRequest(BaseModel):
    astronaut_id: str
    readings: list[dict[str, Any]] = []
    # Decision time. Normally omitted (the server clock is used). Scenario
    # playback sets it so recorded events are judged at their own time; the
    # Record's execution manifest says which clock was used.
    now: datetime | None = None


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

    if body.now is not None:
        now, clock_source = body.now, "request"
    else:
        now, clock_source = datetime.now(timezone.utc), "server"
    now = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now

    def build(prev_hash: str) -> dict:
        common = dict(now=now, prev_hash=prev_hash, astronaut_id=body.astronaut_id, clock_source=clock_source)
        try:
            return decide(readings=readings, baselines=state.baselines, rules=state.rules, **common)
        except Exception as exc:  # noqa: BLE001 - last line of defence
            # decide() already fails safe for anything it can catch. If it
            # still raised, record the fail-safe verdict rather than leave the
            # crew looking at the previous verdict as if it were current.
            logger.exception("decide() raised; recording a fail-safe verdict")
            return _failsafe(
                readings=readings, baselines={}, rules={},
                force_failsafe=f"decision call failed: {type(exc).__name__}", **common,
            )

    # Log first, display second: the signed Record is in the store before the
    # verdict leaves this function.
    record = state.store.append_with(build)

    # Verdict summary only, never the full Record: keeps the downlink payload small.
    return {"record_id": record["id"], "verdict": record["verdict"]}
