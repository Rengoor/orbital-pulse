"""Download Inspiration4 CBC / biochemical panels from OSDR.

Source: NASA Open Science Data Repository, SpaceX Inspiration4 mission.
  OSD-569  Complete Blood Count (CBC)
  OSD-575  Comprehensive Metabolic Panel (CMP)
Four crew (C001-C004), seven draws each: L-92, L-44, L-3 before launch and
R+1, R+45, R+82, R+194 after return. Each row carries the laboratory's own
reference range, which is kept and never replaced by a project threshold.

    python -m data.nasa.osdr_inspiration4.fetch

Owner: person D
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from data.nasa.common import download, utc_now, write_processed

PROCESSED_DIR = Path(__file__).resolve().parent / "processed"
PANELS_PATH = PROCESSED_DIR / "blood_panels.json"

_DOWNLOAD = "https://osdr.nasa.gov/geode-py/ws/studies/{study}/download"
PANELS = [
    {"dataset_id": "OSD-569", "panel": "CBC", "file": "LSDS-7_Complete_Blood_Count_CBC.upload_SUBMITTED.csv"},
    {"dataset_id": "OSD-575", "panel": "CMP", "file": "LSDS-8_Comprehensive_Metabolic_Panel_CMP.upload_SUBMITTED.csv"},
]


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None  # "NA", "N/A", blank


def _timepoint_order(timepoint: str) -> tuple[int, int]:
    # L-92 < L-44 < L-3 < R+1 < R+45 ...
    phase, _, days = timepoint.partition("-") if timepoint.startswith("L") else timepoint.partition("+")
    return (0, -int(days)) if phase == "L" else (1, int(days))


def fetch() -> dict:
    """Download both panels and write processed/blood_panels.json."""
    subjects: dict[str, dict] = {}
    sources = []

    for panel in PANELS:
        url = _DOWNLOAD.format(study=panel["dataset_id"])
        body = download(url, f"{panel['dataset_id']}_{panel['panel']}.csv",
                        params=[("source", "datamanager"), ("file", panel["file"])])
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
        sources.append({**panel, "url": f"https://osdr.nasa.gov/bio/repo/data/studies/{panel['dataset_id']}", "rows": len(rows)})

        for row in rows:
            subject = subjects.setdefault(row["SUBJECT_ID"], {"sex": row.get("SEX"), "analytes": {}})
            analyte = subject["analytes"].setdefault(
                row["ANALYTE"],
                {
                    "panel": panel["panel"],
                    "dataset_id": panel["dataset_id"],
                    "unit": row.get("UNITS"),
                    "range_min": _number(row.get("RANGE_MIN")),
                    "range_max": _number(row.get("RANGE_MAX")),
                    "range_basis": "laboratory reference range as published in the dataset",
                    "draws": [],
                },
            )
            # The CMP file calls the draw column "timepoint", the CBC file "TEST_DATE".
            timepoint = row.get("timepoint") or row.get("TEST_DATE")
            analyte["draws"].append({"timepoint": timepoint, "value": _number(row.get("VALUE"))})

    for subject in subjects.values():
        for analyte in subject["analytes"].values():
            analyte["draws"].sort(key=lambda d: _timepoint_order(d["timepoint"]))

    payload = {
        "source": "NASA OSDR, SpaceX Inspiration4",
        "fetched_at": utc_now(),
        "datasets": sources,
        "timepoints": "L-n = n days before launch, R+n = n days after return",
        "subjects": dict(sorted(subjects.items())),
    }
    write_processed(PANELS_PATH, payload)
    return payload


if __name__ == "__main__":
    result = fetch()
    for source in result["datasets"]:
        print(f"{source['dataset_id']} {source['panel']}: {source['rows']} rows")
    print(f"{len(result['subjects'])} subjects -> {PANELS_PATH}")
