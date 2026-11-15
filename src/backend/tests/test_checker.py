"""Tests for checker.

Owner: person A and person B
"""

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from backend.checker.checker import (
    CHECKER_VERSION,
    _default_action,
    _hash_policy,
    check,
)
from backend.checker.gates import (
    SEVERITY_ORDER,
    TIER_ORDER,
    detect_contradictions,
    drop_confirmed_fault_readings,
    gate_data_fault,
    gate_grey_escalation,
    gate_whitelist,
    gate_worst_of,
)

_REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = str(_REPO / "backend" / "checker" / "policy.yaml")
_FIXTURES = _REPO / "data" / "fixtures"

with open(_REPO / "data" / "schemas" / "verdict.schema.json") as _f:
    _VERDICT_SCHEMA = json.load(_f)
with open(POLICY_PATH) as _f:
    _POLICY = yaml.safe_load(_f)

TIERS = ["GREEN", "YELLOW", "RED", "GREY"]
ACTIONS = _POLICY["actions"]


def _proposal(tier, data_fault=False, pipeline_id="p", reading_ids=None):
    return {
        "pipeline_id": pipeline_id,
        "tier": tier,
        "reasons": [f"{pipeline_id} says {tier}"],
        "data_fault": data_fault,
        "reading_ids": list(reading_ids or []),
    }


def _reading(rid, quality="ok"):
    return {
        "id": rid,
        "astronaut_id": "crew_1",
        "ts": "2026-11-14T08:00:00Z",
        "channel": "heart_rate",
        "value": 72.0,
        "unit": "bpm",
        "source": "simulated",
        "quality": quality,
    }


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

proposal_st = st.fixed_dictionaries(
    {
        "pipeline_id": st.sampled_from(["a_statistical", "b_limits", "c_other"]),
        "tier": st.sampled_from(TIERS),
        "reasons": st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=3),
        "data_fault": st.booleans(),
        "reading_ids": st.lists(st.sampled_from(["r0", "r1", "r2", "r3"]), max_size=4, unique=True),
    }
)

llm_proposal_st = proposal_st.map(lambda p: {**p, "pipeline_id": "d_llm"})

reading_st = st.fixed_dictionaries(
    {
        "id": st.sampled_from(["r0", "r1", "r2", "r3"]),
        "astronaut_id": st.just("crew_1"),
        "ts": st.just("2026-11-14T08:00:00Z"),
        "channel": st.sampled_from(["heart_rate", "bp_systolic", "glucose"]),
        "value": st.floats(min_value=0, max_value=300, allow_nan=False),
        "unit": st.just("bpm"),
        "source": st.just("simulated"),
        "quality": st.sampled_from(["ok", "suspect", "fault"]),
    }
)

readings_st = st.lists(reading_st, max_size=4, unique_by=lambda r: r["id"])


# ---------------------------------------------------------------------------
# gate_worst_of
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tiers,expected",
    [
        (["GREEN"], "GREEN"),
        (["GREEN", "YELLOW"], "YELLOW"),
        (["RED", "YELLOW", "GREEN"], "RED"),
        (["RED", "GREY"], "GREY"),
        (["GREY", "GREEN"], "GREY"),
        (["YELLOW", "YELLOW"], "YELLOW"),
    ],
)
def test_gate_worst_of_table(tiers, expected):
    assert gate_worst_of([_proposal(t) for t in tiers]) == expected


def test_gate_worst_of_fixture_proposal():
    fixture = json.loads((_FIXTURES / "sample_proposal.json").read_text())
    assert gate_worst_of([fixture]) == fixture["tier"]
    assert gate_worst_of([fixture, _proposal("RED")]) == "RED"


@given(proposals=st.lists(proposal_st, min_size=1, max_size=8))
def test_worst_of_gate(proposals):
    """The gate returns exactly the worst proposal tier, never anything lower."""
    tier = gate_worst_of(proposals)
    assert TIER_ORDER[tier] == max(TIER_ORDER[p["tier"]] for p in proposals)


