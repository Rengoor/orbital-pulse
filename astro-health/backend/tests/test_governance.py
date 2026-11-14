"""Governance-layer tests: one section per point of the governance audit.

Point 2 (a confirmed data fault invalidates a reading instead of lowering
severity) is covered in its own section below and in test_checker.py.

Owner: person A and person B
"""

import asyncio
import copy
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import jsonschema
import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from backend import cli
from backend.api.main import create_app
from backend.checker import input_gate
from backend.checker.checker import check
from backend.checker.gates import TIER_ORDER, gate_data_requirements, gate_pipeline_availability
from backend.earth.replay import divergence, replay
from backend.orchestrator import FAILSAFE_ACTION, decide, load_rules
from backend.records.anchor import build_anchor, check_against_anchor
from backend.records.chain import GENESIS, seal
from backend.records.signing import DEMO_KEY_ID, is_demo_key, key_id
from backend.records.store import RecordStore

_REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = str(_REPO / "backend" / "checker" / "policy.yaml")
with open(POLICY_PATH) as _f:
    POLICY = yaml.safe_load(_f)
REQUIREMENTS = POLICY["data_requirements"]

with open(_REPO / "data" / "schemas" / "record.schema.json") as _f:
    _RECORD_SCHEMA = json.load(_f)
with open(_REPO / "data" / "schemas" / "verdict.schema.json") as _f:
    _VERDICT_SCHEMA = json.load(_f)

NOW = datetime(2026, 11, 14, 8, 0, 0)
_UNITS = {"heart_rate": "bpm", "dose_rate_usv_h": "uSv/h", "sleep_hours": "h", "temperature": "C"}


def _reading(rid="r1", channel="heart_rate", value=72.0, ts="2026-11-14T08:00:00Z", **extra):
    return {
        "id": rid,
        "astronaut_id": "crew_1",
        "ts": ts,
        "channel": channel,
        "value": value,
        "unit": _UNITS.get(channel, "x"),
        "source": "simulated",
        **extra,
    }


def _status(report, rid):
    return next(e for e in report["readings"] if e["reading_id"] == rid)


def _proposal(pid, tier, data_fault=False, reading_ids=()):
    return {
        "pipeline_id": pid,
        "tier": tier,
        "reasons": [f"{pid} says {tier}"],
        "data_fault": data_fault,
        "reading_ids": list(reading_ids),
    }


def _decide(readings, rules=None, **kwargs):
    return decide(readings, {}, rules if rules is not None else {}, NOW, **kwargs)


# ---------------------------------------------------------------------------
# 1. Input integrity gate
# ---------------------------------------------------------------------------

def test_gate_passes_a_fresh_well_formed_reading():
    report = input_gate.evaluate([_reading()], NOW, REQUIREMENTS)
    assert _status(report, "r1") == {
        "reading_id": "r1", "channel": "heart_rate", "status": "valid", "issues": [], "simulated": True,
    }
    assert report["summary"] == {"valid": 1, "fault": 0, "stale": 0, "invalid": 0, "total": 1}


@pytest.mark.parametrize(
    "reading,status,issue",
    [
        (_reading(ts="2026-11-14T06:30:00Z"), "stale", "older than"),
        (_reading(ts="2026-11-14T09:00:00Z"), "invalid", "timestamp_in_future"),
        (_reading(ts="yesterday-ish"), "invalid", "unreadable_timestamp"),
        (_reading(unit="beats"), "invalid", "unit_mismatch"),
        (_reading(value=float("nan")), "invalid", "value_not_a_finite_number"),
        (_reading(value=float("inf")), "invalid", "value_not_a_finite_number"),
        (_reading(source="nasa_radlab"), "invalid", "real_data_source_without_provenance"),
        (_reading(quality="fault"), "fault", "sensor_reported_fault"),
    ],
)
def test_gate_classifies_bad_readings(reading, status, issue):
    entry = _status(input_gate.evaluate([reading], NOW, REQUIREMENTS), "r1")
    assert entry["status"] == status
    assert any(issue in text for text in entry["issues"])


def test_gate_tolerates_small_clock_skew_and_boundary_ages():
    edge = [
        _reading("ahead", ts="2026-11-14T08:04:00Z"),   # 4 min ahead: within skew
        _reading("old", ts="2026-11-14T07:00:00Z"),     # exactly max age: still fresh
    ]
    report = input_gate.evaluate(edge, NOW, REQUIREMENTS)
    assert [e["status"] for e in report["readings"]] == ["valid", "valid"]


def test_gate_accepts_real_data_with_provenance_and_keeps_the_real_label():
    real = _reading(
        channel="dose_rate_usv_h", source="nasa_radlab",
        provenance={"dataset_id": "radlab-x", "field": "dose", "timestamp": "2026-11-14T08:00:00Z"},
    )
    entry = _status(input_gate.evaluate([real], NOW, REQUIREMENTS), "r1")
    assert entry["status"] == "valid"
    assert entry["simulated"] is False


def test_gate_flags_duplicate_ids_and_contradictory_sensors():
    report = input_gate.evaluate(
        [_reading("dup", value=70.0, ts="2026-11-14T07:50:00Z"), _reading("dup", value=71.0, ts="2026-11-14T07:55:00Z")],
        NOW, REQUIREMENTS,
    )
    assert [e["status"] for e in report["readings"]] == ["valid", "invalid"]

    report = input_gate.evaluate([_reading("a", value=60.0), _reading("b", value=140.0)], NOW, REQUIREMENTS)
    assert [e["status"] for e in report["readings"]] == ["invalid", "invalid"]
    assert all("contradicts" in e["issues"][0] for e in report["readings"])

    # Two sensors that agree are not a contradiction.
    report = input_gate.evaluate([_reading("a", value=72.0), _reading("b", value=72.0)], NOW, REQUIREMENTS)
    assert [e["status"] for e in report["readings"]] == ["valid", "valid"]


