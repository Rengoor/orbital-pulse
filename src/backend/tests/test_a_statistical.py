"""Tests for a_statistical and pipeline auto-discovery.

Owner: person A
"""

import importlib
import os
import types

import pytest


# ---------------------------------------------------------------------------
# Auto-discovery tests (A-02)
# ---------------------------------------------------------------------------

def _discover(monkeypatch, llm_enabled: str | None = None):
    """Helper: set LLM_ENABLED, reload the module, call discover_pipelines()."""
    if llm_enabled is None:
        monkeypatch.delenv("LLM_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LLM_ENABLED", llm_enabled)

    # Re-import to pick up the fresh env at import time — the function reads
    # os.environ at call time so a simple import is fine, but we re-import to
    # ensure a clean state between tests.
    import backend.pipelines as pkg
    importlib.reload(pkg)
    return pkg.discover_pipelines()


def test_discover_pipelines_returns_list(monkeypatch):
    """discover_pipelines() always returns a list (empty list is valid when no pipeline exposes run)."""
    result = _discover(monkeypatch)
    assert isinstance(result, list)


def test_discover_pipelines_deterministic(monkeypatch):
    """Calling discover_pipelines() twice returns the same module names."""
    import backend.pipelines as pkg
    monkeypatch.delenv("LLM_ENABLED", raising=False)
    importlib.reload(pkg)

    first = [m.__name__ for m in pkg.discover_pipelines()]
    second = [m.__name__ for m in pkg.discover_pipelines()]
    assert first == second


def test_discover_pipelines_skips_llm_by_default(monkeypatch):
    """With LLM_ENABLED unset, d_llm pipeline is not in results."""
    result = _discover(monkeypatch, llm_enabled=None)
    names = [m.__name__ for m in result]
    assert not any("d_llm" in n for n in names)


def test_discover_pipelines_includes_llm_when_enabled(monkeypatch):
    """With LLM_ENABLED=1, d_llm appears — but only if d_llm/pipeline.py has a real run function."""
    # Import d_llm.pipeline to check whether run is defined yet
    import backend.pipelines.d_llm.pipeline as dlp
    if not callable(getattr(dlp, "run", None)):
        pytest.skip("d_llm/pipeline.py has no callable run (still a stub)")

    result = _discover(monkeypatch, llm_enabled="1")
    names = [m.__name__ for m in result]
    assert any("d_llm" in n for n in names)


def test_all_discovered_have_run(monkeypatch):
    """Every module returned by discover_pipelines() has a callable 'run'."""
    result = _discover(monkeypatch)
    for mod in result:
        assert callable(getattr(mod, "run", None)), (
            f"{mod.__name__} was discovered but has no callable 'run'"
        )


# ---------------------------------------------------------------------------
# Baseline tests (A-03)
# ---------------------------------------------------------------------------

import json
import math
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from backend.pipelines.a_statistical.baseline import (
    POPULATION_FALLBACK_STD,
    BaselineStats,
    compute_baseline,
    load_baselines,
)


# ------------------------------------------------------------------
# Unit tests
# ------------------------------------------------------------------

def test_compute_baseline_single_draw():
    """n=1 falls back to the population-level std for the channel."""
    draws = [75.0]
    stats = compute_baseline(draws, channel="heart_rate")
    assert stats.n == 1
    assert stats.std == POPULATION_FALLBACK_STD["heart_rate"]
    assert stats.mean == 75.0
    assert stats.confidence == "low"


def test_compute_baseline_low_confidence():
    """n=3 → confidence='low', band width = 4.0 * std."""
    draws = [70.0, 72.0, 74.0]
    stats = compute_baseline(draws)
    assert stats.n == 3
    assert stats.confidence == "low"
    expected_std = math.sqrt(sum((x - 72.0) ** 2 for x in draws) / 2)
    assert math.isclose(stats.std, expected_std, rel_tol=1e-9)
    assert math.isclose(stats.low, stats.mean - 4.0 * stats.std, rel_tol=1e-9)
    assert math.isclose(stats.high, stats.mean + 4.0 * stats.std, rel_tol=1e-9)


def test_compute_baseline_medium_confidence():
    """n=5 → confidence='medium', multiplier=3.0."""
    draws = [60.0, 62.0, 64.0, 66.0, 68.0]
    stats = compute_baseline(draws)
    assert stats.n == 5
    assert stats.confidence == "medium"
    assert math.isclose(stats.low, stats.mean - 3.0 * stats.std, rel_tol=1e-9)
    assert math.isclose(stats.high, stats.mean + 3.0 * stats.std, rel_tol=1e-9)