# ---------------------------------------------------------------------------
# gate_data_fault
# ---------------------------------------------------------------------------

def test_gate_data_fault_never_lowers_grey_even_when_unanimous():
    proposals = [
        _proposal("GREY", data_fault=True, reading_ids=["r1"]),
        _proposal("RED", data_fault=True, reading_ids=["r1"]),
    ]
    assert gate_data_fault(proposals, "GREY", readings=[_reading("r1", "fault")]) == "GREY"


def test_gate_data_fault_drops_confirmed_fault_and_reevaluates_on_what_remains():
    readings = [_reading("r1", "fault"), _reading("r2", "ok")]
    proposals = [
        _proposal("RED", data_fault=True, pipeline_id="a", reading_ids=["r1"]),
        _proposal("YELLOW", data_fault=True, pipeline_id="b", reading_ids=["r1"]),
    ]
    remaining, dropped = drop_confirmed_fault_readings(readings, proposals)
    assert dropped == {"r1"}
    assert [r["id"] for r in remaining] == ["r2"]

    tier = gate_data_fault(
        proposals,
        "RED",
        readings=readings,
        reevaluate=lambda rem: [_proposal("YELLOW" if any(r["id"] == "r2" for r in rem) else "GREEN")],
    )
    assert tier == "YELLOW"


def test_gate_data_fault_when_all_readings_dropped_returns_green():
    readings = [_reading("r1", "fault")]
    proposals = [
        _proposal("RED", data_fault=True, pipeline_id="a", reading_ids=["r1"]),
        _proposal("YELLOW", data_fault=True, pipeline_id="b", reading_ids=["r1"]),
    ]
    assert gate_data_fault(proposals, "RED", readings=readings) == "GREEN"


@pytest.mark.parametrize("current", TIERS)
def test_gate_data_fault_holds_when_one_pipeline_disagrees(current):
    proposals = [_proposal(current, data_fault=True), _proposal("GREEN", data_fault=False)]
    assert gate_data_fault(proposals, current) == current


def test_gate_data_fault_requires_boolean_true():
    # A truthy non-boolean must not unlock fault dropping.
    proposals = [{**_proposal("RED"), "data_fault": "yes"}]
    assert gate_data_fault(proposals, "RED") == "RED"


@given(proposals=st.lists(proposal_st, min_size=1, max_size=8))
def test_data_fault_safety(proposals):
    """Tier is lowered only when ALL proposals agree data_fault=True, and GREY never steps down."""
    worst = gate_worst_of(proposals)
    after = gate_data_fault(proposals, worst)
    assert TIER_ORDER[after] <= TIER_ORDER[worst]
    if worst == "GREY":
        assert after == "GREY"
    if TIER_ORDER[after] < TIER_ORDER[worst]:
        assert all(p["data_fault"] is True for p in proposals)


# ---------------------------------------------------------------------------
# gate_whitelist
# ---------------------------------------------------------------------------

def test_gate_whitelist_passes_listed_action():
    assert gate_whitelist("ALERT_CMO", ACTIONS) == "ALERT_CMO"


@pytest.mark.parametrize(
    "action,whitelist,expected",
    [
        ("NO_ACTION", ["RECHECK_IN_1H", "ALERT_CMO"], "RECHECK_IN_1H"),
        ("REST_AND_HYDRATE", ["NO_ACTION", "ALERT_CMO", "CONTACT_GROUND_URGENT"], "ALERT_CMO"),
        ("ALERT_CMO", ["NO_ACTION", "CONTACT_GROUND_URGENT"], "CONTACT_GROUND_URGENT"),
        ("CONTACT_GROUND_URGENT", ["NO_ACTION", "ALERT_CMO"], "ALERT_CMO"),
        ("MADE_UP_ACTION", ["NO_ACTION", "ALERT_CMO"], "ALERT_CMO"),
        ("ALERT_CMO", [], "CONTACT_GROUND_URGENT"),
    ],
)
def test_gate_whitelist_escalates_when_action_is_not_listed(action, whitelist, expected):
    assert gate_whitelist(action, whitelist) == expected


