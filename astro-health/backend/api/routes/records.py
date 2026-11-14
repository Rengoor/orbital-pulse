"""List and fetch signed records and cards.

Owner: person A
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.earth.verify import verify_chain
from backend.records.acknowledge import build_ack
from backend.records.cards import build_card, build_trust_summary

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


class AckRequest(BaseModel):
    acknowledged_by: str
    note: str = ""


@router.post("/{record_id}/ack")
def acknowledge(record_id: str, body: AckRequest, state: AppState = Depends(get_state)) -> dict:
    """Log that someone saw this verdict. Changes nothing about the verdict.

    The acknowledgement is signed and appended to its own hash-linked chain,
    so Earth can later distinguish "shown to the crew" from "confirmed seen".
    """
    if state.store.get(record_id) is None:
        raise HTTPException(status_code=404, detail=f"no record {record_id!r}")
    try:
        ack = build_ack(
            record_id,
            body.acknowledged_by,
            note=body.note,
            signing_key=state.signing_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return state.store.add_ack(ack, signing_key=state.signing_key)


@router.get("/{record_id}/acks")
def list_acks(record_id: str, state: AppState = Depends(get_state)) -> dict:
    """Acknowledgements of one Record, oldest first, with chain integrity."""
    if state.store.get(record_id) is None:
        raise HTTPException(status_code=404, detail=f"no record {record_id!r}")
    valid, broken_at = state.store.verify_acks()
    return {
        "acks": state.store.acks(record_id),
        "chain": {"valid": valid, "broken_at": broken_at},
    }


@router.get("/{record_id}/trust")
def get_trust(record_id: str, state: AppState = Depends(get_state)) -> dict:
    """Data for the "Why should I trust this decision?" panel."""
    record = state.store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no record {record_id!r}")
    chain = verify_chain(state.store.all(), upto_record_id=record_id)
    return build_trust_summary(record, chain["valid"], state.store.reviews(record_id))