def test_gate_makes_no_medical_judgment():
    """A wildly abnormal but well-formed value is valid data; severity is the pipelines' job."""
    assert _status(input_gate.evaluate([_reading(value=250.0)], NOW, REQUIREMENTS), "r1")["status"] == "valid"


def test_gate_is_pure_and_only_usable_readings_reach_the_pipelines():
    readings = [_reading("ok"), _reading("stale", ts="2026-11-14T05:00:00Z"), _reading("bad", unit="beats", ts="2026-11-14T07:59:00Z")]
    before = copy.deepcopy(readings)
    report = input_gate.evaluate(readings, NOW, REQUIREMENTS)
    assert readings == before
    assert [r["id"] for r in input_gate.usable_readings(readings, report)] == ["ok"]


def test_rejected_reading_is_kept_in_the_record_but_hidden_from_pipelines(monkeypatch):
    import backend.pipelines.b_limits.pipeline as pipeline_b

    seen = []
    real_run = pipeline_b.run
    monkeypatch.setattr(pipeline_b, "run", lambda readings, context: seen.extend(readings) or real_run(readings, context))

    bad = _reading("bad", value=250.0, unit="beats", ts="2026-11-14T07:59:00Z")
    record = _decide([_reading("ok"), bad])
    assert [r["id"] for r in seen] == ["ok"]
    assert bad in record["readings"]                       # original value and unit preserved
    assert _status(record["integrity"], "bad")["status"] == "invalid"


# ---------------------------------------------------------------------------
# 14. data_requirements give GREY a precise meaning
# ---------------------------------------------------------------------------

def test_policy_has_a_data_requirements_table():
    assert REQUIREMENTS["min_valid_readings"] >= 1
    assert REQUIREMENTS["max_reading_age_s"] > 0
    assert set(REQUIREMENTS["channels"]) >= {"heart_rate", "temperature", "dose_rate_usv_h"}


def test_empty_checkin_is_grey_not_green():
    verdict = _decide([])["verdict"]
    assert (verdict["tier"], verdict["action"]) == ("GREY", "CONTACT_GROUND_URGENT")
    assert "0 valid reading(s)" in verdict["reasons"][0]


def test_all_stale_data_is_grey():
    verdict = _decide([_reading(ts="2026-11-14T03:00:00Z")])["verdict"]
    assert verdict["tier"] == "GREY"
    assert verdict["decision_trace"]["data_quality"]["status"] == "insufficient"


def test_one_unusable_critical_reading_makes_the_verdict_grey():
    verdict = _decide([_reading("ok"), _reading("t", channel="temperature", value=98.6, unit="F")])["verdict"]
    assert verdict["tier"] == "GREY"
    assert any("temperature reading 't' is invalid" in reason for reason in verdict["reasons"])


def test_requirements_gate_rules():
    def report(*statuses):
        return {"readings": [
            {"reading_id": f"r{i}", "channel": ch, "status": s, "issues": ["x"]} for i, (ch, s) in enumerate(statuses)
        ]}

    met = {"min_valid_readings": 1, "default_critical": True}
    assert gate_data_requirements(report(("heart_rate", "valid")), met) == []
    assert len(gate_data_requirements(report(), met)) == 1
    assert len(gate_data_requirements(report(("heart_rate", "fault")), met)) == 1       # a fault is not valid data
    assert len(gate_data_requirements(report(("heart_rate", "valid"), ("mood", "stale")), met)) == 1

    # A non-critical channel may be unusable without making the verdict unverifiable.
    relaxed = {**met, "channels": {"mood": {"critical": False}}}
    assert gate_data_requirements(report(("heart_rate", "valid"), ("mood", "stale")), relaxed) == []
    assert gate_data_requirements(report(("heart_rate", "valid"), ("mood", "invalid")), {**met, "default_critical": False}) == []

    # A required channel must be present and valid.
    required = {**met, "required_channels": ["heart_rate"]}
    assert gate_data_requirements(report(("heart_rate", "valid")), required) == []
    assert gate_data_requirements(report(("mood", "valid")), required) == ["data requirement not met: no valid heart_rate reading"]


def test_checker_skips_the_requirements_gate_only_when_no_report_is_given():
    green = [_proposal("a_statistical", "GREEN"), _proposal("b_limits", "GREEN")]
    empty_report = input_gate.evaluate([], NOW, REQUIREMENTS)
    assert check(green, [], POLICY_PATH)["tier"] == "GREEN"
    assert check(green, [], POLICY_PATH, integrity=empty_report)["tier"] == "GREY"


# ---------------------------------------------------------------------------
# 2. A confirmed data fault invalidates a reading; it does not lower severity
# ---------------------------------------------------------------------------

def _confirmed(pid, tier, reading_ids):
    return _proposal(pid, tier, data_fault=True, reading_ids=reading_ids)


def test_confirmed_fault_never_turns_grey_into_red():
    """The old one-step-down rule made GREY into RED out of nothing."""
    proposals = [_confirmed("a_statistical", "GREY", ["r1"]), _confirmed("b_limits", "GREY", ["r1"])]
    assert check(proposals, [_reading(quality="fault")], POLICY_PATH)["tier"] == "GREY"


def test_dropping_the_only_reading_leaves_too_little_evidence_so_grey_not_green():
    """Fault correction is not medical recovery: nothing left to assess is not an all-clear."""
    readings = [_reading("r1", value=150.0, quality="fault")]
    proposals = [_confirmed("a_statistical", "RED", ["r1"]), _confirmed("b_limits", "RED", ["r1"])]
    integrity = input_gate.evaluate(readings, NOW, REQUIREMENTS)

    verdict = check(proposals, readings, POLICY_PATH, integrity=integrity, reevaluate=lambda remaining: [])
    assert verdict["tier"] == "GREY"
    assert "0 valid reading(s)" in verdict["reasons"][0]
    issue = verdict["decision_trace"]["data_quality"]["issues"][0]
    assert issue["status"] == "confirmed_fault" and "confirmed_data_fault" in issue["issues"]
    # The caller's report is not modified.
    assert integrity["readings"][0]["status"] == "fault"