@given(
    action=st.sampled_from(SEVERITY_ORDER),
    whitelist=st.lists(st.sampled_from(SEVERITY_ORDER), min_size=1, unique=True),
)
def test_gate_whitelist_never_picks_a_milder_action_when_a_stronger_one_is_listed(action, whitelist):
    chosen = gate_whitelist(action, whitelist, action_order=_POLICY["action_order"])
    assert chosen in whitelist
    if any(SEVERITY_ORDER.index(a) >= SEVERITY_ORDER.index(action) for a in whitelist):
        assert SEVERITY_ORDER.index(chosen) >= SEVERITY_ORDER.index(action)


def test_gate_whitelist_reads_action_strength_order_from_policy(tmp_path):
    policy = copy.deepcopy(_POLICY)
    # Custom policy action_order where USE_PROTOCOL_CARD is ranked above ALERT_CMO
    policy["action_order"] = [
        "NO_ACTION",
        "RECHECK_IN_1H",
        "REST_AND_HYDRATE",
        "ALERT_CMO",
        "USE_PROTOCOL_CARD",
        "CONTACT_GROUND_URGENT",
    ]
    policy["actions"] = ["NO_ACTION", "USE_PROTOCOL_CARD", "CONTACT_GROUND_URGENT"]
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy))
    verdict = check([_proposal("RED")], [], str(path))
    assert verdict["action"] == "USE_PROTOCOL_CARD"


# ---------------------------------------------------------------------------
# Contradiction detection with tolerance band
# ---------------------------------------------------------------------------

def test_contradiction_within_tolerance_band_does_not_escalate():
    r1 = {**_reading("r1"), "channel": "heart_rate", "value": 72.0}
    r2 = {**_reading("r2"), "channel": "heart_rate", "value": 74.5}  # diff 2.5 <= 3.0 tolerance
    assert detect_contradictions([r1, r2]) == set()
    assert gate_grey_escalation([r1, r2], [_proposal("GREEN")], "GREEN") == "GREEN"


def test_contradiction_beyond_tolerance_band_escalates_to_grey():
    r1 = {**_reading("r1"), "channel": "heart_rate", "value": 72.0}
    r2 = {**_reading("r2"), "channel": "heart_rate", "value": 80.0}  # diff 8.0 > 3.0 tolerance
    assert detect_contradictions([r1, r2]) == {"r1", "r2"}
    assert gate_grey_escalation([r1, r2], [_proposal("GREEN")], "GREEN") == "GREY"
    assert check([_proposal("GREEN")], [r1, r2], POLICY_PATH)["tier"] == "GREY"


# ---------------------------------------------------------------------------
# gate_grey_escalation
# ---------------------------------------------------------------------------

def test_grey_when_fault_reading_is_unclaimed():
    assert gate_grey_escalation([_reading("r1", "fault")], [_proposal("GREEN")], "GREEN") == "GREY"


def test_no_grey_when_a_pipeline_claims_the_fault():
    proposals = [_proposal("YELLOW", data_fault=True, reading_ids=["r1"])]
    assert gate_grey_escalation([_reading("r1", "fault")], proposals, "YELLOW") == "YELLOW"


def test_grey_when_reading_id_listed_without_data_fault_flag():
    proposals = [_proposal("YELLOW", data_fault=False, reading_ids=["r1"])]
    assert gate_grey_escalation([_reading("r1", "fault")], proposals, "YELLOW") == "GREY"


def test_grey_when_only_some_fault_readings_are_claimed():
    readings = [_reading("r1", "fault"), _reading("r2", "fault")]
    proposals = [_proposal("YELLOW", data_fault=True, reading_ids=["r1"])]
    assert gate_grey_escalation(readings, proposals, "RED") == "GREY"


