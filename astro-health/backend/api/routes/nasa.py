"""Real NASA data behind the decisions: blood panels, radiation, space weather.

Read-only. Serves the small processed files built by the fetchers under
data/nasa/. Each response names its dataset, field, unit and fetch time, so
anything a view shows can be traced to its source. When a file has not been
fetched the route says so (404) and never substitutes sample data.

Owner: person A
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_NASA_DIR = Path(__file__).resolve().parents[3] / "data" / "nasa"

FILES = {
    "blood_panels": _NASA_DIR / "osdr_inspiration4" / "processed" / "blood_panels.json",
    "baselines": _NASA_DIR / "osdr_inspiration4" / "processed" / "baselines.json",
    "baselines_provenance": _NASA_DIR / "osdr_inspiration4" / "processed" / "baselines_provenance.json",
    "radiation": _NASA_DIR / "radlab" / "processed" / "dose_rates.json",
    "space_weather": _NASA_DIR / "donki" / "processed" / "event_window.json",
}

_HOW_TO_FETCH = {
    "blood_panels": "python -m data.nasa.osdr_inspiration4.fetch",
    "baselines": "python -m data.nasa.osdr_inspiration4.build_baselines",
    "baselines_provenance": "python -m data.nasa.osdr_inspiration4.build_baselines",
    "radiation": "python -m data.nasa.radlab.fetch",
    "space_weather": "python -m data.nasa.donki.fetch",
}


def _load(name: str) -> dict | None:
    path = FILES[name]
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _require(name: str) -> dict:
    data = _load(name)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"NASA data '{name}' has not been fetched. Run: {_HOW_TO_FETCH[name]}",
        )
    return data


@router.get("/sources")
def sources() -> dict:
    """What real NASA data is loaded, where it came from and when."""
    panels, radiation, weather = _load("blood_panels"), _load("radiation"), _load("space_weather")
    return {
        "sources": [
            {
                "id": "blood_panels",
                "name": "Inspiration4 blood panels (CBC and metabolic)",
                "provider": "NASA OSDR",
                "available": panels is not None,
                "datasets": [d["dataset_id"] for d in panels["datasets"]] if panels else ["OSD-569", "OSD-575"],
                "fetched_at": panels["fetched_at"] if panels else None,
                "detail": f"{len(panels['subjects'])} crew, {sum(d['rows'] for d in panels['datasets'])} results" if panels else None,
                "used_for": "Personal baselines for the statistical pipeline; reference for clinicians",
            },
            {
                "id": "radiation",
                "name": "Measured absorbed dose rates",
                "provider": "NASA OSDR RadLab",
                "available": radiation is not None,
                "datasets": ["RadLab"],
                "fetched_at": radiation["fetched_at"] if radiation else None,
                "detail": (
                    f"{len(radiation['series'])} instruments, {radiation['window']['start'][:10]} to {radiation['window']['end'][:10]}"
                    if radiation else None
                ),
                "used_for": "Radiation context for clinicians. Not fed to the decision pipelines (absorbed dose, not dose equivalent)",
            },
            {
                "id": "space_weather",
                "name": "Space weather events",
                "provider": "NASA CCMC DONKI",
                "available": weather is not None,
                "datasets": ["DONKI"],
                "fetched_at": weather["fetched_at"] if weather else None,
                "detail": (
                    f"{weather['summary']['flares']} flares, {weather['summary']['particle_events']} particle events, Kp max {weather['summary']['kp_max']}"
                    if weather else None
                ),
                "used_for": "Event timeline for the storm window",
            },
        ]
    }


@router.get("/space-weather")
def space_weather() -> dict:
    """DONKI flares, particle events, geomagnetic storms and CMEs for the fetched window."""
    return _require("space_weather")


@router.get("/radiation")
def radiation(hourly: bool = True) -> dict:
    """RadLab absorbed dose rates per instrument. ``hourly=false`` returns the summary only."""
    data = _require("radiation")
    if not hourly:
        data = {**data, "series": [{k: v for k, v in s.items() if k != "hourly"} for s in data["series"]]}
    return data


@router.get("/blood-panels")
def blood_panels(subject: str | None = None) -> dict:
    """Inspiration4 CBC and metabolic panel results, with the laboratory reference ranges."""
    data = _require("blood_panels")
    if subject is not None:
        if subject not in data["subjects"]:
            raise HTTPException(status_code=404, detail=f"no subject {subject!r} in the dataset")
        data = {**data, "subjects": {subject: data["subjects"][subject]}}
    return data


@router.get("/baselines")
def baselines() -> dict:
    """The pre-flight draws the statistical pipeline uses as personal baselines."""
    return {"baselines": _require("baselines"), "provenance": _load("baselines_provenance")}