def test_confirmed_fault_is_dropped_and_the_rest_is_reassessed():
    readings = [_reading("bad", value=150.0, quality="fault"), _reading("good", channel="sleep_hours", value=5.0)]
    proposals = [_confirmed("a_statistical", "RED", ["bad"]), _confirmed("b_limits", "RED", ["bad"])]
    integrity = input_gate.evaluate(readings, NOW, REQUIREMENTS)
    seen = []

    def reevaluate(remaining):
        seen.append([r["id"] for r in remaining])
        return [_proposal("a_statistical", "GREEN"), _proposal("b_limits", "YELLOW")]

    verdict = check(proposals, readings, POLICY_PATH, integrity=integrity, reevaluate=reevaluate)
    assert seen and all(ids == ["good"] for ids in seen)      # only the surviving reading was reassessed
    assert verdict["tier"] == "YELLOW"                        # what the remaining evidence supports
    changed = [g for g in verdict["decision_trace"]["gates"] if g["changed"]]
    assert (changed[0]["gate"], changed[0]["tier_in"], changed[0]["tier_out"]) == ("data_fault", "RED", "YELLOW")


def test_one_pipeline_alone_cannot_invalidate_a_reading():
    readings = [_reading("r1", value=150.0, quality="fault"), _reading("ok", channel="sleep_hours", value=7.0)]
    proposals = [_confirmed("a_statistical", "GREEN", ["r1"]), _proposal("b_limits", "RED")]
    integrity = input_gate.evaluate(readings, NOW, REQUIREMENTS)
    verdict = check(proposals, readings, POLICY_PATH, integrity=integrity)
    assert verdict["tier"] == "RED"
    assert integrity["readings"][0]["status"] == "fault"


def test_contradiction_uses_the_policy_tolerance_band():
    tolerances = POLICY["contradiction_tolerances"]
    close = [_reading("a", value=72.0), _reading("b", value=74.0)]      # heart_rate band is 3.0
    apart = [_reading("a", value=72.0), _reading("b", value=80.0)]
    assert [e["status"] for e in input_gate.evaluate(close, NOW, REQUIREMENTS, tolerances)["readings"]] == ["valid", "valid"]
    assert [e["status"] for e in input_gate.evaluate(apart, NOW, REQUIREMENTS, tolerances)["readings"]] == ["invalid", "invalid"]
    assert _decide(close)["verdict"]["tier"] == "GREEN"
    assert _decide(apart)["verdict"]["tier"] == "GREY"


# ---------------------------------------------------------------------------
# 3. Pipeline availability policy
# ---------------------------------------------------------------------------

def test_policy_separates_required_from_optional_pipelines():
    assert POLICY["pipelines"]["required"] == ["a_statistical", "b_limits"]
    assert POLICY["pipelines"]["optional"] == ["d_llm"]


def test_availability_gate_rules():
    required = ["a_statistical", "b_limits"]
    assert gate_pipeline_availability({"a_statistical": "ok", "b_limits": "ok", "d_llm": "disabled"}, required) == []
    assert gate_pipeline_availability({"a_statistical": "ok", "b_limits": "ok", "d_llm": "failed"}, required) == []
    for bad in ("failed", "timeout", "invalid_output", "no_output", "missing"):
        reasons = gate_pipeline_availability({"a_statistical": "ok", "b_limits": bad}, required)
        assert reasons == [f"required pipeline 'b_limits' unavailable ({bad})"]
    assert len(gate_pipeline_availability({}, required)) == 2


def test_normal_run_reports_every_pipeline():
    record = _decide([_reading()])
    assert record["execution_manifest"]["pipelines"] == {"a_statistical": "ok", "b_limits": "ok", "d_llm": "disabled"}
    assert record["verdict"]["tier"] == "GREEN"


def test_a_required_pipeline_that_cannot_be_loaded_is_grey_not_silently_skipped(monkeypatch):
    """The case the old design missed: B vanishes, A alone says GREEN."""
    import backend.orchestrator as orchestrator
    import backend.pipelines.a_statistical.pipeline as pipeline_a

    monkeypatch.setattr(orchestrator, "discover_pipelines", lambda: [pipeline_a])
    record = _decide([_reading()])
    assert [p["tier"] for p in record["proposals"]] == ["GREEN"]
    assert record["execution_manifest"]["pipelines"]["b_limits"] == "missing"
    assert record["verdict"]["tier"] == "GREY"
    assert record["verdict"]["disagreement_status"] == "PARTIAL_ASSESSMENT"
    assert "required pipeline 'b_limits' unavailable (missing)" in record["verdict"]["reasons"]


@pytest.mark.parametrize(
    "replacement,status",
    [
        (lambda readings, context: (_ for _ in ()).throw(RuntimeError("killed")), "failed"),
        (lambda readings, context: {"tier": "GREEN"}, "invalid_output"),
        (lambda readings, context: None, "no_output"),
    ],
)
def test_required_pipeline_failures_are_grey(monkeypatch, replacement, status):
    import backend.pipelines.a_statistical.pipeline as pipeline_a

    monkeypatch.setattr(pipeline_a, "run", replacement)
    record = _decide([_reading()])
    assert record["execution_manifest"]["pipelines"]["a_statistical"] == status
    assert record["verdict"]["tier"] == "GREY"
    assert record["verdict"]["known_severity"] == "GREEN"      # what B could still establish