@pytest.mark.parametrize("quality", ["ok", "suspect"])
def test_no_grey_without_fault_readings(quality):
    assert gate_grey_escalation([_reading("r1", quality)], [_proposal("RED")], "RED") == "RED"


@given(
    readings=st.lists(reading_st.map(lambda r: {**r, "quality": "fault"}), min_size=1, max_size=4),
    proposals=st.lists(proposal_st.map(lambda p: {**p, "data_fault": False}), min_size=1, max_size=4),
    current=st.sampled_from(TIERS),
)
def test_grey_escalation_on_unverified_fault(readings, proposals, current):
    """Fault readings that no pipeline claims as a known data fault always give GREY."""
    assert gate_grey_escalation(readings, proposals, current) == "GREY"


# ---------------------------------------------------------------------------
# Gate purity
# ---------------------------------------------------------------------------

@given(proposals=st.lists(proposal_st, min_size=1, max_size=6), readings=readings_st)
def test_gates_and_check_do_not_mutate_inputs(proposals, readings):
    p_before, r_before = copy.deepcopy(proposals), copy.deepcopy(readings)
    tier = gate_worst_of(proposals)
    tier = gate_data_fault(proposals, tier)
    gate_grey_escalation(readings, proposals, tier)
    check(proposals, readings, POLICY_PATH)
    assert proposals == p_before
    assert readings == r_before


# ---------------------------------------------------------------------------
# checker.check
# ---------------------------------------------------------------------------

def test_hash_policy_is_sha256_of_file_bytes():
    expected = hashlib.sha256(Path(POLICY_PATH).read_bytes()).hexdigest()
    assert _hash_policy(POLICY_PATH) == expected
    assert len(expected) == 64


def test_default_action_per_tier_comes_from_policy():
    for tier in TIERS:
        assert _default_action(tier, _POLICY) == _POLICY["default_actions"][tier]
    assert _default_action("UNKNOWN", _POLICY) == "CONTACT_GROUND_URGENT"


@pytest.mark.parametrize(
    "proposals,readings,tier,action",
    [
        # all nominal
        ([_proposal("GREEN", pipeline_id="a"), _proposal("GREEN", pipeline_id="b")], [_reading("r1")],
         "GREEN", "NO_ACTION"),
        # pipelines disagree: escalation wins
        ([_proposal("GREEN", pipeline_id="a"), _proposal("RED", pipeline_id="b")], [_reading("r1")],
         "RED", "ALERT_CMO"),
        # unanimous confirmed data fault drops the faulted reading and re-evaluates on what remains
        ([_proposal("RED", True, "a", ["r1"]), _proposal("YELLOW", True, "b", ["r1"])], [_reading("r1", "fault")],
         "GREEN", "NO_ACTION"),
        # unanimous confirmed data fault never steps GREY down to RED
        ([_proposal("GREY", True, "a", ["r1"]), _proposal("RED", True, "b", ["r1"])], [_reading("r1", "fault")],
         "GREY", "CONTACT_GROUND_URGENT"),
        # only one pipeline says data fault: no drop
        ([_proposal("RED", True, "a", ["r1"]), _proposal("GREEN", False, "b")], [_reading("r1", "fault")],
         "RED", "ALERT_CMO"),
        # fault reading nobody vouches for: GREY, even from GREEN
        ([_proposal("GREEN", pipeline_id="a")], [_reading("r1", "fault")],
         "GREY", "CONTACT_GROUND_URGENT"),
        # confirmed fault drops r1, but unclaimed fault r2 still forces GREY
        ([_proposal("RED", True, "a", ["r1"])], [_reading("r1", "fault"), _reading("r2", "fault")],
         "GREY", "CONTACT_GROUND_URGENT"),
        # a dead pipeline reports GREY
        ([_proposal("GREEN", pipeline_id="b"), _proposal("GREY", pipeline_id="a")], [_reading("r1")],
         "GREY", "CONTACT_GROUND_URGENT"),
    ],
)
def test_check_scenarios(proposals, readings, tier, action):
    verdict = check(proposals, readings, POLICY_PATH)
    assert (verdict["tier"], verdict["action"]) == (tier, action)


