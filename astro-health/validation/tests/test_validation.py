"""The REAL NASA validation snapshot: intact, labelled, and matched by the report."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from backend.orchestrator import decide, load_rules
from validation import run

HERE = Path(__file__).resolve().parents[1]
DATA, RESULTS = HERE / "data", HERE / "results"


def _manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def test_snapshot_matches_its_manifest():
    manifest = _manifest()
    assert manifest["label"].startswith("REAL NASA DATA")
    for entry in manifest["files"]:
        digest = hashlib.sha256((DATA / entry["file"]).read_bytes()).hexdigest()
        assert digest == entry["sha256"], f"{entry['file']} changed since it was fetched from NASA"
        assert "nasa" in entry["source"].lower()


def test_sources_are_nasa_urls():
    queries = [e.get("query", "") for e in _manifest()["files"]]
    assert any(q.startswith("https://visualization.osdr.nasa.gov/radlab/api/") for q in queries)
    assert any(q.startswith("https://ccmc.gsfc.nasa.gov/DONKI/") for q in queries)
    glucose = json.loads((DATA / "inspiration4_glucose.json").read_text(encoding="utf-8"))
    assert glucose["url"].startswith("https://osdr.nasa.gov/") and glucose["dataset_id"] == "OSD-575"


def test_real_readings_are_labelled_and_accepted(monkeypatch):
    """A real ALTEA sample goes in as nasa_radlab with provenance and is judged, not rejected as unverifiable."""
    monkeypatch.setenv("SIGNING_KEY", "validation-test-key")
    row = next(csv.DictReader((DATA / "altea_dose_equivalent.csv").open(encoding="utf-8")))
    ts = row["timestamp"] + "Z"
    reading = {"id": "t", "astronaut_id": "iss", "ts": ts, "channel": "dose_rate_usv_h",
               "value": float(row["dose_equivalent_rate"]), "unit": "uSv/h", "source": "nasa_radlab",
               "provenance": {"dataset_id": "RadLab:ALTEA", "field": "dose_equivalent_rate", "timestamp": ts}}
    from datetime import datetime
    rec = decide([reading], {}, load_rules(), datetime.fromisoformat(row["timestamp"]))
    assert rec["integrity"]["readings"][0]["status"] == "valid"
    assert rec["verdict"]["tier"] in ("GREEN", "YELLOW", "RED")


def test_glucose_report_is_reproducible(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "validation-test-key")
    fresh = run.glucose()
    saved = json.loads((RESULTS / "validation.json").read_text(encoding="utf-8"))["glucose"]
    assert fresh["agreement"] == saved["agreement"]
    assert [(r["crew"], r["timepoint"], r["tier"]) for r in fresh["rows"]] == \
           [(r["crew"], r["timepoint"], r["tier"]) for r in saved["rows"]]


def test_radiation_report_covers_the_whole_snapshot():
    saved = json.loads((RESULTS / "validation.json").read_text(encoding="utf-8"))["radiation"]
    with (DATA / "altea_dose_equivalent.csv").open(encoding="utf-8") as f:
        rows = sum(1 for _ in f) - 1
    assert saved["samples"] == rows == sum(saved["verdicts"].values())
    assert saved["donki_sep_events"] == len(json.loads((DATA / "donki_sep.json").read_text(encoding="utf-8"))["events"])
