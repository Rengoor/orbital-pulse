"""Personal baselines from pre-flight draws, plus baseline-confidence (wide, low-confidence band when few draws).

Owner: person A
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Population-level fallback standard deviations.
# Used when n < 2 (single draw — not enough to compute sample std).
# ---------------------------------------------------------------------------

POPULATION_FALLBACK_STD: dict[str, float] = {
    "bp_systolic":       15.0,
    "bp_diastolic":      10.0,
    "heart_rate":        15.0,
    "glucose":           20.0,
    "temperature":        0.5,
    "sleep_hours":        1.5,
    "mood":               2.0,
    "co2_ppm":          200.0,
    "exercise_minutes":  15.0,
    "dose_rate_usv_h":    5.0,
    "blood_analyte":      1.0,
}

_DEFAULT_FALLBACK_STD = 1.0  # for channels not in the table


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BaselineStats:
    mean: float
    std: float
    n: int
    low: float
    high: float
    confidence: str  # "high" | "medium" | "low"


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def compute_baseline(draws: list[float], channel: str = "blood_analyte") -> BaselineStats:
    """Compute a personal baseline from pre-flight measurement draws.

    Parameters
    ----------
    draws:
        Pre-flight measurements for one channel. Must be non-empty.
    channel:
        Channel name, used only when n < 2 to look up the population fallback
        standard deviation. Defaults to "blood_analyte".

    Returns
    -------
    BaselineStats
        Always satisfies ``stats.low <= stats.mean <= stats.high``.
    """
    if not draws:
        raise ValueError("draws must be non-empty (len >= 1)")

    n = len(draws)
    mean = sum(draws) / n

    if n >= 2:
        # Sample standard deviation (Bessel-corrected, denominator n-1)
        variance = sum((x - mean) ** 2 for x in draws) / (n - 1)
        std = math.sqrt(variance)
    else:
        # Single draw — fall back to population-level std for the channel
        std = POPULATION_FALLBACK_STD.get(channel, _DEFAULT_FALLBACK_STD)

    # Confidence band: wider when fewer draws
    if n >= 10:
        multiplier = 2.0
        confidence = "high"
    elif n >= 4:
        multiplier = 3.0
        confidence = "medium"
    else:
        multiplier = 4.0
        confidence = "low"

    low = mean - multiplier * std
    high = mean + multiplier * std

    # Postcondition: band always contains the mean
    assert low <= mean <= high, (
        f"Invariant violated: low={low} mean={mean} high={high}"
    )

    return BaselineStats(mean=mean, std=std, n=n, low=low, high=high, confidence=confidence)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_baselines(astronaut_id: str, draws_path: str) -> dict[str, BaselineStats]:
    """Load pre-flight draws from a JSON file and compute baselines.

    The JSON file must have the structure::

        {
          "crew_1": {
            "heart_rate": [72.0, 68.0, 75.0],
            "bp_systolic": [120.0, 118.0]
          }
        }

    Parameters
    ----------
    astronaut_id:
        Key to look up in the top-level JSON object.
    draws_path:
        Path to the JSON draws file.

    Returns
    -------
    dict[str, BaselineStats]
        ``{channel: BaselineStats}`` for the given astronaut, or ``{}`` if the
        astronaut is not found in the file.
    """
    path = Path(draws_path)
    with path.open() as f:
        data = json.load(f)

    crew_draws = data.get(astronaut_id)
    if crew_draws is None:
        return {}

    result: dict[str, BaselineStats] = {}
    for channel, draws in crew_draws.items():
        stats = compute_baseline(draws, channel=channel)
        # Postcondition check per channel
        assert stats.low <= stats.mean <= stats.high, (
            f"Invariant violated for channel {channel!r}: "
            f"low={stats.low} mean={stats.mean} high={stats.high}"
        )
        result[channel] = stats

    return result
