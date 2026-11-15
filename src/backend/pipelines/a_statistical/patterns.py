"""Multi-channel pattern rules (e.g. sleep + mood + CO2 drift).

Owner: person A
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.pipelines.a_statistical.baseline import BaselineStats

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PatternMatch:
    rule_id: str
    matched: bool
    reasons: list[str]
    tier: str  # tier this pattern contributes if matched


# ---------------------------------------------------------------------------
# Operator evaluation
# ---------------------------------------------------------------------------

_OPERATORS = {
    "lt":  lambda v, t: v < t,
    "gt":  lambda v, t: v > t,
    "lte": lambda v, t: v <= t,
    "gte": lambda v, t: v >= t,
    "eq":  lambda v, t: v == t,
}


def _apply_op(op: str, value: float, threshold: float) -> bool:
    """Return True if the operator condition holds."""
    fn = _OPERATORS.get(op)
    if fn is None:
        raise ValueError(f"Unknown operator: {op!r}")
    return fn(value, threshold)


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_patterns(
    readings: list[dict],
    baselines: dict[str, BaselineStats],
    rules: list[dict],
) -> list[PatternMatch]:
    """Evaluate each pattern rule against the current reading window.

    A pattern fires when ALL its channel conditions are satisfied.  For each
    condition the most-recent reading matching that channel is used.  If no
    reading exists for a required channel the condition is not satisfied and
    the pattern does not fire.

    Returns an empty list when ``rules`` is empty.
    """
    if not rules:
        return []

    # Build a channel→most-recent-reading index (readings are assumed to be in
    # time order, so the last entry for a channel is the most recent).
    latest: dict[str, dict] = {}
    for reading in readings:
        channel = reading.get("channel")
        if channel is not None:
            latest[channel] = reading

    results: list[PatternMatch] = []

    for rule in rules:
        rule_id: str = rule.get("id", "")
        tier: str = rule.get("tier", "GREEN")
        conditions: list[dict] = rule.get("conditions", [])

        matched_reasons: list[str] = []
        all_satisfied = True

        for cond in conditions:
            channel: str = cond["channel"]
            op: str = cond["op"]
            threshold: float = float(cond["threshold"])

            reading = latest.get(channel)
            if reading is None:
                # Required channel not present — pattern cannot fire
                all_satisfied = False
                break

            value: float = float(reading["value"])
            if _apply_op(op, value, threshold):
                matched_reasons.append(f"{channel}={value} {op} {threshold}")
            else:
                all_satisfied = False
                break

        if all_satisfied and conditions:
            results.append(
                PatternMatch(
                    rule_id=rule_id,
                    matched=True,
                    reasons=matched_reasons,
                    tier=tier,
                )
            )
        else:
            results.append(
                PatternMatch(
                    rule_id=rule_id,
                    matched=False,
                    reasons=[],
                    tier=tier,
                )
            )

    return results
