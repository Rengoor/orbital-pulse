"""Run REAL NASA measurements through the real decision system and report what it says.

    python -m validation.run [--no-write]

Uses only the committed snapshot in validation/data/ (see fetch.py), so it runs
offline and reproduces exactly. Every reading is labelled with its real NASA
source and provenance, and judged by the real orchestrator (decide()) at its own
timestamp, exactly as a live check-in would be.

1. Radiation, ISS, one quiet week (no solar particle event in NASA DONKI):
   each ALTEA dose-equivalent sample (uSv/h) is one check-in. Because no SEP was
   catalogued, any YELLOW/RED is a false alarm relative to the solar-storm record.
   Samples are also split by the ISS's latitude at the time (from RadLab), which
   shows where the alarms come from: geomagnetic shielding weakens towards the
   ISS's highest latitudes (about 51.6 degrees).

2. Glucose, SpaceX Inspiration4 (OSD-575): every crew draw is one check-in,
   with that crew member's personal baseline from pre-flight draws. The verdict
   is compared with the laboratory's own reference range published in the
   dataset (an independent standard).

The limits judged here are the project's placeholders (limits_table.yaml), so
this measures how those placeholders behave on real data. It is not a clinical
validation.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from backend.api.state import load_all_baselines
from backend.orchestrator import decide, load_rules

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"

LAT_BANDS = ((0, 20), (20, 35), (35, 45), (45, 60))   # |latitude| bands, degrees
# Public mission dates (SpaceX Inspiration4): launch 2021-09-16, splashdown 2021-09-18.
# The dataset gives draws relative to them (L-n / R+n days); absolute times are derived.
I4_LAUNCH, I4_RETURN = datetime(2021, 9, 16, 12, 0, 0), datetime(2021, 9, 18, 12, 0, 0)
TIERS = ("GREEN", "YELLOW", "RED", "GREY")


def _draw_time(tp: str) -> datetime:
    n = int(tp[2:])
    return I4_LAUNCH - timedelta(days=n) if tp.startswith("L-") else I4_RETURN + timedelta(days=n)


def _band(lat: float | None) -> str:
    if lat is None:
        return "unknown"
    for lo, hi in LAT_BANDS:
        if lo <= abs(lat) < hi:
            return f"{lo}-{hi}"
    return "unknown"


def radiation() -> dict:
    rules, manifest = load_rules(), json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    sep = json.loads((DATA / "donki_sep.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((DATA / "altea_dose_equivalent.csv").open(encoding="utf-8")))
    tiers, prev, values = Counter(), "GENESIS", []
    by_band: dict[str, Counter] = {f"{lo}-{hi}": Counter() for lo, hi in LAT_BANDS}
    examples = []
    for i, r in enumerate(rows):
        ts = r["timestamp"] + "Z"
        now = datetime.fromisoformat(r["timestamp"])
        value = float(r["dose_equivalent_rate"])
        reading = {"id": f"altea-{i}", "astronaut_id": "iss_altea", "ts": ts, "channel": "dose_rate_usv_h",
                   "value": value, "unit": "uSv/h", "source": "nasa_radlab", "quality": "ok",
                   "provenance": {"dataset_id": "RadLab:ALTEA", "field": "dose_equivalent_rate", "timestamp": ts}}
        rec = decide([reading], {}, rules, now, prev_hash=prev)
        prev = rec["hash"]
        tier = rec["verdict"]["tier"]
        tiers[tier] += 1
        values.append(value)
        lat, lon = (float(r["latitude"]), float(r["longitude"])) if r["latitude"] and r["longitude"] else (None, None)
        by_band.setdefault(_band(lat), Counter())[tier] += 1
        if tier != "GREEN" and len(examples) < 5:
            examples.append({"ts": ts, "value": round(value, 1), "lat": lat, "lon": lon, "tier": tier,
                             "rules": rec["verdict"].get("decision_trace", {}).get("triggered_rules", [])})
    alarms = tiers["YELLOW"] + tiers["RED"]
    values.sort()
    return {
        "source": "NASA OSDR RadLab, ALTEA on the ISS, dose_equivalent_rate (uSv/h)",
        "window": manifest["window"],
        "samples": len(rows),
        "donki_sep_events": len(sep["events"]),
        "verdicts": {t: tiers[t] for t in TIERS},
        "alarms": alarms,
        "false_alarm_share": round(alarms / len(rows), 4) if rows else None,
        "by_abs_latitude": {b: {t: c[t] for t in TIERS} for b, c in by_band.items() if sum(c.values())},
        "dose_uSv_h": {"median": round(values[len(values) // 2], 2), "p95": round(values[int(len(values) * 0.95)], 2),
                       "max": round(values[-1], 2)},
        "example_alarms": examples,
    }


def glucose() -> dict:
    snap = json.loads((DATA / "inspiration4_glucose.json").read_text(encoding="utf-8"))
    rules, baselines = load_rules(), load_all_baselines()
    rows, agree = [], Counter()
    for sid, g in sorted(snap["subjects"].items()):
        prev = "GENESIS"
        for d in g["draws"]:
            if d["value"] is None:
                continue
            t = _draw_time(d["timepoint"])
            ts = t.isoformat() + "Z"
            reading = {"id": f"{sid}-{d['timepoint']}", "astronaut_id": sid, "ts": ts, "channel": "glucose",
                       "value": d["value"], "unit": "mg/dL", "source": "nasa_osdr", "quality": "ok",
                       "provenance": {"dataset_id": "OSD-575", "field": "GLUCOSE", "timestamp": ts}}
            rec = decide([reading], baselines, rules, t, prev_hash=prev)
            prev = rec["hash"]
            tier = rec["verdict"]["tier"]
            in_range = g["range_min"] <= d["value"] <= g["range_max"]
            match = (tier == "GREEN") == in_range
            agree["agree" if match else ("system_flagged_in_range" if in_range else "system_missed_out_of_range")] += 1
            rows.append({"crew": sid, "timepoint": d["timepoint"], "value": d["value"], "lab_range": [g["range_min"], g["range_max"]],
                         "lab_in_range": in_range, "tier": tier,
                         "rules": rec["verdict"].get("decision_trace", {}).get("triggered_rules", [])})
    return {"source": "NASA OSDR OSD-575 (SpaceX Inspiration4, CMP), GLUCOSE mg/dL",
            "draws": len(rows), "agreement": dict(agree), "rows": rows}


def to_markdown(rad: dict, glu: dict) -> str:
    v, z = rad["verdicts"], rad["by_abs_latitude"]
    out = [
        "# Validation on REAL NASA data",
        "",
        "> **REAL NASA DATA.** Every number below comes from NASA measurements (snapshot in",
        "> `validation/data/`, sources and checksums in `manifest.json`), judged by the real",
        "> decision system. Generated by `python -m validation.run`. The limits being judged are",
        "> the project's placeholders, so this shows how they behave on real data. It is not a",
        "> clinical validation.",
        "",
        "## 1. Radiation: ISS, one quiet week",
        "",
        f"Source: {rad['source']}. Window {rad['window']['start']} to {rad['window']['end']}.",
        f"NASA DONKI lists **{rad['donki_sep_events']} solar energetic particle events** in this window, so",
        "no radiation storm was under way and every YELLOW or RED is a false alarm relative to the storm record.",
        "",
        "| Samples | GREEN | YELLOW | RED | GREY | False-alarm share |",
        "|---|---|---|---|---|---|",
        f"| {rad['samples']} | {v['GREEN']} | {v['YELLOW']} | {v['RED']} | {v['GREY']} | {rad['false_alarm_share']:.1%} |",
        "",
        "Where the alarms happen, by the ISS's latitude at the time of the sample:",
        "",
        "| ISS latitude (absolute) | Samples | GREEN | YELLOW | RED | Alarm share |",
        "|---|---|---|---|---|---|",
        *[f"| {b} deg | {sum(c.values())} | {c['GREEN']} | {c['YELLOW']} | {c['RED']} | "
          f"{(c['YELLOW'] + c['RED']) / sum(c.values()):.1%} |" for b, c in z.items()],
        "",
        f"Dose-equivalent rate: median {rad['dose_uSv_h']['median']}, 95th percentile {rad['dose_uSv_h']['p95']}, "
        f"max {rad['dose_uSv_h']['max']} uSv/h. Project limits: YELLOW above 50, RED above 200 uSv/h.",
        "",
        "**Finding.** The placeholder dose-rate limits fire on routine ISS orbits with no solar storm,",
        "and the alarm rate climbs with latitude, where Earth's magnetic field shields less. An alarm",
        "on instantaneous dose rate is therefore not fit for crew use as it stands. It needs an",
        "orbit-aware or time-averaged rule (for example, judging the mean over an orbit, or comparing",
        "with the expected rate for the position). That rule belongs in the backend Checker policy and",
        "needs review; it is not changed here.",
        "",
        "## 2. Glucose: SpaceX Inspiration4 crew",
        "",
        f"Source: {glu['source']}. Each draw judged with that crew member's personal baseline;",
        "the verdict is compared with the laboratory's reference range published in the dataset.",
        "",
        "| Crew | Draw | Glucose (mg/dL) | Lab range | Lab says | System verdict | Rules |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in glu["rows"]:
        out.append(f"| {r['crew']} | {r['timepoint']} | {r['value']:g} | {r['lab_range'][0]:g}-{r['lab_range'][1]:g} | "
                   f"{'in range' if r['lab_in_range'] else 'OUT of range'} | {r['tier']} | {', '.join(r['rules']) or '-'} |")
    a = glu["agreement"]
    out += [
        "",
        f"Agreement with the lab: {a.get('agree', 0)} of {glu['draws']} draws. "
        f"System flagged an in-range value: {a.get('system_flagged_in_range', 0)}. "
        f"System missed an out-of-range value: {a.get('system_missed_out_of_range', 0)}.",
        "",
        "The project's glucose limits (YELLOW below 70 or above 180 mg/dL) are wider than a fasting",
        "lab range (65-99 mg/dL) on the high side and tighter on the low side, so disagreements show",
        "exactly where the placeholders differ from a clinical laboratory's reference.",
        "",
        "All three RED verdicts come from the same draw (R+45) in three different crew members. The",
        "system reports what the data says; whether those values reflect physiology or sample handling",
        "at that draw is not established here.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    rad, glu = radiation(), glucose()
    md = to_markdown(rad, glu)
    if not args.no_write:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "validation.md").write_text(md, encoding="utf-8", newline="\n")
        (RESULTS / "validation.json").write_text(json.dumps({"radiation": rad, "glucose": glu}, indent=2) + "\n",
                                                 encoding="utf-8", newline="\n")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
