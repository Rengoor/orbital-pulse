"""POST a check-in or sensor reading.

Owner: person A
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.orchestrator import decide

router = APIRouter()


class CheckinRequest(BaseModel):
    astronaut_id: str
    readings: list[dict[str, Any]] = []


@router.post("/checkin")
def checkin(body: CheckinRequest) -> dict:
    """Accept a check-in and return a verdict summary.

    Stamps each reading dict with the request's astronaut_id if not already
    present, so the fixture stub can echo it back correctly.
    """
    readings = body.readings
    # Ensure each reading carries the astronaut_id expected by decide().
    for r in readings:
        r.setdefault("astronaut_id", body.astronaut_id)

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, matches isoformat stub

    try:
        record = decide(readings=readings, baselines={}, rules={}, now=now)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"record_id": record["id"], "verdict": record["verdict"]}
