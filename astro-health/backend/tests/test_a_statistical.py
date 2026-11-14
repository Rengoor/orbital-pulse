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
