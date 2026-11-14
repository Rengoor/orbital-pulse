"""Tests for b_limits.

Owner: person B
"""

import copy
import json
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from backend.pipelines import discover_pipelines
from backend.pipelines.b_limits.pipeline import run

_REPO = Path(__file__).resolve().parents[2]
with open(_REPO / "data" / "schemas" / "proposal.schema.json") as _f:
    _PROPOSAL_SCHEMA = json.load(_f)
with open(_REPO / "backend" / "pipelines" / "b_limits" / "limits_table.yaml") as _f:
    _TABLE = yaml.safe_load(_f)

_TIER_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2, "GREY": 3}

# A small table of its own, so these tests do not move when the real one is re-sourced.
LIMITS = {
    "channels": {
        "heart_rate": {"unit": "bpm", "yellow_low": 50, "yellow_high": 100, "red_low": 40, "red_high": 130},
        "sleep_hours": {"unit": "h", "yellow_low": 6.0, "yellow_high": None, "red_low": 4.0, "red_high": None},
        "glucose": {"unit": "mg/dL", "yellow_low": None, "yellow_high": None, "red_low": None, "red_high": None},
    }
}
_UNITS = {"heart_rate": "bpm", "sleep_hours": "h", "glucose": "mg/dL", "mood": "score_1_10"}


def _reading(rid, channel, value, unit=None, quality="ok"):
    return {
        "id": rid,
        "astronaut_id": "crew_1",
        "ts": "2026-11-14T08:00:00Z",
        "channel": channel,
        "value": value,
        "unit": unit or _UNITS[channel],
        "source": "simulated",
        "quality": quality,
    }


def _run(readings, limits=LIMITS):
    return run(readings, {"baselines": {}, "rules": {"limits": limits}, "now": datetime(2026, 11, 14)})


def test_discovered_alongside_pipeline_a():
    names = [m.__name__ for m in discover_pipelines()]
    assert "backend.pipelines.b_limits.pipeline" in names
    assert "backend.pipelines.a_statistical.pipeline" in names


def test_pipeline_b_does_not_import_pipeline_a():
    source = (_REPO / "backend" / "pipelines" / "b_limits" / "pipeline.py").read_text(encoding="utf-8")
    assert "a_statistical" not in source
    assert "d_llm" not in source


def test_no_readings_is_green():
    proposal = _run([])
    assert proposal == {
        "pipeline_id": "b_limits",
        "tier": "GREEN",
        "reasons": [],
        "data_fault": False,
        "reading_ids": [],
        "rule_ids": [],
    }


@pytest.mark.parametrize(
    "value,tier,rule",
    [
        (72, "GREEN", None),
        (50, "GREEN", None),      # exactly on a limit is inside it
        (100, "GREEN", None),
        (49.9, "YELLOW", "heart_rate.yellow_low"),
        (100.1, "YELLOW", "heart_rate.yellow_high"),
        (40, "YELLOW", "heart_rate.yellow_low"),
        (130, "YELLOW", "heart_rate.yellow_high"),
        (39.9, "RED", "heart_rate.red_low"),
        (130.1, "RED", "heart_rate.red_high"),
        (0, "RED", "heart_rate.red_low"),
    ],
)
def test_heart_rate_bands(value, tier, rule):
    proposal = _run([_reading("r1", "heart_rate", value)])
    assert proposal["tier"] == tier
    assert proposal["rule_ids"] == ([rule] if rule else [])
    assert proposal["reading_ids"] == (["r1"] if rule else [])
    if rule:
        assert "heart_rate" in proposal["reasons"][0]


def test_one_sided_limits():
    assert _run([_reading("r1", "sleep_hours", 14.0)])["tier"] == "GREEN"   # no upper limit
    assert _run([_reading("r1", "sleep_hours", 5.0)])["tier"] == "YELLOW"
    assert _run([_reading("r1", "sleep_hours", 3.0)])["tier"] == "RED"


def test_unsourced_null_limits_and_unlisted_channels_are_not_checked():
    assert _run([_reading("r1", "glucose", 9999)])["tier"] == "GREEN"
    assert _run([_reading("r1", "mood", -50)])["tier"] == "GREEN"


def test_worst_reading_sets_the_tier_and_every_breach_is_reported():
    proposal = _run(
        [
            _reading("ok", "heart_rate", 72),
            _reading("y", "sleep_hours", 5.0),
            _reading("r", "heart_rate", 150),
        ]
    )
    assert proposal["tier"] == "RED"
    assert proposal["reading_ids"] == ["y", "r"]
    assert proposal["rule_ids"] == ["sleep_hours.yellow_low", "heart_rate.red_high"]
    assert len(proposal["reasons"]) == 2


