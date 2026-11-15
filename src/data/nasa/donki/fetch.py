"""Pull one DONKI event window.

Source: NASA CCMC DONKI (Space Weather Database Of Notifications, Knowledge,
Information). Pulls solar flares, solar energetic particle events, geomagnetic
storms and coronal mass ejections for a window and writes one compact file.
The default window is the May 2024 storm (X-class flares from active region
13664, an SEP event, and a Kp 9 geomagnetic storm on 10-11 May).

Uses the CCMC web service, which needs no key. api.nasa.gov/DONKI serves the
same data but its shared DEMO_KEY is limited to 30 requests an hour per
network; set NASA_API_KEY to use that route instead.

    python -m data.nasa.donki.fetch [--start 2024-05-08] [--end 2024-05-14]

Owner: person D
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from data.nasa.common import download, utc_now, write_processed

CCMC_URL = "https://ccmc.gsfc.nasa.gov/DONKI/WS/get/{kind}"
API_NASA_URL = "https://api.nasa.gov/DONKI/{kind}"
PROCESSED_DIR = Path(__file__).resolve().parent / "processed"
EVENTS_PATH = PROCESSED_DIR / "event_window.json"

DEFAULT_START = "2024-05-08"
DEFAULT_END = "2024-05-14"


def _get(kind: str, start: str, end: str) -> list[dict]:
    params = [("startDate", start), ("endDate", end)]
    key = os.environ.get("NASA_API_KEY")
    if key and key != "DEMO_KEY":
        url, params = API_NASA_URL.format(kind=kind), params + [("api_key", key)]
    else:
        url = CCMC_URL.format(kind=kind)
    body = download(url, f"donki_{kind}_{start}_{end}.json", params=params)
    return json.loads(body or b"[]") or []


def fetch(start: str = DEFAULT_START, end: str = DEFAULT_END) -> dict:
    """Download the window and write processed/event_window.json."""
    flares = [
        {
            "id": f["flrID"],
            "class": f.get("classType"),
            "begin": f.get("beginTime"),
            "peak": f.get("peakTime"),
            "end": f.get("endTime"),
            "active_region": f.get("activeRegionNum"),
            "source_location": f.get("sourceLocation"),
            "link": f.get("link"),
        }
        for f in _get("FLR", start, end)
    ]
    particle_events = [
        {
            "id": s["sepID"],
            "time": s.get("eventTime"),
            "instruments": [i.get("displayName") for i in s.get("instruments") or []],
            "linked": [e.get("activityID") for e in s.get("linkedEvents") or []],
            "link": s.get("link"),
        }
        for s in _get("SEP", start, end)
    ]
    storms = [
        {
            "id": g["gstID"],
            "start": g.get("startTime"),
            "kp_max": max((k.get("kpIndex") or 0 for k in g.get("allKpIndex") or []), default=None),
            "kp": [{"time": k.get("observedTime"), "kp": k.get("kpIndex"), "source": k.get("source")} for k in g.get("allKpIndex") or []],
            "link": g.get("link"),
        }
        for g in _get("GST", start, end)
    ]
    ejections = [
        {
            "id": c["activityID"],
            "start": c.get("startTime"),
            "source_location": c.get("sourceLocation"),
            "active_region": c.get("activeRegionNum"),
            "speed_km_s": next((a.get("speed") for a in c.get("cmeAnalyses") or [] if a.get("isMostAccurate")), None),
            "link": c.get("link"),
        }
        for c in _get("CME", start, end)
    ]

    x_class = [f for f in flares if (f["class"] or "").startswith("X")]
    payload = {
        "source": "NASA CCMC DONKI",
        "url": "https://ccmc.gsfc.nasa.gov/tools/DONKI/",
        "dataset_id": "DONKI",
        "fetched_at": utc_now(),
        "window": {"start": start, "end": end},
        "summary": {
            "flares": len(flares),
            "x_class_flares": len(x_class),
            "strongest_flare": max(x_class or flares, key=lambda f: float((f["class"] or "A0")[1:] or 0), default={}).get("class"),
            "particle_events": len(particle_events),
            "geomagnetic_storms": len(storms),
            "kp_max": max((s["kp_max"] or 0 for s in storms), default=None),
            "coronal_mass_ejections": len(ejections),
        },
        "flares": flares,
        "particle_events": particle_events,
        "geomagnetic_storms": storms,
        "coronal_mass_ejections": ejections,
    }
    write_processed(EVENTS_PATH, payload)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    args = parser.parse_args()
    result = fetch(args.start, args.end)
    print(json.dumps(result["summary"], indent=2))
    print(f"-> {EVENTS_PATH}")
