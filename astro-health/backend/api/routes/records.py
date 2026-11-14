"""List and fetch signed records and cards.

Owner: person A
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.state import AppState, get_state
from backend.records.cards import build_card

router = APIRouter()


@router.get("")
def list_records(
    astronaut_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=1000),
    state: AppState = Depends(get_state),
) -> list[dict]:
    """Records, most recent first. Read-only; writes happen only through /checkin."""
    return state.store.list(astronaut_id=astronaut_id, limit=limit)


@router.get("/{record_id}")
def get_record(record_id: str, state: AppState = Depends(get_state)) -> dict:
    """One full Record, including hash and signature."""
    record = state.store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no record {record_id!r}")
    return record


@router.get("/{record_id}/card")
def get_card(record_id: str, state: AppState = Depends(get_state)) -> dict:
    """The display card for one Record: tier, action, provenance, simulated labels."""
    record = state.store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no record {record_id!r}")
    return build_card(record)