def test_a_pipeline_that_hangs_is_timed_out_and_the_verdict_is_grey(monkeypatch, tmp_path):
    import backend.pipelines.a_statistical.pipeline as pipeline_a

    policy = copy.deepcopy(POLICY)
    policy["pipelines"]["timeout_s"] = 0.2
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy))
    monkeypatch.setattr(pipeline_a, "run", lambda readings, context: time.sleep(2) or {})

    started = time.monotonic()
    record = _decide([_reading()], rules={"policy_path": str(path)})
    assert time.monotonic() - started < 1.5                    # did not wait for the hung pipeline
    assert record["execution_manifest"]["pipelines"]["a_statistical"] == "timeout"
    assert record["verdict"]["tier"] == "GREY"


def test_optional_pipeline_failure_is_disclosed_but_does_not_change_the_decision(monkeypatch):
    from backend.pipelines.d_llm import pipeline as llm

    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm, "call_llm", lambda s, u: (_ for _ in ()).throw(RuntimeError("no server")))
    record = _decide([_reading()])
    assert record["verdict"]["tier"] == "GREEN"
    assert record["execution_manifest"]["pipelines"]["d_llm"] == "no_output"
    assert record["verdict"]["disagreement_status"] == "PARTIAL_ASSESSMENT"


# ---------------------------------------------------------------------------
# 13. GREY sits outside the severity order
# ---------------------------------------------------------------------------

def test_policy_severity_order_excludes_grey():
    assert POLICY["severity_order"] == ["GREEN", "YELLOW", "RED"]


def test_grey_does_not_hide_a_known_red():
    verdict = check([_proposal("a_statistical", "GREY"), _proposal("b_limits", "RED")], [], POLICY_PATH)
    assert verdict["tier"] == "GREY"
    assert verdict["action"] == "CONTACT_GROUND_URGENT"
    assert verdict["known_severity"] == "RED"
    assert verdict["additional_actions"] == ["ALERT_CMO"]      # the medical alert survives


def test_grey_with_known_yellow_keeps_the_caution():
    verdict = check([_proposal("a_statistical", "YELLOW"), _proposal("b_limits", "GREY")], [], POLICY_PATH)
    assert (verdict["tier"], verdict["known_severity"]) == ("GREY", "YELLOW")
    assert verdict["additional_actions"] == ["REST_AND_HYDRATE"]


def test_grey_with_nothing_worse_known_adds_no_action():
    verdict = check([_proposal("a_statistical", "GREEN"), _proposal("b_limits", "GREY")], [], POLICY_PATH)
    assert verdict["known_severity"] == "GREEN"
    assert "additional_actions" not in verdict


def test_grey_with_nothing_known_at_all():
    verdict = check([_proposal("a_statistical", "GREY"), _proposal("b_limits", "GREY")], [], POLICY_PATH)
    assert verdict["tier"] == "GREY"
    assert "known_severity" not in verdict


def test_verified_verdict_reports_its_own_severity_as_known():
    verdict = check([_proposal("a_statistical", "GREEN"), _proposal("b_limits", "RED")], [], POLICY_PATH)
    assert (verdict["tier"], verdict["known_severity"]) == ("RED", "RED")
    assert "additional_actions" not in verdict


def test_red_reading_plus_an_unusable_reading_end_to_end():
    record = _decide([_reading("hr", value=150.0), _reading("t", channel="temperature", value=98.6, unit="F")])
    verdict = record["verdict"]
    assert verdict["tier"] == "GREY"
    assert verdict["known_severity"] == "RED"
    assert verdict["additional_actions"] == ["ALERT_CMO"]


_tiers = st.sampled_from(["GREEN", "YELLOW", "RED", "GREY"])


@given(a=_tiers, b=_tiers, a_fault=st.booleans(), b_fault=st.booleans())
def test_known_severity_is_never_grey_and_never_understates_a_verified_verdict(a, b, a_fault, b_fault):
    verdict = check(
        [_proposal("a_statistical", a, a_fault), _proposal("b_limits", b, b_fault)], [], POLICY_PATH
    )
    jsonschema.validate(verdict, _VERDICT_SCHEMA)
    known = verdict.get("known_severity")
    assert known != "GREY"
    if verdict["tier"] != "GREY":
        assert known == verdict["tier"]
    # Any action attached to what is known is on the whitelist and is not a no-op.
    for extra in verdict.get("additional_actions", []):
        assert extra in POLICY["actions"] and extra != "NO_ACTION"


# ---------------------------------------------------------------------------
# 15. System-wide fail-safe
# ---------------------------------------------------------------------------

def _assert_failsafe(record, cause):
    verdict = record["verdict"]
    assert (verdict["tier"], verdict["action"]) == ("GREY", FAILSAFE_ACTION)
    assert verdict["failsafe"] is True
    assert cause in verdict["reasons"][0]
    assert record["execution_manifest"]["failsafe"] is True
    jsonschema.validate(record, _RECORD_SCHEMA)
    jsonschema.validate(verdict, _VERDICT_SCHEMA)


def test_missing_policy_file_fails_safe():
    record = _decide([_reading()], rules={"policy_path": str(_REPO / "no_such_policy.yaml")})
    _assert_failsafe(record, "FileNotFoundError")
    assert record["execution_manifest"]["policy_hash"] == "unavailable"


@pytest.mark.parametrize("content", ["just a string", "- a\n- list\n", "actions: [NO_ACTION\n", ""])
def test_corrupt_policy_file_fails_safe(tmp_path, content):
    path = tmp_path / "policy.yaml"
    path.write_text(content)
    record = _decide([_reading()], rules={"policy_path": str(path)})
    assert record["verdict"]["tier"] == "GREY"
    assert record["verdict"]["failsafe"] is True


