"""Integration test (A-13): the Storm Day scenario end to end through the API.

Owner: person A
"""

import asyncio
import csv
import hashlib
import hmac
import io
import json
from datetime import datetime
from pathlib import Path

import httpx
import jsonschema
import pytest

from backend import cli
from backend.api.main import create_app
from backend.api.state import load_all_baselines
from backend.earth.replay import replay
from backend.orchestrator import decide, load_rules
from backend.records.chain import GENESIS

_ROOT = Path(__file__).resolve().parents[2]
_SCENARIO_PATH = _ROOT / "data" / "scenarios" / "storm_day.json"
_SIGNING_KEY = "storm-day-test-key"

with open(_SCENARIO_PATH) as _f:
    SCENARIO = json.load(_f)
with open(_ROOT / "data" / "schemas" / "reading.schema.json") as _f:
    _READING_SCHEMA = json.load(_f)
with open(_ROOT / "data" / "schemas" / "record.schema.json") as _f:
    _RECORD_SCHEMA = json.load(_f)

EVENTS = SCENARIO["events"]
PEAK = SCENARIO["peak_event_index"]


def _channel(event: dict, channel: str) -> float:
    return next(r["value"] for r in event["readings"] if r["channel"] == channel)


def _independent_hash(record: dict) -> str:
    """Re-hash a Record from the documented rule, without the backend helpers:
    SHA-256 over canonical JSON (sorted keys, compact separators) of every field
    except hash and signature."""
    body = {k: v for k, v in record.items() if k not in ("hash", "signature")}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _independent_signature(record_hash: str) -> str:
    return hmac.new(_SIGNING_KEY.encode(), record_hash.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", _SIGNING_KEY)
    for var in ("RECORDS_PATH", "BASELINES_PATH", "LLM_ENABLED"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def storm_run(env):
    """POST every Storm Day event to /checkin in order; return responses + full Records."""
    app = create_app()

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses, records = [], []
            for event in EVENTS:
                resp = await client.post(
                    "/checkin", json={"astronaut_id": "crew_1", "readings": event["readings"]}
                )
                assert resp.status_code == 200, resp.text
                responses.append(resp.json())
                full = await client.get(f"/records/{resp.json()['record_id']}")
                assert full.status_code == 200
                records.append(full.json())
            verify = await client.get(f"/earth/verify/{records[-1]['id']}")
            status = await client.get("/status/crew_1")
            return responses, records, verify.json(), status.json()

    return asyncio.run(go())


# -- A-13.1: the scenario file ------------------------------------------------

def test_scenario_is_populated_and_schema_valid():
    assert len(EVENTS) >= 3
    assert [e["ts"] for e in EVENTS] == sorted(e["ts"] for e in EVENTS)
    ids = [r["id"] for e in EVENTS for r in e["readings"]]
    assert len(ids) == len(set(ids))
    for event in EVENTS:
        for reading in event["readings"]:
            jsonschema.validate(reading, _READING_SCHEMA)
            # Nothing in this draft scenario may pose as real NASA data.
            assert reading["source"] == "simulated"


def test_scenario_tells_the_storm_story():
    dose = [_channel(e, "dose_rate_usv_h") for e in EVENTS]
    mood = [_channel(e, "mood") for e in EVENTS]
    sleep = [_channel(e, "sleep_hours") for e in EVENTS]
    assert dose.index(max(dose)) == PEAK
    assert dose[PEAK] > 10 * dose[0]                      # elevated dose rate
    assert mood == sorted(mood, reverse=True) and mood[-1] < mood[0]    # declining mood
    assert sleep == sorted(sleep, reverse=True) and sleep[-1] < sleep[0]  # declining sleep


# -- A-13.2 to A-13.4: verdicts through the API ---------------------------------

def test_every_event_gets_a_verdict(storm_run):
    responses, records, _, _ = storm_run
    assert len(responses) == len(EVENTS)
    for response, record in zip(responses, records):
        assert response["verdict"] == record["verdict"]
        jsonschema.validate(record, _RECORD_SCHEMA)


def test_peak_storm_event_is_red_or_grey(storm_run):
    responses, _, _, _ = storm_run
    assert responses[PEAK]["verdict"]["tier"] in ("RED", "GREY")


def test_peak_storm_event_action_alerts_cmo_or_ground(storm_run):
    responses, _, _, _ = storm_run
    assert responses[PEAK]["verdict"]["action"] in ("ALERT_CMO", "CONTACT_GROUND_URGENT")


def test_quiet_morning_is_green_and_storm_never_reads_as_all_clear(storm_run):
    responses, _, _, _ = storm_run
    tiers = [r["verdict"]["tier"] for r in responses]
    assert tiers[0] == "GREEN"
    assert tiers[PEAK] == "RED"
    # After the peak the dose rate is still elevated: never back to GREEN.
    assert all(t != "GREEN" for t in tiers[PEAK:])


def test_statistical_pipeline_says_normal_and_limits_escalates(storm_run):
    """The point of the scenario: A sees nothing unusual, B escalates, the Checker sides with B."""
    _, records, _, _ = storm_run
    proposals = {p["pipeline_id"]: p for p in records[PEAK]["proposals"]}
    assert proposals["a_statistical"]["tier"] == "GREEN"
    assert proposals["b_limits"]["tier"] == "RED"
    assert records[PEAK]["verdict"]["tier"] == "RED"
    assert records[PEAK]["verdict"]["overruled_pipelines"] == ["a_statistical"]


def test_latest_status_matches_last_event(storm_run):
    responses, _, _, status = storm_run
    tiers = [r["verdict"]["tier"] for r in responses]
    assert status["record_id"] == responses[-1]["record_id"]
    assert status["tier"] == tiers[-1]


def test_peak_verdict_explains_itself(storm_run):
    _, records, _, _ = storm_run
    peak = records[PEAK]
    assert peak["verdict"]["reasons"]
    assert any("dose_rate_usv_h" in reason for reason in peak["verdict"]["reasons"])
    assert len(peak["verdict"]["ruleset_hash"]) == 64
    assert peak["readings"] == EVENTS[PEAK]["readings"]


# -- A-13.5 to A-13.7: hash, signature, chain ---------------------------------

def test_record_hashes_are_consistent(storm_run):
    _, records, _, _ = storm_run
    for record in records:
        assert record["hash"] == _independent_hash(record)


def test_record_signatures_are_valid_hmac(storm_run):
    _, records, _, _ = storm_run
    for record in records:
        assert hmac.compare_digest(record["signature"], _independent_signature(record["hash"]))
    # ...and the signature really depends on the key.
    wrong = hmac.new(b"some-other-key", records[0]["hash"].encode(), hashlib.sha256).hexdigest()
    assert records[0]["signature"] != wrong


def test_prev_hash_links_consecutive_events(storm_run):
    _, records, verify, _ = storm_run
    assert records[0]["prev_hash"] == GENESIS
    for previous, current in zip(records, records[1:]):
        assert current["prev_hash"] == previous["hash"]
    assert len({r["hash"] for r in records}) == len(records)
    assert len({r["id"] for r in records}) == len(records)
    assert verify == {"valid": True, "broken_at": None}


# -- A-13.8: determinism ------------------------------------------------------

def test_decide_is_deterministic(env):
    rules = load_rules()
    for event in EVENTS:
        now = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        first = decide(event["readings"], {}, rules, now, prev_hash="abc")
        second = decide(event["readings"], {}, rules, now, prev_hash="abc")
        assert first["verdict"] == second["verdict"]
        assert first == second  # the whole Record, id, hash and signature included


def test_replay_reproduces_api_records_exactly(storm_run):
    """Earth re-running decide() on a stored Record gets the same hash."""
    _, records, _, _ = storm_run
    rules, baselines = load_rules(), load_all_baselines()
    for record in records:
        assert replay(record, baselines, rules) == record


# -- CLI over the same scenario (A-10) ----------------------------------------

def test_cli_run_scenario_matches_the_story(env, capsys):
    assert cli.main(["run-scenario", str(_SCENARIO_PATH), "--seed", "42"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert len(first) == len(EVENTS)
    assert first[PEAK]["verdict"]["tier"] in ("RED", "GREY")
    assert first[0]["prev_hash"] == GENESIS
    assert all(b["prev_hash"] == a["hash"] for a, b in zip(first, first[1:]))

    # Same seed, same inputs: byte-identical output.
    assert cli.main(["run-scenario", str(_SCENARIO_PATH), "--seed", "42"]) == 0
    assert json.loads(capsys.readouterr().out) == first


def test_cli_config_override_changes_the_outcome(env, capsys, tmp_path):
    """--config swaps the pipeline A config (how the ablation runner varies it)."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "cusum: {k: 0.5, h: 4.0}\n"
        "patterns:\n"
        "  - id: any_dose\n"
        "    tier: RED\n"
        "    conditions: [{channel: dose_rate_usv_h, op: gt, threshold: 1.0}]\n"
    )
    assert cli.main(["run-scenario", str(_SCENARIO_PATH), "--config", str(config)]) == 0
    records = json.loads(capsys.readouterr().out)
    assert [r["verdict"]["tier"] for r in records] == ["RED"] * len(EVENTS)


def test_cli_limits_file_changes_the_outcome(env, capsys, tmp_path):
    """--limits-file swaps the pipeline B table (how the sensitivity runner sweeps thresholds)."""
    lenient = tmp_path / "limits.yaml"
    lenient.write_text("channels:\n  dose_rate_usv_h: {unit: uSv/h, yellow_high: 500, red_high: 1000}\n")
    assert cli.main(["run-scenario", str(_SCENARIO_PATH), "--limits-file", str(lenient)]) == 0
    records = json.loads(capsys.readouterr().out)
    assert records[PEAK]["verdict"]["tier"] == "GREEN"


def test_cli_limits_file_is_passed_into_the_rules(env, capsys, tmp_path, monkeypatch):
    limits = tmp_path / "limits.yaml"
    limits.write_text("channels:\n  heart_rate: {unit: bpm, red_high: 999}\n")
    seen = []
    real_decide = cli.decide

    def spy(*args, **kwargs):
        seen.append(kwargs["rules"])
        return real_decide(*args, **kwargs)

    monkeypatch.setattr(cli, "decide", spy)
    assert cli.main(["run-scenario", str(_SCENARIO_PATH), "--limits-file", str(limits)]) == 0
    capsys.readouterr()
    assert seen and all(r["limits"] == {"channels": {"heart_rate": {"unit": "bpm", "red_high": 999}}} for r in seen)


def test_cli_store_out_replay_and_dump_round_trip(env, capsys, tmp_path):
    store = tmp_path / "records.db"
    out = tmp_path / "out"
    assert cli.main(
        ["run-scenario", str(_SCENARIO_PATH), "--store", str(store), "--out", str(out)]
    ) == 0
    capsys.readouterr()
    files = sorted(out.glob("*.json"))
    assert len(files) == len(EVENTS)
    peak = json.loads(files[PEAK].read_text())

    # dump-records, JSON
    assert cli.main(["dump-records", "--store", str(store)]) == 0
    dumped = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in dumped] == [json.loads(f.read_text())["id"] for f in files]

    # dump-records, CSV with astronaut filter
    assert cli.main(["dump-records", "--store", str(store), "--format", "csv", "--astronaut", "crew_1"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == len(EVENTS)
    assert rows[PEAK]["tier"] == peak["verdict"]["tier"]
    assert cli.main(["dump-records", "--store", str(store), "--astronaut", "nobody"]) == 0
    assert json.loads(capsys.readouterr().out) == []

    # replay by id: identical under unchanged rules
    assert cli.main(["replay", peak["id"], "--store", str(store)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == peak
    assert "identical record" in captured.err

    # replay from a file with alternate rules: the decision diverges
    rules = tmp_path / "rules.yaml"
    rules.write_text("limits: {channels: {}}\n")
    assert cli.main(["replay", str(files[PEAK]), "--rules", str(rules)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["verdict"]["tier"] == "GREEN"
    assert "DIVERGED" in captured.err

    # a second run appends to the same chain rather than starting a new one
    assert cli.main(["run-scenario", str(_SCENARIO_PATH), "--store", str(store)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second[0]["prev_hash"] == dumped[-1]["hash"]


@pytest.mark.parametrize(
    "argv",
    [
        ["run-scenario", "no_such_scenario.json"],
        ["replay", "no-such-record-id"],
        ["dump-records"],
        ["dump-records", "--store", "no_such_store.db"],
    ],
)
def test_cli_reports_bad_input_without_a_traceback(env, capsys, argv):
    assert cli.main(argv) == 2
    assert capsys.readouterr().err.startswith("error: ")
