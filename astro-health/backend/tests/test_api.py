"""Tests for api.

Owner: person A
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app

_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "astro-health"
_SCHEMA_PATH = _ROOT / "data" / "schemas" / "record.schema.json"

with open(_SCHEMA_PATH) as _f:
    _RECORD_SCHEMA = json.load(_f)


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# A-01.3: /checkin returns HTTP 200 with a schema-valid Record verdict summary
# ---------------------------------------------------------------------------

def test_checkin_returns_200_with_no_readings(client):
    resp = client.post("/checkin", json={"astronaut_id": "crew_1", "readings": []})
    assert resp.status_code == 200
    data = resp.json()
    assert "record_id" in data
    assert "verdict" in data


def test_checkin_stamps_astronaut_id(client):
    """decide() should stamp the astronaut_id from the request onto the record."""
    resp = client.post(
        "/checkin",
        json={
            "astronaut_id": "crew_42",
            "readings": [
                {
                    "id": "r1",
                    "astronaut_id": "crew_42",
                    "ts": "2026-11-14T08:00:00Z",
                    "channel": "heart_rate",
                    "value": 72.0,
                    "unit": "bpm",
                    "source": "simulated",
                }
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["record_id"] is not None


def test_checkin_response_record_id_is_string(client):
    resp = client.post("/checkin", json={"astronaut_id": "crew_1", "readings": []})
    assert resp.status_code == 200
    assert isinstance(resp.json()["record_id"], str)


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# A-01.1 / A-01.2: decide() stamps fields and validates against schema
# ---------------------------------------------------------------------------

def test_decide_stamps_astronaut_id():
    from backend.orchestrator import decide

    now = datetime(2026, 11, 14, 8, 0, 0)
    readings = [{"astronaut_id": "crew_7"}]
    record = decide(readings=readings, baselines={}, rules={}, now=now)
    assert record["astronaut_id"] == "crew_7"


def test_decide_stamps_ts():
    from backend.orchestrator import decide

    now = datetime(2026, 11, 14, 8, 0, 0)
    record = decide(readings=[], baselines={}, rules={}, now=now)
    assert record["ts"] == "2026-11-14T08:00:00Z"


def test_decide_default_astronaut_id_when_no_readings():
    from backend.orchestrator import decide

    now = datetime(2026, 11, 14, 8, 0, 0)
    record = decide(readings=[], baselines={}, rules={}, now=now)
    assert record["astronaut_id"] == "crew_1"


def test_decide_output_passes_record_schema():
    from backend.orchestrator import decide

    now = datetime(2026, 11, 14, 8, 0, 0)
    record = decide(readings=[], baselines={}, rules={}, now=now)
    # Should not raise
    jsonschema.validate(instance=record, schema=_RECORD_SCHEMA)