def test_checker_crash_fails_safe(monkeypatch):
    import backend.orchestrator as orchestrator

    def crash(*args, **kwargs):
        raise ZeroDivisionError("checker bug")

    monkeypatch.setattr(orchestrator, "check", crash)
    record = _decide([_reading(value=150.0)])
    _assert_failsafe(record, "ZeroDivisionError")
    # The pipelines' work is not thrown away: it stays in the record for Earth.
    assert {p["pipeline_id"]: p["tier"] for p in record["proposals"]} == {"a_statistical": "GREEN", "b_limits": "RED"}


def test_input_gate_crash_fails_safe(monkeypatch):
    monkeypatch.setattr(input_gate, "evaluate", lambda *a, **k: (_ for _ in ()).throw(KeyError("gate bug")))
    _assert_failsafe(_decide([_reading()]), "KeyError")


def test_failsafe_record_is_still_signed_and_chained():
    from backend.earth.verify import verify_record

    record = _decide([_reading()], rules={"policy_path": "/nope"}, prev_hash="a" * 64)
    assert record["prev_hash"] == "a" * 64
    assert verify_record(record)


def test_failsafe_does_not_swallow_caller_errors():
    with pytest.raises(ValueError):
        _decide([{"id": "incomplete"}])


# ---------------------------------------------------------------------------
# 4. Decision trace  /  9. Disagreement status
# ---------------------------------------------------------------------------

def test_decision_trace_contents():
    record = _decide([_reading("hr", value=150.0)])
    verdict = record["verdict"]
    trace = verdict["decision_trace"]

    assert trace["final_tier"] == verdict["tier"] == "RED"
    assert trace["action_authorized"] == verdict["action"] == "ALERT_CMO"
    assert trace["policy_hash"] == verdict["ruleset_hash"]
    assert trace["contributing_proposals"] == [
        {"pipeline_id": "a_statistical", "tier": "GREEN", "data_fault": False, "rule_ids": [], "advisory": False},
        {"pipeline_id": "b_limits", "tier": "RED", "data_fault": False, "rule_ids": ["heart_rate.red_high"], "advisory": False},
    ]
    assert trace["triggered_rules"] == ["heart_rate.red_high"]
    assert trace["pipeline_status"] == {"a_statistical": "ok", "b_limits": "ok", "d_llm": "disabled"}
    assert trace["data_quality"]["status"] == "ok"
    assert [g["gate"] for g in trace["gates"]] == [
        "worst_of", "data_fault", "grey_escalation", "data_requirements", "pipeline_availability",
    ]
    assert trace["gates"][0]["tier_out"] == "RED"
    assert "b_limits proposed RED" in trace["explanation"]
    assert "ALERT_CMO" in trace["explanation"]
    json.dumps(trace)  # machine-readable all the way down


def test_trace_shows_which_gate_changed_the_tier():
    trace = _decide([_reading(quality="fault")])["verdict"]["decision_trace"]
    changed = [g for g in trace["gates"] if g["changed"]]
    assert changed[0]["gate"] == "grey_escalation"
    assert (changed[0]["tier_in"], changed[0]["tier_out"]) == ("GREEN", "GREY")
    assert trace["data_quality"]["issues"][0]["reading_id"] == "r1"


@pytest.mark.parametrize(
    "proposals,status",
    [
        ([("a_statistical", "GREEN"), ("b_limits", "GREEN")], "AGREEMENT"),
        ([("a_statistical", "RED"), ("b_limits", "RED")], "AGREEMENT"),
        ([("a_statistical", "GREEN"), ("b_limits", "RED")], "DISAGREEMENT"),
        ([("a_statistical", "YELLOW"), ("b_limits", "RED")], "DISAGREEMENT"),
        ([("a_statistical", "GREY"), ("b_limits", "GREEN")], "UNVERIFIABLE"),
    ],
)
def test_disagreement_status(proposals, status):
    verdict = check([_proposal(p, t) for p, t in proposals], [], POLICY_PATH)
    assert verdict["disagreement_status"] == status
    assert verdict["decision_trace"]["disagreement_status"] == status


def test_disagreement_never_softens_the_verdict():
    """Status is information only: two GREENs cannot outvote one RED."""
    proposals = [_proposal("a_statistical", "GREEN"), _proposal("c_other", "GREEN"), _proposal("b_limits", "RED")]
    verdict = check(proposals, [], POLICY_PATH)
    assert (verdict["tier"], verdict["disagreement_status"]) == ("RED", "DISAGREEMENT")
    assert verdict["overruled_pipelines"] == ["a_statistical", "c_other"]


# ---------------------------------------------------------------------------
# 12. Execution manifest and deterministic replay
# ---------------------------------------------------------------------------

def test_manifest_identifies_the_decision_environment():
    manifest = _decide([_reading()], rules=load_rules())["execution_manifest"]
    assert set(manifest) == {
        "orchestrator_version", "checker_version", "schema_version", "policy_hash", "config_hash",
        "limits_hash", "baselines_hash", "pipelines", "llm", "clock_source", "random_seed", "signing", "failsafe",
    }
    assert all(len(manifest[k]) == 64 for k in ("policy_hash", "config_hash", "limits_hash", "baselines_hash"))
    assert manifest["llm"] == {"enabled": False, "model": None}


def test_manifest_is_part_of_what_is_hashed_and_signed():
    from backend.earth.verify import verify_record

    record = _decide([_reading()])
    assert verify_record(record)
    record["execution_manifest"]["limits_hash"] = "0" * 64
    assert not verify_record(record)


def test_manifest_does_not_depend_on_where_the_policy_file_lives(tmp_path):
    """Replay on another machine must not diverge just because paths differ."""
    elsewhere = tmp_path / "copied_policy.yaml"
    elsewhere.write_bytes(Path(POLICY_PATH).read_bytes())
    here = _decide([_reading()], rules={"policy_path": POLICY_PATH})
    there = _decide([_reading()], rules={"policy_path": str(elsewhere)})
    assert here == there


