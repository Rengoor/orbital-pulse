"""Fetch the REAL NASA data used to validate the decision system.

    python -m validation.fetch [--start 2010-11-01T00:00] [--end 2010-11-08T00:00]

Downloads, straight from NASA, into validation/data/ (a committed snapshot, so
the validation reproduces offline):

  altea_dose_equivalent.csv   NASA OSDR RadLab Data API, instrument ALTEA on the
                              ISS: dose_equivalent_rate in uSv/hour (the unit of
                              the backend's dose_rate_usv_h channel, per the
                              RadLab Data API documentation), with the ISS's
                              latitude and longitude for each sample.
  donki_sep.json              NASA CCMC DONKI: solar energetic particle (SEP)
                              events catalogued in the same window, the
                              independent record of when a radiation storm was
                              actually happening.
  inspiration4_glucose.json   NASA OSDR OSD-575 (SpaceX Inspiration4, CMP panel):
                              every crew member's glucose at all seven draws,
                              with the laboratory's own reference range.
  manifest.json               Source URLs, query, fetch time and SHA-256 of each file.

Nothing here is simulated or altered: values are written as NASA returned them.
Only ALTEA reports dose_equivalent_rate in RadLab (checked 2026-11-15: DosTel,
TEPC, IV-TEPC, RAD, Lidal, REM and Liulin-5 return no such values), and its
public data covers 2010-2011, so the window is in that period.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

from data.nasa.common import download, utc_now

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RADLAB_URL = "https://visualization.osdr.nasa.gov/radlab/api/"
DONKI_URL = "https://ccmc.gsfc.nasa.gov/DONKI/WS/get/SEP"
OSDR_GLUCOSE_SOURCE = HERE.parent / "data" / "nasa" / "osdr_inspiration4" / "processed" / "blood_panels.json"

DEFAULT_START = "2010-11-01T00:00"
DEFAULT_END = "2010-11-08T00:00"
ALTEA_FIELDS = ("timestamp", "instrument_id", "dose_equivalent_rate", "latitude", "longitude")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_altea(start: str, end: str) -> dict:
    params = [("instrument", "ALTEA"), (f"timestamp>={start}", None), (f"timestamp<{end}", None),
              ("dose_equivalent_rate", None), ("instrument_id", None), ("latitude", None),
              ("longitude", None), ("format", "csv")]
    body = download(RADLAB_URL, f"validation_altea_{start[:10]}_{end[:10]}.csv", params=params, timeout=600.0)
    rows = [r for r in csv.DictReader(io.StringIO(body.decode("utf-8"))) if r.get("dose_equivalent_rate")]
    if not rows:
        raise SystemExit(f"RadLab returned no ALTEA dose_equivalent_rate rows for {start}..{end}")
    out = DATA / "altea_dose_equivalent.csv"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=ALTEA_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["timestamp"], r["instrument_id"])):
            w.writerow({k: r.get(k, "") for k in ALTEA_FIELDS})
    query = RADLAB_URL + "?" + "&".join(urllib.parse.quote(k, safe="<>=:") + ("=" + v if v else "") for k, v in params)
    return {"file": out.name, "source": "NASA OSDR RadLab Data API", "instrument": "ALTEA (ISS)",
            "field": "dose_equivalent_rate", "unit": "uSv/h", "query": query, "rows": len(rows)}


def fetch_donki_sep(start: str, end: str) -> dict:
    url = f"{DONKI_URL}?startDate={start[:10]}&endDate={end[:10]}"
    request = urllib.request.Request(url, headers={"User-Agent": "src-validation/0.1"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        raw = resp.read().decode("utf-8").strip()
    events = json.loads(raw) if raw else []
    out = DATA / "donki_sep.json"
    out.write_text(json.dumps({"source": "NASA CCMC DONKI", "url": url, "window": [start + "Z", end + "Z"],
                               "events": events}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"file": out.name, "source": "NASA CCMC DONKI (SEP)", "query": url, "events": len(events)}


def fetch_glucose() -> dict:
    """Re-download the Inspiration4 panels from OSDR, then keep glucose only."""
    from data.nasa.osdr_inspiration4 import fetch as osdr_fetch
    osdr_fetch.fetch()   # writes data/nasa/osdr_inspiration4/processed/blood_panels.json from OSDR
    panels = json.loads(OSDR_GLUCOSE_SOURCE.read_text(encoding="utf-8"))
    subjects = {sid: s["analytes"]["GLUCOSE"] for sid, s in panels["subjects"].items() if "GLUCOSE" in s["analytes"]}
    out = DATA / "inspiration4_glucose.json"
    out.write_text(json.dumps({"source": panels["source"], "dataset_id": "OSD-575",
                               "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-575",
                               "fetched_at": panels["fetched_at"], "timepoints": panels["timepoints"],
                               "subjects": subjects}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"file": out.name, "source": "NASA OSDR OSD-575 (Inspiration4 CMP)", "field": "GLUCOSE",
            "unit": "mg/dL", "subjects": len(subjects)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    args = ap.parse_args(argv)
    DATA.mkdir(parents=True, exist_ok=True)
    entries = [fetch_altea(args.start, args.end), fetch_donki_sep(args.start, args.end), fetch_glucose()]
    for e in entries:
        e["sha256"] = _sha256(DATA / e["file"])
    manifest = {"label": "REAL NASA DATA. Not simulated, not altered.", "fetched_at": utc_now(),
                "window": {"start": args.start + "Z", "end": args.end + "Z"}, "files": entries}
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    for e in entries:
        print(f"{e['file']}: {e.get('rows', e.get('events', e.get('subjects')))} from {e['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
