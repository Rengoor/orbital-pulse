"""The link to Earth: how far away it is, so how long an answer takes.

GET shows the current link and the presets; POST changes it (a demo control:
on a real vehicle this would come from navigation and comms). Changing the link
never touches any verdict; it only affects handoffs computed afterwards and
when ground reviews reach the crew.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.downlink.delay import DISTANCES_KM
from backend.records.handoff import link_for

router = APIRouter()


def _presets() -> list[dict]:
    return [link_for(p) for p in DISTANCES_KM]


@router.get("")
def get_link(state: AppState = Depends(get_state)) -> dict:
    return {"link": state.link, "presets": _presets(),
            "ground_turnaround_s": state.autonomy_policy.get("ground_turnaround_s")}


class LinkRequest(BaseModel):
    preset: str | None = None
    one_way_delay_s: float | None = None
    label: str | None = None


@router.post("")
def set_link(body: LinkRequest, state: AppState = Depends(get_state)) -> dict:
    if body.preset is None and body.one_way_delay_s is None:
        raise HTTPException(status_code=422, detail="give a preset or a one_way_delay_s")
    try:
        state.link = link_for(body.preset, body.one_way_delay_s, body.label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"link": state.link}