def test_replay_names_exactly_what_changed(monkeypatch):
    from backend.pipelines.a_statistical.baseline import compute_baseline

    rules = load_rules()
    original = decide([_reading(value=95.0)], {}, rules, NOW)

    same = divergence(original, replay(original, {}, rules))
    assert (same["identical"], same["environment_changed"], same["unexplained"]) == (True, {}, False)

    baselines = {"crew_1": {"heart_rate": compute_baseline([70.0, 71.0, 69.0, 70.0])}}
    assert set(divergence(original, replay(original, baselines, rules))["environment_changed"]) == {"baselines_hash"}

    patterns = {**rules, "patterns": [{"id": "p", "tier": "RED", "conditions": [{"channel": "heart_rate", "op": "gt", "threshold": 90}]}]}
    report = divergence(original, replay(original, {}, patterns))
    assert set(report["environment_changed"]) == {"config_hash"}
    assert report["decision_changed"] is True and report["unexplained"] is False

    monkeypatch.setenv("SIGNING_KEY", "a-different-key")
    assert set(divergence(original, replay(original, {}, rules))["environment_changed"]) == {"signing"}


def test_clock_source_is_recorded_and_survives_replay():
    original = _decide([_reading()], clock_source="request")
    assert original["execution_manifest"]["clock_source"] == "request"
    assert replay(original, {}, {}) == original


# ---------------------------------------------------------------------------
# 6. Signing key is identified  /  5. prev_hash is enforced
# ---------------------------------------------------------------------------

def test_key_id_identifies_the_key_without_revealing_it():
    assert key_id("secret-a") == key_id("secret-a")
    assert key_id("secret-a") != key_id("secret-b")
    assert "secret-a" not in key_id("secret-a")
    assert key_id("secret-a").startswith("k-") and len(key_id("secret-a")) == 18


def test_demo_key_is_recognised(monkeypatch):
    monkeypatch.delenv("SIGNING_KEY", raising=False)
    assert is_demo_key() and key_id() == DEMO_KEY_ID
    monkeypatch.setenv("SIGNING_KEY", "demo-only-change-me")
    assert is_demo_key()
    monkeypatch.setenv("SIGNING_KEY", "a-real-secret")
    assert not is_demo_key()


def test_every_record_names_its_signing_key(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "a-real-secret")
    record = _decide([_reading()])
    assert record["key_id"] == key_id("a-real-secret")
    assert record["execution_manifest"]["signing"] == {"key_id": key_id("a-real-secret"), "demo_key": False}

    monkeypatch.delenv("SIGNING_KEY")
    assert _decide([_reading()])["execution_manifest"]["signing"]["demo_key"] is True


@pytest.mark.parametrize("key", [None, "", "demo-only-change-me"])
def test_api_refuses_to_start_without_a_real_signing_key(monkeypatch, key):
    monkeypatch.delenv("RECORDS_PATH", raising=False)
    if key is None:
        monkeypatch.delenv("SIGNING_KEY", raising=False)
    else:
        monkeypatch.setenv("SIGNING_KEY", key)
    with pytest.raises(RuntimeError, match="SIGNING_KEY"):
        create_app()


def test_api_starts_with_a_real_signing_key(monkeypatch):
    monkeypatch.delenv("RECORDS_PATH", raising=False)
    monkeypatch.setenv("SIGNING_KEY", "a-real-secret")
    assert create_app().state.ctx.signing_key == "a-real-secret"


@pytest.mark.parametrize("prev_hash", ["", "abc", "genesis", "G" * 64, "a" * 63, "a" * 65, "A" * 64])
def test_record_schema_rejects_malformed_prev_hash(prev_hash):
    record = _decide([_reading()])
    record["prev_hash"] = prev_hash
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, _RECORD_SCHEMA)
    with pytest.raises(ValueError, match="prev_hash|does not match"):
        _decide([_reading()], prev_hash=prev_hash)


@pytest.mark.parametrize("prev_hash", [GENESIS, "a" * 64, "0123456789abcdef" * 4])
def test_record_schema_accepts_well_formed_prev_hash(prev_hash):
    jsonschema.validate(_decide([_reading()], prev_hash=prev_hash), _RECORD_SCHEMA)


def test_store_refuses_a_record_that_does_not_link_to_the_head():
    store = RecordStore()
    first = store.append_with(lambda prev: _decide([_reading("a")], prev_hash=prev))

    with pytest.raises(ValueError, match="does not link to the chain head"):
        store.append_with(lambda prev: _decide([_reading("b")], prev_hash=GENESIS))     # forks the chain
    with pytest.raises(ValueError, match="does not link to the chain head"):
        store.append_with(lambda prev: _decide([_reading("c")], prev_hash="f" * 64))    # points at nothing

    assert store.all() == [first]
    assert store.verify_chain() == (True, None)
    store.close()


# ---------------------------------------------------------------------------
# 7. Externally anchored chain hash
# ---------------------------------------------------------------------------

def _chain(n, key=None):
    records, prev = [], GENESIS
    for i in range(n):
        records.append(seal({"id": f"rec{i}", "n": i}, prev, key))
        prev = records[-1]["hash"]
    return records


def test_anchor_describes_the_chain_head():
    chain = _chain(3)
    anchor = build_anchor(chain, NOW)
    assert anchor["record_count"] == 3
    assert anchor["head_hash"] == chain[-1]["hash"]
    assert anchor["head_record_id"] == "rec2"
    assert anchor["ts"] == "2026-11-14T08:00:00Z"
    assert anchor["key_id"] == key_id()
    assert check_against_anchor(chain, anchor)["valid"] is True
    assert build_anchor([], NOW)["head_hash"] == GENESIS
    assert check_against_anchor([], build_anchor([], NOW))["valid"] is True


