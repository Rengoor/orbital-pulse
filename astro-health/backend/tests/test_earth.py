"""Tests for earth.

Owner: person B
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from backend.earth.replay import divergence, replay
from backend.earth.review import build_review
from backend.earth.rulechange import rulechange
from backend.earth.verify import verify_chain, verify_record
from backend.orchestrator import decide, load_rules
from backend.records.chain import GENESIS, canonical_json, compute_hash
from backend.records.signing import verify as verify_signature

_REPO = Path(__file__).resolve().parents[2]
with open(_REPO / "data" / "schemas" / "review.schema.json") as _f:
    _REVIEW_SCHEMA = json.load(_f)
with open(_REPO / "data" / "schemas" / "record.schema.json") as _f:
    _RECORD_SCHEMA = json.load(_f)

_NOW = datetime(2026, 11, 14, 8, 0, 0)
_KEY = "earth-test-key"


def _reading(rid, value, channel="heart_rate", unit="bpm", astronaut_id="crew_1"):
    return {
        "id": rid,
        "astronaut_id": astronaut_id,
        "ts": "2026-11-14T08:00:00Z",
        "channel": channel,
        "value": value,
        "unit": unit,
        "source": "simulated",
    }


@pytest.fixture
def rules():
    return load_rules()


@pytest.fixture
def history(rules, monkeypatch):
    """Four chained Records: GREEN, YELLOW, RED, GREEN heart rates."""
    monkeypatch.setenv("SIGNING_KEY", _KEY)
    records, prev = [], GENESIS
    for i, hr in enumerate([72.0, 110.0, 150.0, 80.0]):
        record = decide([_reading(f"r{i}", hr)], {}, rules, _NOW.replace(minute=i), prev_hash=prev)
        records.append(record)
        prev = record["hash"]
    assert [r["verdict"]["tier"] for r in records] == ["GREEN", "YELLOW", "RED", "GREEN"]
    return records


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def test_verify_intact_chain(history):
    assert all(verify_record(r) for r in history)
    assert verify_chain(history) == {"valid": True, "broken_at": None}
    assert verify_chain([]) == {"valid": True, "broken_at": None}


def test_verify_rejects_the_wrong_key(history):
    assert not verify_record(history[0], signing_key="not-the-key")
    assert verify_chain(history, signing_key="not-the-key") == {"valid": False, "broken_at": history[0]["id"]}


@pytest.mark.parametrize(
    "path",
    [
        ("verdict", "tier"),
        ("verdict", "action"),
        ("verdict", "ruleset_hash"),
        ("readings", 0, "value"),
        ("proposals", 1, "tier"),
        ("ts",),
        ("astronaut_id",),
        ("versions", "checker"),
    ],
)
def test_tampering_with_any_part_of_a_record_is_detected(history, path):
    tampered = copy.deepcopy(history)
    target = tampered[2]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "GREEN" if path[-1] != "value" else 70.0

    assert not verify_record(tampered[2])
    assert verify_chain(tampered) == {"valid": False, "broken_at": history[2]["id"]}
    # Everything before the edit still checks out.
    assert verify_chain(tampered, upto_record_id=history[1]["id"]) == {"valid": True, "broken_at": None}


def test_softening_a_red_verdict_and_rehashing_is_still_detected(history):
    tampered = copy.deepcopy(history)
    tampered[2]["verdict"]["tier"] = "GREEN"
    tampered[2]["verdict"]["action"] = "NO_ACTION"
    tampered[2]["hash"] = compute_hash(tampered[2])
    assert verify_chain(tampered)["broken_at"] == history[2]["id"]


def test_dropping_the_red_record_is_detected(history):
    assert verify_chain(history[:2] + history[3:]) == {"valid": False, "broken_at": history[3]["id"]}


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

def test_replay_with_the_same_rules_reproduces_every_record_exactly(history, rules):
    for record in history:
        replayed = replay(record, {}, rules)
        assert replayed == record
        report = divergence(record, replayed)
        assert report["identical"] is True
        assert report["decision_changed"] is False
        assert report["rules_changed"] is False


def test_replay_does_not_modify_the_original(history, rules):
    before = copy.deepcopy(history[2])
    replay(history[2], {}, {**rules, "limits": {"channels": {}}})
    assert history[2] == before


def test_replay_under_different_rules_reports_the_divergence(history, rules):
    lenient = {**rules, "limits": {"channels": {"heart_rate": {"unit": "bpm", "red_high": 200}}}}
    replayed = replay(history[2], {}, lenient)
    jsonschema.validate(replayed, _RECORD_SCHEMA)
    assert verify_record(replayed)

    report = divergence(history[2], replayed)
    assert report == {
        "record_id": history[2]["id"],
        "identical": False,
        "decision_changed": True,
        "old_tier": "RED",
        "new_tier": "GREEN",
        "old_action": "ALERT_CMO",
        "new_action": "NO_ACTION",
        "rules_changed": True,
    }


def test_rule_change_that_does_not_touch_the_decision_is_not_a_decision_change(history, rules):
    # Tighter glucose limits are irrelevant to a heart-rate record.
    other = {**rules, "limits": {**rules["limits"], "channels": {**rules["limits"]["channels"], "glucose": {"unit": "mg/dL", "red_high": 100}}}}
    report = divergence(history[2], replay(history[2], {}, other))
    assert report["identical"] is False       # the rules version in the record differs
    assert report["rules_changed"] is True
    assert report["decision_changed"] is False


def test_replay_of_a_tampered_record_exposes_the_real_decision(history, rules):
    tampered = copy.deepcopy(history[2])
    tampered["verdict"]["tier"] = "GREEN"
    tampered["verdict"]["action"] = "NO_ACTION"
    report = divergence(tampered, replay(tampered, {}, rules))
    assert report["decision_changed"] is True
    assert (report["old_tier"], report["new_tier"]) == ("GREEN", "RED")


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE", "FOLLOW_UP"])
def test_build_review(outcome):
    review = build_review("rec-1", outcome, note="looks right", now=_NOW, signing_key=_KEY)
    jsonschema.validate(review, _REVIEW_SCHEMA)
    assert review == {
        "record_id": "rec-1",
        "reviewer": "simulated_flight_surgeon",
        "outcome": outcome,
        "simulated": True,
        "note": "looks right",
        "ts": "2026-11-14T08:00:00Z",
        "signature": review["signature"],
    }
    unsigned = {k: v for k, v in review.items() if k != "signature"}
    assert verify_signature(canonical_json(unsigned), review["signature"], _KEY)


def test_review_signature_covers_every_field():
    base = build_review("rec-1", "AGREE", note="n", now=_NOW, signing_key=_KEY)
    assert build_review("rec-2", "AGREE", note="n", now=_NOW, signing_key=_KEY)["signature"] != base["signature"]
    assert build_review("rec-1", "DISAGREE", note="n", now=_NOW, signing_key=_KEY)["signature"] != base["signature"]
    assert build_review("rec-1", "AGREE", note="m", now=_NOW, signing_key=_KEY)["signature"] != base["signature"]
    assert build_review("rec-1", "AGREE", note="n", now=_NOW, signing_key="other")["signature"] != base["signature"]


def test_review_rejects_unknown_outcomes():
    with pytest.raises(ValueError, match="outcome"):
        build_review("rec-1", "SHRUG")


def test_review_timestamps_are_utc():
    aware = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    assert build_review("rec-1", "AGREE", now=aware)["ts"] == "2026-11-14T10:00:00Z"
    assert build_review("rec-1", "AGREE")["ts"].endswith("Z")


# ---------------------------------------------------------------------------
# rulechange
# ---------------------------------------------------------------------------

def test_no_op_rule_change_changes_nothing(history, rules):
    diff = rulechange(history, {}, rules)
    assert (diff["total"], diff["changed"], diff["unsafe"]) == (4, 0, 0)
    assert [r["record_id"] for r in diff["rows"]] == [r["id"] for r in history]


def test_loosening_a_limit_is_flagged_unsafe(history, rules):
    """Raising the red limit turns a past RED into YELLOW: a new unsafe approval."""
    channels = {**rules["limits"]["channels"], "heart_rate": {"unit": "bpm", "yellow_low": 50, "yellow_high": 100, "red_low": 40, "red_high": 160}}
    diff = rulechange(history, {}, {**rules, "limits": {"channels": channels}})
    assert (diff["total"], diff["changed"], diff["unsafe"]) == (4, 1, 1)
    row = diff["rows"][2]
    assert (row["old_tier"], row["new_tier"], row["changed"], row["unsafe"]) == ("RED", "YELLOW", True, True)
    assert (row["old_action"], row["new_action"]) == ("ALERT_CMO", "REST_AND_HYDRATE")


def test_tightening_a_limit_changes_decisions_but_is_not_unsafe(history, rules):
    channels = {**rules["limits"]["channels"], "heart_rate": {"unit": "bpm", "yellow_high": 75, "red_high": 100}}
    diff = rulechange(history, {}, {**rules, "limits": {"channels": channels}})
    assert [r["new_tier"] for r in diff["rows"]] == ["GREEN", "RED", "RED", "YELLOW"]
    assert (diff["changed"], diff["unsafe"]) == (2, 0)


def test_rulechange_leaves_history_untouched(history, rules):
    before = copy.deepcopy(history)
    rulechange(history, {}, {**rules, "limits": {"channels": {}}})
    assert history == before
    assert verify_chain(history)["valid"] is True


def test_rulechange_on_empty_history(rules):
    assert rulechange([], {}, rules) == {"total": 0, "changed": 0, "unsafe": 0, "rows": []}
