"""decide(readings, baselines, rules, now) -> Record. Runs pipelines blind, calls the Checker, builds the record. Pure core: no clock, no database, no network inside.

Owner: person A
"""

import json
from pathlib import Path

import jsonschema

# STUB: returns fixture until A-02 through A-08 are complete

# Resolve paths relative to this file so they work regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
_FIXTURE_PATH = _REPO_ROOT / "data" / "fixtures" / "sample_record.json"
_SCHEMA_PATH = _REPO_ROOT / "data" / "schemas" / "record.schema.json"

# Load schema once at import time.
with open(_SCHEMA_PATH) as _f:
    _RECORD_SCHEMA = json.load(_f)


def decide(
    readings: list[dict],
    baselines: dict,
    rules: dict,
    now,  # datetime
) -> dict:
    """Return a stub Record from the fixture, stamped with the caller's context.

    Loads sample_record.json, stamps astronaut_id and ts, validates against
    record.schema.json, and returns the record dict.  No network or database
    access; the only I/O is reading the two static JSON files.
    """
    with open(_FIXTURE_PATH) as f:
        record = json.load(f)

    # Stamp the actual astronaut_id so callers can test filtering.
    record["astronaut_id"] = (
        readings[0]["astronaut_id"] if readings else "crew_1"
    )

    # Stamp the caller-supplied timestamp (no datetime.now() here).
    record["ts"] = now.isoformat() + "Z"

    # A-01.2 — validate before returning; raise ValueError with a clear message.
    try:
        jsonschema.validate(instance=record, schema=_RECORD_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Fixture record failed record.schema.json validation: {exc.message}"
        ) from exc

    return record
