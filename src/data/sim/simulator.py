"""Daily-vitals simulator (BP, HR, glucose, temperature, sleep, mood, CO2, exercise). Seeded, labelled simulated.

Posts check-ins to a running backend so the tablet and Earth base views have
live data. Every value it generates is labelled ``simulated``. The one real
input is blood glucose: when the Inspiration4 panels have been fetched, each
crew member's glucose is their actual post-flight draw from NASA OSDR OSD-575,
sent with its dataset reference.

    python -m data.sim.simulator                      # four crew, one check-in each, every 10 s
    python -m data.sim.simulator --once               # one round, then stop
    python -m data.sim.simulator --storm              # dose rate climbs past its limit over the run
    python -m data.sim.simulator --fault heart_rate   # crew 1's heart-rate sensor reports a fault

Owner: person D
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_PANELS = Path(__file__).resolve().parents[1] / "nasa" / "osdr_inspiration4" / "processed" / "blood_panels.json"

# Crew ids are the Inspiration4 dataset's own subject ids, so real baselines apply.
CREW = ["C001", "C002", "C003", "C004"]

# (channel, unit, typical value, spread)
VITALS = [
    ("heart_rate", "bpm", 70.0, 4.0),
    ("bp_systolic", "mmHg", 118.0, 5.0),
    ("bp_diastolic", "mmHg", 76.0, 4.0),
    ("temperature", "C", 36.8, 0.15),
    ("sleep_hours", "h", 7.2, 0.4),
    ("mood", "score_1_10", 7.0, 0.6),
    ("co2_ppm", "ppm", 2400.0, 150.0),
    ("exercise_minutes", "min", 45.0, 8.0),
    ("dose_rate_usv_h", "uSv/h", 12.0, 1.5),
]


def _real_glucose() -> dict[str, dict]:
    """Each subject's first post-flight glucose draw, with its provenance."""
    if not _PANELS.is_file():
        return {}
    panels = json.loads(_PANELS.read_text(encoding="utf-8"))
    out = {}
    for subject_id, subject in panels["subjects"].items():
        analyte = subject["analytes"].get("GLUCOSE")
        draw = next((d for d in (analyte or {}).get("draws", []) if d["timepoint"].startswith("R+") and d["value"] is not None), None)
        if draw:
            out[subject_id] = {"value": draw["value"], "dataset_id": analyte["dataset_id"], "timepoint": draw["timepoint"]}
    return out


def build_readings(crew_id: str, rng: random.Random, round_no: int, storm: bool, fault: str | None, glucose: dict) -> list[dict]:
    ts = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"
    readings = []
    for channel, unit, typical, spread in VITALS:
        value = rng.gauss(typical, spread)
        if storm and channel == "dose_rate_usv_h":
            value = typical + 30.0 * round_no  # crosses yellow (50) on round 2, red (200) on round 7
        reading = {
            "id": f"{crew_id}-{channel}-{round_no}",
            "ts": ts,
            "channel": channel,
            "value": round(max(value, 0.0), 2),
            "unit": unit,
            "source": "simulated",
            "quality": "fault" if fault == channel and crew_id == CREW[0] else "ok",
        }
        readings.append(reading)
    real = glucose.get(crew_id)
    if real:
        readings.append({
            "id": f"{crew_id}-glucose-{round_no}",
            "ts": ts,
            "channel": "glucose",
            "value": real["value"],
            "unit": "mg/dL",
            "source": "nasa_osdr",
            "quality": "ok",
            "provenance": {"dataset_id": real["dataset_id"], "field": "GLUCOSE", "timestamp": real["timepoint"]},
        })
    return readings


def post_checkin(url: str, crew_id: str, readings: list[dict]) -> dict:
    body = json.dumps({"astronaut_id": crew_id, "readings": readings}).encode("utf-8")
    request = urllib.request.Request(url.rstrip("/") + "/checkin", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="backend address")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between rounds")
    parser.add_argument("--rounds", type=int, default=0, help="stop after this many rounds (0 = run until interrupted)")
    parser.add_argument("--once", action="store_true", help="one round, then stop")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--storm", action="store_true", help="dose rate climbs past its limits")
    parser.add_argument("--fault", metavar="CHANNEL", help="first crew member's sensor on this channel reports a fault")
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    glucose = _real_glucose()
    rounds = 1 if args.once else args.rounds
    round_no = 0
    try:
        while True:
            round_no += 1
            for crew_id in CREW:
                result = post_checkin(args.url, crew_id, build_readings(crew_id, rng, round_no, args.storm, args.fault, glucose))
                verdict = result["verdict"]
                print(f"round {round_no:3} {crew_id}  {verdict['tier']:6} {verdict['action']}")
            if rounds and round_no >= rounds:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"error: cannot reach the backend at {args.url}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
