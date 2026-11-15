"""Build per-astronaut baselines from pre-flight draws.

Reads processed/blood_panels.json (run fetch.py first) and writes
processed/baselines.json in the shape pipeline A loads:

    {"C001": {"glucose": [83.0, 80.0, 91.0]}, ...}

Only the three pre-flight draws (L-92, L-44, L-3) are baseline material; the
post-flight draws are what a baseline is compared against. Only analytes that
map onto a reading channel are included. Three draws is a small baseline, so
pipeline A marks it low-confidence and uses a wide band.

    python -m data.nasa.osdr_inspiration4.build_baselines

Owner: person D
"""

from __future__ import annotations

from pathlib import Path

from data.nasa.common import read_processed, utc_now, write_processed
from data.nasa.osdr_inspiration4.fetch import PANELS_PATH

PROCESSED_DIR = Path(__file__).resolve().parent / "processed"
BASELINES_PATH = PROCESSED_DIR / "baselines.json"
PROVENANCE_PATH = PROCESSED_DIR / "baselines_provenance.json"

# Dataset analyte -> reading channel (see data/schemas/reading.schema.json).
ANALYTE_TO_CHANNEL = {"GLUCOSE": "glucose"}


def build() -> dict:
    panels = read_processed(PANELS_PATH)
    if panels is None:
        raise SystemExit(f"{PANELS_PATH} not found: run `python -m data.nasa.osdr_inspiration4.fetch` first")

    baselines: dict[str, dict[str, list[float]]] = {}
    provenance: dict[str, dict] = {}
    for subject_id, subject in panels["subjects"].items():
        for analyte_name, channel in ANALYTE_TO_CHANNEL.items():
            analyte = subject["analytes"].get(analyte_name)
            if not analyte:
                continue
            draws = [d for d in analyte["draws"] if d["timepoint"].startswith("L-") and d["value"] is not None]
            if not draws:
                continue
            baselines.setdefault(subject_id, {})[channel] = [d["value"] for d in draws]
            provenance.setdefault(subject_id, {})[channel] = {
                "dataset_id": analyte["dataset_id"],
                "field": analyte_name,
                "unit": analyte["unit"],
                "timepoints": [d["timepoint"] for d in draws],
            }

    write_processed(BASELINES_PATH, baselines)
    write_processed(
        PROVENANCE_PATH,
        {
            "source": panels["source"],
            "built_at": utc_now(),
            "note": "Baselines are real Inspiration4 pre-flight draws. Subject ids are the dataset's own (C001-C004).",
            "baselines": provenance,
        },
    )
    return baselines


if __name__ == "__main__":
    built = build()
    for subject_id, channels in built.items():
        print(subject_id, {channel: values for channel, values in channels.items()})
    print(f"-> {BASELINES_PATH}")