def test_check_verdict_fields():
    verdict = check(
        [_proposal("GREEN", pipeline_id="a"), _proposal("RED", pipeline_id="b")],
        [_reading("r1")],
        POLICY_PATH,
    )
    jsonschema.validate(verdict, _VERDICT_SCHEMA)
    assert verdict["ruleset_hash"] == _hash_policy(POLICY_PATH)
    assert verdict["checker_version"] == CHECKER_VERSION
    assert verdict["reasons"] == ["a says GREEN", "b says RED"]
    assert verdict["overruled_pipelines"] == ["a"]


def test_check_ruleset_hash_tracks_policy_changes(tmp_path):
    altered = tmp_path / "policy.yaml"
    altered.write_bytes(Path(POLICY_PATH).read_bytes() + b"\n# tampered\n")
    verdict = check([_proposal("GREEN")], [], str(altered))
    assert verdict["ruleset_hash"] == _hash_policy(str(altered))
    assert verdict["ruleset_hash"] != _hash_policy(POLICY_PATH)


def test_check_escalates_when_default_action_is_not_whitelisted(tmp_path):
    policy = copy.deepcopy(_POLICY)
    policy["actions"] = [a for a in policy["actions"] if a != "REST_AND_HYDRATE"]
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy))
    verdict = check([_proposal("YELLOW")], [], str(path))
    assert verdict["action"] == "USE_PROTOCOL_CARD"


def test_check_missing_policy_raises():
    with pytest.raises(FileNotFoundError):
        check([_proposal("GREEN")], [], str(_REPO / "no_such_policy.yaml"))


@given(proposals=st.lists(proposal_st, min_size=1, max_size=8), readings=readings_st)
def test_action_whitelist(proposals, readings):
    """verdict.action is always on the policy whitelist, and the verdict is schema-valid."""
    verdict = check(proposals, readings, POLICY_PATH)
    assert verdict["action"] in ACTIONS
    jsonschema.validate(verdict, _VERDICT_SCHEMA)


@given(proposals=st.lists(proposal_st, min_size=1, max_size=8), readings=readings_st)
def test_verdict_never_steps_down_grey_and_holds_worst_without_unanimous_fault(proposals, readings):
    verdict = check(proposals, readings, POLICY_PATH)
    worst = max(TIER_ORDER[p["tier"]] for p in proposals)
    if worst == TIER_ORDER["GREY"]:
        assert verdict["tier"] == "GREY"
    if not all(p["data_fault"] for p in proposals):
        assert TIER_ORDER[verdict["tier"]] >= worst


@given(
    core=st.lists(proposal_st, min_size=1, max_size=6),
    llm=llm_proposal_st,
    readings=readings_st,
)
def test_llm_never_lowers(core, llm, readings):
    """Adding a d_llm proposal, whatever it claims, never lowers the verdict tier."""
    without = check(core, readings, POLICY_PATH)
    with_llm = check(core + [llm], readings, POLICY_PATH)
    assert TIER_ORDER[with_llm["tier"]] >= TIER_ORDER[without["tier"]]


def test_llm_cannot_suppress_grey_by_claiming_a_data_fault():
    readings = [_reading("r1", "fault")]
    core = [_proposal("GREEN", pipeline_id="a_statistical")]
    llm = _proposal("GREEN", data_fault=True, pipeline_id="d_llm", reading_ids=["r1"])
    assert check(core, readings, POLICY_PATH)["tier"] == "GREY"
    assert check(core + [llm], readings, POLICY_PATH)["tier"] == "GREY"


def test_llm_can_raise_the_tier():
    core = [_proposal("GREEN", pipeline_id="a_statistical")]
    llm = _proposal("RED", pipeline_id="d_llm")
    verdict = check(core + [llm], [_reading("r1")], POLICY_PATH)
    assert verdict["tier"] == "RED"
    assert verdict["overruled_pipelines"] == ["a_statistical"]