def test_chain_may_grow_after_the_anchor():
    chain = _chain(5)
    anchor = build_anchor(chain[:3], NOW)
    assert check_against_anchor(chain, anchor)["valid"] is True


def test_anchor_catches_truncation_that_the_chain_alone_cannot():
    from backend.records.chain import first_broken_link

    chain = _chain(5)
    anchor = build_anchor(chain, NOW)
    truncated = chain[:3]
    assert first_broken_link(truncated) is None                 # the chain alone sees nothing wrong
    result = check_against_anchor(truncated, anchor)
    assert result["valid"] is False and "removed" in result["reason"]


def test_anchor_catches_a_complete_rewrite_by_someone_holding_the_key():
    original = _chain(4, key="k")
    anchor = build_anchor(original, NOW, signing_key="k")

    rewritten, prev = [], GENESIS
    for i in range(4):
        rewritten.append(seal({"id": f"rec{i}", "n": i, "softened": True}, prev, "k"))
        prev = rewritten[-1]["hash"]
    from backend.records.chain import first_broken_link

    assert first_broken_link(rewritten, signing_key="k") is None    # internally perfect
    result = check_against_anchor(rewritten, anchor, signing_key="k")
    assert result["valid"] is False and "rewritten" in result["reason"]


def test_a_forged_or_malformed_anchor_is_rejected():
    chain = _chain(3)
    anchor = build_anchor(chain, NOW)
    assert check_against_anchor(chain, {**anchor, "record_count": 1})["valid"] is False
    assert check_against_anchor(chain, {**anchor, "head_hash": chain[0]["hash"]})["valid"] is False
    assert check_against_anchor(chain, anchor, signing_key="other-key")["valid"] is False
    for junk in ({}, {"record_count": "x"}, None, "anchor", []):
        assert check_against_anchor(chain, junk)["valid"] is False