def test_unit_mismatch_is_grey_not_a_guess():
    # 98.6 F would read as a lethal fever in Celsius, or be waved through: do neither.
    limits = {"channels": {"temperature": {"unit": "C", "yellow_high": 37.5, "red_high": 38.5}}}
    proposal = _run([_reading("t1", "temperature", 98.6, unit="F")], limits)
    assert proposal["tier"] == "GREY"
    assert proposal["rule_ids"] == ["temperature.unit"]
    assert proposal["reading_ids"] == ["t1"]


def test_never_claims_a_data_fault_even_for_fault_quality_readings():
    proposal = _run([_reading("r1", "heart_rate", 150, quality="fault")])
    assert proposal["data_fault"] is False
    assert proposal["tier"] == "RED"


def test_alternate_table_from_context_replaces_the_default():
    reading = [_reading("r1", "heart_rate", 110)]
    assert _run(reading)["tier"] == "YELLOW"
    assert _run(reading, {"channels": {"heart_rate": {"unit": "bpm", "yellow_high": 120}}})["tier"] == "GREEN"
    assert _run(reading, {"channels": {}})["tier"] == "GREEN"


def test_falls_back_to_the_default_table_when_rules_carry_none():
    proposal = run([_reading("r1", "heart_rate", 250)], {"baselines": {}, "rules": {}, "now": None})
    assert proposal["tier"] == "RED"


def test_does_not_mutate_inputs():
    readings = [_reading("r1", "heart_rate", 150)]
    limits = copy.deepcopy(LIMITS)
    before = copy.deepcopy(readings)
    _run(readings, limits)
    assert readings == before
    assert limits == LIMITS


# -- the real table -----------------------------------------------------------

@pytest.mark.parametrize("channel", sorted(_TABLE["channels"]))
def test_real_table_rows_are_well_formed(channel):
    row = _TABLE["channels"][channel]
    assert isinstance(row["unit"], str) and row["unit"]
    assert row["source"]
    bounds = [row.get(k) for k in ("red_low", "yellow_low", "yellow_high", "red_high")]
    present = [b for b in bounds if b is not None]
    assert present, "a row with no limits checks nothing"
    assert present == sorted(present), "limits must be ordered red_low <= yellow_low <= yellow_high <= red_high"


def test_real_table_is_still_marked_placeholder():
    """Remove a row from this check only when its numbers have a real source."""
    assert all(row["source"] == "PLACEHOLDER" for row in _TABLE["channels"].values())


# -- properties ---------------------------------------------------------------

_reading_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "astronaut_id": st.just("crew_1"),
        "ts": st.just("2026-11-14T08:00:00Z"),
        "channel": st.sampled_from(["heart_rate", "sleep_hours", "glucose", "mood", "co2_ppm"]),
        "value": st.floats(min_value=-1000, max_value=10000, allow_nan=False),
        "unit": st.sampled_from(["bpm", "h", "mg/dL", "ppm", "x"]),
        "source": st.just("simulated"),
        "quality": st.sampled_from(["ok", "suspect", "fault"]),
    }
)


@given(readings=st.lists(_reading_st, max_size=10))
def test_output_always_schema_valid(readings):
    for limits in (LIMITS, _TABLE):
        proposal = _run(readings, limits)
        jsonschema.validate(proposal, _PROPOSAL_SCHEMA)
        assert proposal["pipeline_id"] == "b_limits"
        assert set(proposal["reading_ids"]) <= {r["id"] for r in readings}
        assert (proposal["tier"] == "GREEN") == (proposal["reasons"] == [])


@given(readings=st.lists(_reading_st, min_size=1, max_size=8), extra=_reading_st)
def test_more_readings_never_lower_the_tier(readings, extra):
    assert _TIER_ORDER[_run(readings + [extra])["tier"]] >= _TIER_ORDER[_run(readings)["tier"]]


@given(value=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False), bump=st.floats(min_value=0, max_value=500))
def test_tier_is_monotone_above_the_upper_limits(value, bump):
    """Moving further past an upper limit can never look better."""
    low = _run([_reading("r", "heart_rate", value)])["tier"]
    high = _run([_reading("r", "heart_rate", value + bump)])["tier"]
    assert _TIER_ORDER[high] >= _TIER_ORDER[low]
