"""Tests for the NASA data routes, the red-team suite, the stuck-sensor guard and the simulator.

Owner: person A and person D
"""

import asyncio
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import jsonschema
import pytest
import yaml

from backend.api.main import create_app
from backend.api.routes import nasa as nasa_routes
from backend.checker import input_gate
from backend.orchestrator import decide
from data.sim import simulator
from evidence.redteam import run_redteam

_REPO = Path(__file__).resolve().parents[2]
with open(_REPO / "backend" / "checker" / "policy.yaml") as _f:
    POLICY = yaml.safe_load(_f)
with open(_REPO / "data" / "schemas" / "reading.schema.json") as _f:
    _READING_SCHEMA = json.load(_f)

NOW = datetime(2026, 11, 14, 12, 0, 0)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "nasa-test-key")
    for var in ("RECORDS_PATH", "BASELINES_PATH", "LLM_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    app = create_app()

    def call(method, url, **kwargs):
        async def go():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(go())

    return call


# ---------------------------------------------------------------------------
# NASA data routes (the committed processed files)
# ---------------------------------------------------------------------------

def test_sources_lists_all_three_and_says_what_each_is_used_for(api):
    sources = api("GET", "/nasa/sources").json()["sources"]
    assert [s["id"] for s in sources] == ["blood_panels", "radiation", "space_weather"]
    for source in sources:
        assert source["available"] is True
        assert source["fetched_at"] and source["provider"].startswith("NASA")
        assert source["used_for"]
    # The page must not suggest radiation data drives decisions when it does not.
    assert "Not fed to the decision pipelines" in sources[1]["used_for"]


def test_blood_panels_are_the_inspiration4_datasets_with_lab_ranges(api):
    body = api("GET", "/nasa/blood-panels").json()
    assert {d["dataset_id"] for d in body["datasets"]} == {"OSD-569", "OSD-575"}
    assert sorted(body["subjects"]) == ["C001", "C002", "C003", "C004"]
    glucose = body["subjects"]["C001"]["analytes"]["GLUCOSE"]
    assert glucose["dataset_id"] == "OSD-575" and glucose["unit"] == "mg/dL"
    assert (glucose["range_min"], glucose["range_max"]) == (65.0, 99.0)
    assert "laboratory reference range" in glucose["range_basis"]
    timepoints = [d["timepoint"] for d in glucose["draws"]]
    assert timepoints[:3] == ["L-92", "L-44", "L-3"] and timepoints[3].startswith("R+")
    assert "HEMOGLOBIN" in body["subjects"]["C001"]["analytes"]          # from the CBC dataset

    one = api("GET", "/nasa/blood-panels", params={"subject": "C003"}).json()
    assert list(one["subjects"]) == ["C003"]
    assert api("GET", "/nasa/blood-panels", params={"subject": "C999"}).status_code == 404


def test_baselines_are_only_the_preflight_draws(api):
    body = api("GET", "/nasa/baselines").json()
    panels = api("GET", "/nasa/blood-panels").json()
    for subject, channels in body["baselines"].items():
        draws = panels["subjects"][subject]["analytes"]["GLUCOSE"]["draws"]
        assert channels["glucose"] == [d["value"] for d in draws if d["timepoint"].startswith("L-")]
        assert body["provenance"]["baselines"][subject]["glucose"]["dataset_id"] == "OSD-575"


def test_real_baselines_reach_the_statistical_pipeline(api):
    """The app loads the Inspiration4 baselines by default and records that it used them."""
    reading = {"id": "g1", "ts": "2026-11-14T12:00:00Z", "channel": "glucose", "value": 80, "unit": "mg/dL", "source": "simulated"}
    with_baseline = api("POST", "/checkin", json={"astronaut_id": "C001", "readings": [reading], "now": "2026-11-14T12:00:00Z"}).json()
    without = api("POST", "/checkin", json={"astronaut_id": "nobody", "readings": [reading], "now": "2026-11-14T12:00:00Z"}).json()
    a = api("GET", f"/records/{with_baseline['record_id']}").json()["execution_manifest"]["baselines_hash"]
    b = api("GET", f"/records/{without['record_id']}").json()["execution_manifest"]["baselines_hash"]
    assert a != b


def test_radiation_is_labelled_honestly(api):
    body = api("GET", "/nasa/radiation").json()
    assert body["field"] == "absorbed_dose_rate" and body["unit"] == "uGy/h"
    assert "Inferred" in body["unit_note"] and "not dose equivalent" in body["unit_note"]
    where = {s["spacecraft"]: s["location"] for s in body["series"]}
    assert where["ISS"] == "low Earth orbit" and where["Curiosity"].startswith("Mars surface")
    for series in body["series"]:
        assert series["samples"] > 0 and series["window_max"] >= series["window_mean"] > 0
        assert all(p["max"] >= p["mean"] and p["n"] > 0 for p in series["hourly"])

    summary = api("GET", "/nasa/radiation", params={"hourly": "false"}).json()
    assert all("hourly" not in s for s in summary["series"])
    assert len(summary["series"]) == len(body["series"])


def test_space_weather_window(api):
    body = api("GET", "/nasa/space-weather").json()
    s = body["summary"]
    assert body["dataset_id"] == "DONKI"
    assert s["flares"] == len(body["flares"]) and s["x_class_flares"] >= 1
    assert s["strongest_flare"].startswith("X") and s["kp_max"] >= 8
    assert all(f["id"] and f["class"] for f in body["flares"])


def test_missing_nasa_file_is_a_404_with_instructions_not_sample_data(api, monkeypatch, tmp_path):
    monkeypatch.setitem(nasa_routes.FILES, "radiation", tmp_path / "absent.json")
    resp = api("GET", "/nasa/radiation")
    assert resp.status_code == 404
    assert "python -m data.nasa.radlab.fetch" in resp.json()["detail"]
    radiation = next(s for s in api("GET", "/nasa/sources").json()["sources"] if s["id"] == "radiation")
    assert radiation["available"] is False and radiation["fetched_at"] is None


# ---------------------------------------------------------------------------
# Red-team suite: the governance gates block every attack
# ---------------------------------------------------------------------------

_CASES = run_redteam.load_cases()


def test_red_team_covers_every_area():
    assert len(_CASES) >= 18
    assert {c["area"] for c in _CASES} == {"data", "governance", "llm", "records"}
    assert len({c["id"] for c in _CASES}) == len(_CASES)


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_attack_is_blocked(case, monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "redteam-test-key")
    result = run_redteam.run_case(case)
    assert result["blocked"], result["problems"]


def test_runner_reports_an_unsafe_approval_when_a_gate_is_removed(monkeypatch):
    """The suite must be able to fail: with the data-requirements gate disabled, stale data gets through."""
    import backend.checker.checker as checker

    monkeypatch.setenv("SIGNING_KEY", "redteam-test-key")
    monkeypatch.setattr(checker, "gate_data_requirements", lambda integrity, requirements: [])
    stale = next(c for c in _CASES if c["id"] == "stale_data")
    result = run_redteam.run_case(stale)
    assert result["blocked"] is False
    assert "GREEN" in result["observed"]


def test_governance_checks_route_serves_the_saved_run(api):
    body = api("GET", "/earth/governance-checks").json()
    assert body["total"] == len(_CASES)
    assert body["unsafe_approvals"] == 0 and body["blocked"] == body["total"]
    assert {r["id"] for r in body["results"]} == {c["id"] for c in _CASES}


def test_results_markdown_states_the_count():
    results = [{"id": "x", "title": "T", "area": "data", "description": "d", "observed": "o", "blocked": False, "problems": ["p"]}]
    text = run_redteam.to_markdown(results)
    assert "**1 unsafe approvals**" in text and "NO: p" in text


# ---------------------------------------------------------------------------
# Stuck sensor
# ---------------------------------------------------------------------------

def _hr(i, value, minutes_ago):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat() + "Z"
    return {"id": f"hr{i}", "astronaut_id": "crew_1", "ts": ts, "channel": "heart_rate", "value": value, "unit": "bpm", "source": "simulated"}


def test_flat_line_is_rejected_as_a_stuck_sensor():
    limit = POLICY["data_requirements"]["channels"]["heart_rate"]["stuck_after"]
    flat = [_hr(i, 71, limit - i) for i in range(limit)]
    report = input_gate.evaluate(flat, NOW, POLICY["data_requirements"])
    assert all(e["status"] == "invalid" and "stuck_sensor" in e["issues"][0] for e in report["readings"])
    assert decide(flat, {}, {}, NOW)["verdict"]["tier"] == "GREY"


def test_a_shorter_run_or_a_varying_signal_is_not_stuck():
    limit = POLICY["data_requirements"]["channels"]["heart_rate"]["stuck_after"]
    short = [_hr(i, 71, limit - i) for i in range(limit - 1)]
    varying = [_hr(i, 70 + (i % 2), limit - i) for i in range(limit + 4)]
    for readings in (short, varying):
        report = input_gate.evaluate(readings, NOW, POLICY["data_requirements"])
        assert all(e["status"] == "valid" for e in report["readings"])


def test_stuck_check_only_applies_where_the_policy_sets_it():
    sleep = [{**_hr(i, 7.5, 20 - i), "channel": "sleep_hours", "unit": "h"} for i in range(12)]
    report = input_gate.evaluate(sleep, NOW, POLICY["data_requirements"])
    assert all(e["status"] == "valid" for e in report["readings"])


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def test_simulator_readings_are_schema_valid_and_honestly_labelled():
    glucose = simulator._real_glucose()
    assert set(glucose) == set(simulator.CREW)
    readings = simulator.build_readings("C001", random.Random(1), 1, storm=False, fault=None, glucose=glucose)
    for reading in readings:
        jsonschema.validate({"astronaut_id": "C001", **reading}, _READING_SCHEMA)
    real = [r for r in readings if r["source"] != "simulated"]
    assert [r["channel"] for r in real] == ["glucose"]
    assert real[0]["provenance"]["dataset_id"] == "OSD-575" and real[0]["provenance"]["timestamp"].startswith("R+")
    assert len(readings) == len(simulator.VITALS) + 1


def test_simulator_is_seeded_and_its_storm_and_fault_flags_work():
    def run(seed, **kw):
        out = simulator.build_readings("C001", random.Random(seed), 7, glucose={}, **{"storm": False, "fault": None, **kw})
        return {r["channel"]: r for r in out}

    assert [r["value"] for r in run(42).values()] == [r["value"] for r in run(42).values()]
    assert run(42)["heart_rate"]["value"] != run(43)["heart_rate"]["value"]
    assert run(42, storm=True)["dose_rate_usv_h"]["value"] > 200
    assert run(42, fault="heart_rate")["heart_rate"]["quality"] == "fault"


def test_simulated_round_gives_a_verdict_end_to_end(api):
    readings = simulator.build_readings("C001", random.Random(42), 1, storm=False, fault=None, glucose=simulator._real_glucose())
    body = api("POST", "/checkin", json={"astronaut_id": "C001", "readings": readings}).json()
    assert body["verdict"]["tier"] == "GREEN"
    stormy = simulator.build_readings("C001", random.Random(42), 8, storm=True, fault=None, glucose={})
    assert api("POST", "/checkin", json={"astronaut_id": "C001", "readings": stormy}).json()["verdict"]["tier"] == "RED"