def test_cli_anchor_round_trip(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("RECORDS_PATH", raising=False)
    store, checkpoint = tmp_path / "records.db", tmp_path / "anchor.json"
    scenario = str(_REPO / "data" / "scenarios" / "storm_day.json")
    assert cli.main(["run-scenario", scenario, "--store", str(store)]) == 0
    assert cli.main(["anchor", "--store", str(store), "--out", str(checkpoint)]) == 0
    capsys.readouterr()
    assert json.loads(checkpoint.read_text())["record_count"] == 5

    assert cli.main(["verify-anchor", str(checkpoint), "--store", str(store)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True

    # Quietly drop the two newest records: the chain still verifies, the anchor does not.
    db = RecordStore(store)
    with db._conn:
        db._conn.execute("DELETE FROM records WHERE seq > 3")
    assert db.verify_chain() == (True, None)
    db.close()
    assert cli.main(["verify-anchor", str(checkpoint), "--store", str(store)]) == 1
    assert json.loads(capsys.readouterr().out)["valid"] is False


# ---------------------------------------------------------------------------
# 8. Project thresholds are never presented as NASA limits
# ---------------------------------------------------------------------------

def test_every_placeholder_breach_is_labelled_project_defined():
    record = _decide([_reading("hr", value=150.0), _reading("d", channel="dose_rate_usv_h", value=260.0)])
    limit_reasons = [r for r in record["verdict"]["reasons"] if "limit" in r]
    assert len(limit_reasons) == 2
    assert all("project-defined" in r for r in limit_reasons)
    assert not any("NASA" in r for r in record["verdict"]["reasons"])


@pytest.mark.parametrize(
    "row",
    [
        {"basis": "nasa_direct", "source": "PLACEHOLDER", "reference": "Table 4"},   # claims NASA, no document
        {"basis": "nasa_direct", "source": "NASA-STD-3001", "reference": None},      # no place in the document
        {"basis": "nasa_direct", "source": None, "reference": None},
        {"basis": "project_defined", "source": "NASA-STD-3001", "reference": "Table 4"},  # adapted, so ours
        {},
    ],
)
def test_unverifiable_source_is_never_treated_as_authoritative(row):
    limits = {"channels": {"heart_rate": {"unit": "bpm", "red_high": 130, **row}}}
    reason = _decide([_reading(value=150.0)], rules={"limits": limits})["verdict"]["reasons"][0]
    assert "project-defined" in reason and "NASA" not in reason


def test_a_fully_sourced_direct_limit_is_attributed_with_its_reference():
    limits = {"channels": {"heart_rate": {
        "unit": "bpm", "red_high": 130, "basis": "nasa_direct", "source": "NASA-STD-3001", "reference": "Vol 1, Table 4",
    }}}
    reason = _decide([_reading(value=150.0)], rules={"limits": limits})["verdict"]["reasons"][0]
    assert "NASA (NASA-STD-3001, Vol 1, Table 4) red limit" in reason


def test_every_row_of_the_real_table_declares_its_basis():
    table = load_rules()["limits"]["channels"]
    assert all(row["basis"] == "project_defined" for row in table.values())
    assert all({"source", "reference", "applies_to"} <= set(row) for row in table.values())


# ---------------------------------------------------------------------------
# 11. "Why should I trust this decision?" (data for the UI panel)
# ---------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    for var in ("RECORDS_PATH", "BASELINES_PATH", "LLM_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SIGNING_KEY", "governance-test-key")
    app = create_app()

    def call(method, url, **kwargs):
        async def go():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(go())

    call.app = app
    call.store = app.state.ctx.store
    return call


def _checkin(api, readings, now="2026-11-14T08:00:30Z"):
    resp = api("POST", "/checkin", json={"astronaut_id": "crew_1", "readings": readings, "now": now})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_trust_summary_for_a_disputed_red(api):
    record_id = _checkin(api, [_reading("hr", value=150.0)])["record_id"]
    resp = api("GET", f"/records/{record_id}/trust")
    assert resp.status_code == 200
    trust = resp.json()

    assert (trust["tier"], trust["action"], trust["failsafe"]) == ("RED", "ALERT_CMO", False)
    assert trust["assessments"]["status"] == "DISAGREEMENT"
    assert trust["assessments"]["contributed"] == [
        {"pipeline_id": "a_statistical", "tier": "GREEN", "advisory": False},
        {"pipeline_id": "b_limits", "tier": "RED", "advisory": False},
    ]
    assert trust["assessments"]["did_not_run"] == []
    assert trust["data"]["status"] == "ok" and trust["data"]["usable"] == 1
    assert trust["data"]["simulated_inputs"] == ["heart_rate"]
    assert trust["rules"]["triggered"] == ["heart_rate.red_high"]
    assert trust["rules"]["limits_are_official"] is False
    assert trust["record"] == {"recorded": True, "chain_intact": True, "signed_with_demo_key": False}
    assert trust["human_review"]["status"] == "pending"
    # Meant for the astronaut: plain statements, no hashes.
    assert "b_limits proposed RED" in trust["explanation"]
    assert "hash" not in json.dumps(trust)

    api("POST", "/earth/review", json={"record_id": record_id, "cmo_note": "seen", "outcome": "AGREE"})
    reviewed = api("GET", f"/records/{record_id}/trust").json()["human_review"]
    assert reviewed == {"status": "reviewed", "outcomes": ["AGREE"], "simulated": True}


def test_trust_summary_reflects_tampering_and_missing_records(api):
    record_id = _checkin(api, [_reading()])["record_id"]
    edited = api.store.get(record_id)
    edited["verdict"]["reasons"] = ["edited"]
    with api.store._conn:
        api.store._conn.execute("UPDATE records SET body = ? WHERE id = ?", (json.dumps(edited), record_id))
    assert api("GET", f"/records/{record_id}/trust").json()["record"]["chain_intact"] is False
    assert api("GET", "/records/nope/trust").status_code == 404


def test_status_and_card_show_disagreement_and_known_severity(api):
    _checkin(api, [_reading("hr", value=150.0), _reading("t", channel="temperature", value=98.6, unit="F")])
    status = api("GET", "/status/crew_1").json()
    assert status["tier"] == "GREY"
    assert status["known_severity"] == "RED"
    assert status["additional_actions"] == ["ALERT_CMO"]
    assert status["disagreement_status"] == "UNVERIFIABLE"

    card = api("GET", f"/records/{status['record_id']}/card").json()
    assert (card["tier"], card["known_severity"], card["additional_actions"]) == ("GREY", "RED", ["ALERT_CMO"])
    assert card["disagreement_status"] == "UNVERIFIABLE"
    assert card["explanation"].startswith("GREY:")


# ---------------------------------------------------------------------------
# API behaviour of the points above
# ---------------------------------------------------------------------------

def test_api_judges_freshness_against_the_server_clock_by_default(api):
    """No `now` in the request: readings stamped at a fixed past/future time are not fresh."""
    stale_ts = (datetime.utcnow() - timedelta(hours=5)).isoformat() + "Z"
    resp = api("POST", "/checkin", json={"astronaut_id": "crew_1", "readings": [_reading(ts=stale_ts)]})
    assert resp.json()["verdict"]["tier"] == "GREY"
    record = api.store.get(resp.json()["record_id"])
    assert record["execution_manifest"]["clock_source"] == "server"

    fresh_ts = datetime.utcnow().isoformat() + "Z"
    resp = api("POST", "/checkin", json={"astronaut_id": "crew_1", "readings": [_reading("r2", ts=fresh_ts)]})
    assert resp.json()["verdict"]["tier"] == "GREEN"


def test_api_records_when_the_request_supplied_the_clock(api):
    record = api.store.get(_checkin(api, [_reading()])["record_id"])
    assert record["execution_manifest"]["clock_source"] == "request"
    assert record["ts"] == "2026-11-14T08:00:30Z"


def test_api_fails_safe_when_the_decision_call_itself_blows_up(api, monkeypatch):
    _checkin(api, [_reading()])                                  # a GREEN is on file
    assert api("GET", "/status/crew_1").json()["tier"] == "GREEN"

    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("backend.api.routes.checkin.decide", boom)
    body = _checkin(api, [_reading("r2")], now="2026-11-14T08:01:00Z")
    assert (body["verdict"]["tier"], body["verdict"]["failsafe"]) == ("GREY", True)

    # The stale GREEN is no longer what the astronaut sees, and the failure is on the chain.
    assert api("GET", "/status/crew_1").json()["tier"] == "GREY"
    assert len(api.store.all()) == 2
    assert api.store.verify_chain() == (True, None)


def test_api_fails_safe_when_policy_becomes_unreadable_mid_run(api):
    _checkin(api, [_reading()])
    state = api.app.state.ctx
    state.rules = {**state.rules, "policy_path": "/vanished/policy.yaml"}

    body = _checkin(api, [_reading("r2")], now="2026-11-14T08:01:00Z")
    assert (body["verdict"]["tier"], body["verdict"]["action"]) == ("GREY", "CONTACT_GROUND_URGENT")
    assert body["verdict"]["failsafe"] is True


def test_api_anchor_endpoints(api):
    for i in range(3):
        _checkin(api, [_reading(f"r{i}")], now=f"2026-11-14T08:0{i}:30Z")
    anchor = api("GET", "/earth/anchor").json()
    assert anchor["record_count"] == 3
    assert api("POST", "/earth/anchor/verify", json=anchor).json()["valid"] is True

    with api.store._conn:
        api.store._conn.execute("DELETE FROM records WHERE seq = 3")
    result = api("POST", "/earth/anchor/verify", json=anchor).json()
    assert result["valid"] is False and "removed" in result["reason"]
    assert api("POST", "/earth/anchor/verify", json={"nonsense": True}).json()["valid"] is False