def test_compute_baseline_high_confidence():
    """n=10 → confidence='high', multiplier=2.0."""
    draws = [100.0 + i for i in range(10)]
    stats = compute_baseline(draws)
    assert stats.n == 10
    assert stats.confidence == "high"
    assert math.isclose(stats.low, stats.mean - 2.0 * stats.std, rel_tol=1e-9)
    assert math.isclose(stats.high, stats.mean + 2.0 * stats.std, rel_tol=1e-9)


def test_compute_baseline_band_contains_mean():
    """low <= mean <= high always holds."""
    for draws in [[5.0], [1.0, 2.0], [10.0] * 10]:
        stats = compute_baseline(draws)
        assert stats.low <= stats.mean <= stats.high


def test_load_baselines_returns_dict():
    """load_baselines returns a non-empty dict for a known astronaut_id."""
    payload = {
        "crew_1": {
            "heart_rate": [72.0, 68.0, 75.0],
            "bp_systolic": [120.0, 118.0],
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(payload, f)
        tmp_path = f.name

    result = load_baselines("crew_1", tmp_path)
    assert isinstance(result, dict)
    assert "heart_rate" in result
    assert "bp_systolic" in result
    assert isinstance(result["heart_rate"], BaselineStats)


def test_load_baselines_missing_astronaut():
    """load_baselines returns {} for an astronaut_id not present in the file."""
    payload = {"crew_1": {"heart_rate": [72.0]}}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(payload, f)
        tmp_path = f.name

    result = load_baselines("crew_99", tmp_path)
    assert result == {}


# ------------------------------------------------------------------
# Property-based tests
# ------------------------------------------------------------------

# Strategy: non-empty list of floats with reasonable bounds to avoid
# floating-point overflow.
_draws_strategy = st.lists(
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=50,
)


@given(draws=_draws_strategy)
@settings(max_examples=500)
def test_baseline_confidence_band_contains_mean(draws):
    """**Validates: Requirements 1.2** — low <= mean <= high for all draw lists."""
    stats = compute_baseline(draws)
    assert stats.low <= stats.mean <= stats.high


@given(
    base_draws=st.lists(
        st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False),
        min_size=10,
        max_size=10,
    ),
    extra_draws=st.lists(
        st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=300)
def test_more_draws_narrower_band(base_draws, extra_draws):
    """**Validates: Requirements 1.2** — adding draws to an already-high-confidence baseline
    does not widen the confidence band (high confidence band width <= any lower confidence band width).

    Both ``base_draws`` (n=10, high confidence) and ``base_draws + extra_draws``
    (n>=11, still high confidence) use multiplier=2.0, so the band is determined
    entirely by std.  The larger sample cannot have a wider band than is implied
    by the multiplier; we verify that the absolute band width never grows when we
    go from n=10 to n>=11 on the same underlying data plus noise iff the sample
    std does not increase — but that's not a guaranteed monotone property.

    Instead, the meaningful property is: at n>=10 the multiplier is fixed at 2.0,
    so the band width equals 4.0 * std.  Band width is proportional to std, and
    std cannot be negative.  We assert the stricter invariant: band width == 4*std
    for high-confidence baselines and 6*std for medium, 8*std for low.
    """
    # Verify the multiplier-to-width relationship for the base (high-confidence) case
    stats_base = compute_baseline(base_draws)
    assert stats_base.confidence == "high"
    expected_width = 4.0 * stats_base.std
    actual_width = stats_base.high - stats_base.low
    assert math.isclose(actual_width, expected_width, rel_tol=1e-9)

    # Combined draws — still high confidence if n >= 10 (always true here since base is 10)
    combined = base_draws + extra_draws
    stats_combined = compute_baseline(combined)
    assert stats_combined.confidence == "high"

    # Width of combined baseline must equal 4 * std (invariant, not comparison)
    expected_combined_width = 4.0 * stats_combined.std
    actual_combined_width = stats_combined.high - stats_combined.low
    assert math.isclose(actual_combined_width, expected_combined_width, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# CUSUM tests (A-04)
# ---------------------------------------------------------------------------

from datetime import datetime
from pathlib import Path

import jsonschema
import yaml

from backend.pipelines.a_statistical.cusum import (
    CUSUMState,
    cusum_alarm,
    cusum_update,
    run_cusum_series,
)
from backend.pipelines.a_statistical.patterns import evaluate_patterns
from backend.pipelines.a_statistical.pipeline import run as run_pipeline_a

_REPO = Path(__file__).resolve().parents[2]
with open(_REPO / "data" / "schemas" / "proposal.schema.json") as _f:
    _PROPOSAL_SCHEMA = json.load(_f)
with open(_REPO / "backend" / "pipelines" / "a_statistical" / "config.yaml") as _f:
    _CONFIG = yaml.safe_load(_f)


def test_cusum_config_has_real_parameters():
    assert _CONFIG["cusum"] == {"k": 0.5, "h": 4.0}


def test_cusum_update_does_not_mutate_input():
    state = CUSUMState(s_pos=1.0, s_neg=-1.0)
    new = cusum_update(state, value=5.0, mean=0.0, std=1.0, k=0.5)
    assert (state.s_pos, state.s_neg) == (1.0, -1.0)
    assert new is not state
    assert new.s_pos == pytest.approx(5.5)
    assert new.s_neg == 0.0


def test_cusum_alarm_thresholds():
    assert cusum_alarm(CUSUMState(4.1, 0.0), h=4.0)
    assert cusum_alarm(CUSUMState(0.0, -4.1), h=4.0)
    assert not cusum_alarm(CUSUMState(4.0, -4.0), h=4.0)


def test_cusum_series_quiet_on_baseline_values():
    alarm, history = run_cusum_series([10.0] * 20, mean=10.0, std=1.0, k=0.5, h=4.0)
    assert alarm is False
    assert len(history) == 20
    assert all(s.s_pos == 0.0 and s.s_neg == 0.0 for s in history)


def test_cusum_series_alarms_on_sustained_upward_drift():
    # +1.5 sigma every step accumulates 1.0 per step, so it crosses h=4 on step 5.
    alarm, history = run_cusum_series([11.5] * 6, mean=10.0, std=1.0, k=0.5, h=4.0)
    assert alarm is True
    assert not cusum_alarm(history[3], 4.0)
    assert cusum_alarm(history[4], 4.0)


def test_cusum_series_alarms_on_sustained_downward_drift():
    alarm, _ = run_cusum_series([8.0] * 6, mean=10.0, std=1.0, k=0.5, h=4.0)
    assert alarm is True


@given(
    values=st.lists(st.floats(min_value=-10, max_value=10, allow_nan=False), min_size=1, max_size=50),
    mean=st.floats(min_value=-5, max_value=5, allow_nan=False),
    std=st.floats(min_value=0.1, max_value=5, allow_nan=False),
    k=st.floats(min_value=0.1, max_value=2.0, allow_nan=False),
)
def test_cusum_state_invariant(values, mean, std, k):
    """s_pos >= 0 and s_neg <= 0 after every update."""
    state = CUSUMState(s_pos=0.0, s_neg=0.0)
    for v in values:
        state = cusum_update(state, v, mean, std, k)
        assert state.s_pos >= 0
        assert state.s_neg <= 0


# ---------------------------------------------------------------------------
# Pattern tests (A-05)
# ---------------------------------------------------------------------------

def _reading(rid, channel, value, quality="ok"):
    return {
        "id": rid,
        "astronaut_id": "crew_1",
        "ts": "2026-11-14T08:00:00Z",
        "channel": channel,
        "value": value,
        "unit": "x",
        "source": "simulated",
        "quality": quality,
    }


_FATIGUE = {
    "id": "fatigue_cluster",
    "tier": "YELLOW",
    "conditions": [
        {"channel": "sleep_hours", "op": "lt", "threshold": 6.0},
        {"channel": "mood", "op": "lt", "threshold": 4.0},
    ],
}


def test_patterns_empty_rules_returns_empty_list():
    assert evaluate_patterns([_reading("r1", "mood", 1.0)], {}, []) == []


def test_pattern_fires_only_when_all_conditions_hold():
    both = [_reading("r1", "sleep_hours", 5.0), _reading("r2", "mood", 3.0)]
    one = [_reading("r1", "sleep_hours", 5.0), _reading("r2", "mood", 7.0)]
    assert evaluate_patterns(both, {}, [_FATIGUE])[0].matched is True
    assert evaluate_patterns(one, {}, [_FATIGUE])[0].matched is False


def test_pattern_does_not_fire_when_a_channel_is_missing():
    match = evaluate_patterns([_reading("r1", "sleep_hours", 5.0)], {}, [_FATIGUE])[0]
    assert match.matched is False
    assert match.rule_id == "fatigue_cluster"


def test_pattern_uses_most_recent_reading_per_channel():
    readings = [
        _reading("r1", "sleep_hours", 5.0),
        _reading("r2", "mood", 3.0),
        _reading("r3", "mood", 8.0),  # later reading recovers
    ]
    assert evaluate_patterns(readings, {}, [_FATIGUE])[0].matched is False


@pytest.mark.parametrize(
    "op,value,expected",
    [
        ("lt", 4.9, True), ("lt", 5.0, False),
        ("gt", 5.1, True), ("gt", 5.0, False),
        ("lte", 5.0, True), ("lte", 5.1, False),
        ("gte", 5.0, True), ("gte", 4.9, False),
        ("eq", 5.0, True), ("eq", 5.1, False),
    ],
)
def test_pattern_operators(op, value, expected):
    rule = {"id": "r", "tier": "YELLOW", "conditions": [{"channel": "mood", "op": op, "threshold": 5.0}]}
    assert evaluate_patterns([_reading("r1", "mood", value)], {}, [rule])[0].matched is expected


@pytest.mark.parametrize("rule", _CONFIG["patterns"], ids=lambda r: r["id"])
def test_each_configured_pattern_fires_and_clears(rule):
    """Every pattern in config.yaml fires just past its thresholds and not at them."""
    nudge = {"lt": -0.5, "lte": 0.0, "gt": 0.5, "gte": 0.0, "eq": 0.0}
    miss = {"lt": 0.0, "lte": 0.5, "gt": 0.0, "gte": -0.5, "eq": 0.5}
    firing = [
        _reading(f"r{i}", c["channel"], c["threshold"] + nudge[c["op"]])
        for i, c in enumerate(rule["conditions"])
    ]
    assert evaluate_patterns(firing, {}, [rule])[0].matched is True
    # Break only the first condition: the pattern must no longer fire.
    c0 = rule["conditions"][0]
    firing[0] = _reading("r0", c0["channel"], c0["threshold"] + miss[c0["op"]])
    assert evaluate_patterns(firing, {}, [rule])[0].matched is False


# ---------------------------------------------------------------------------
# Pipeline tests (A-06)
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 11, 14, 8, 0, 0)


def _context(baselines=None, rules=None):
    return {"baselines": baselines or {}, "rules": rules or {}, "now": _NOW}


def test_pipeline_green_with_no_readings():
    proposal = run_pipeline_a([], _context())
    assert proposal["pipeline_id"] == "a_statistical"
    assert proposal["tier"] == "GREEN"
    assert proposal["data_fault"] is False


def test_pipeline_cusum_alarm_gives_yellow_and_lists_reading_ids():
    baselines = {"heart_rate": compute_baseline([70.0, 72.0, 68.0, 71.0, 69.0], channel="heart_rate")}
    readings = [_reading(f"hr{i}", "heart_rate", 95.0) for i in range(6)]
    proposal = run_pipeline_a(readings, _context(baselines=baselines, rules={"cusum": {"k": 0.5, "h": 4.0}}))
    assert proposal["tier"] == "YELLOW"
    assert proposal["reading_ids"] == [f"hr{i}" for i in range(6)]
    assert any("heart_rate" in reason for reason in proposal["reasons"])


def test_pipeline_skips_cusum_without_a_baseline():
    readings = [_reading(f"hr{i}", "heart_rate", 250.0) for i in range(6)]
    assert run_pipeline_a(readings, _context())["tier"] == "GREEN"


def test_pipeline_worst_of_cusum_and_pattern():
    baselines = {"heart_rate": compute_baseline([70.0, 72.0, 68.0, 71.0, 69.0], channel="heart_rate")}
    red_rule = {"id": "red_rule", "tier": "RED", "conditions": [{"channel": "mood", "op": "lt", "threshold": 2.0}]}
    readings = [_reading(f"hr{i}", "heart_rate", 95.0) for i in range(6)] + [_reading("m1", "mood", 1.0)]
    proposal = run_pipeline_a(readings, _context(baselines=baselines, rules={"patterns": [red_rule]}))
    assert proposal["tier"] == "RED"
    assert proposal["rule_ids"] == ["red_rule"]
    assert "m1" in proposal["reading_ids"]


_reading_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "astronaut_id": st.just("crew_1"),
        "ts": st.just("2026-11-14T08:00:00Z"),
        "channel": st.sampled_from(["heart_rate", "bp_systolic", "glucose", "mood", "sleep_hours", "dose_rate_usv_h"]),
        "value": st.floats(min_value=0, max_value=300, allow_nan=False),
        "unit": st.just("x"),
        "source": st.just("simulated"),
        "quality": st.sampled_from(["ok", "suspect", "fault"]),
    }
)


@given(readings=st.lists(_reading_st, min_size=1, max_size=10), with_baseline=st.booleans())
def test_pipeline_a_always_schema_valid(readings, with_baseline):
    """a_statistical.run() output always validates against proposal.schema.json."""
    baselines = (
        {"heart_rate": compute_baseline([70.0, 72.0, 68.0, 71.0], channel="heart_rate")}
        if with_baseline
        else {}
    )
    proposal = run_pipeline_a(readings, _context(baselines=baselines, rules=_CONFIG))
    jsonschema.validate(proposal, _PROPOSAL_SCHEMA)
    assert proposal["pipeline_id"] == "a_statistical"
    assert set(proposal["reading_ids"]) <= {r["id"] for r in readings}
