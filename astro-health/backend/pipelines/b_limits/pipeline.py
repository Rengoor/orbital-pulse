"""Absolute-limits check against limits_table.yaml. Written independently of pipeline A.

Pipeline A asks "is this unusual for this person?". This pipeline asks the
other question: "is this outside fixed limits for anyone?". It knows nothing
about baselines, drift or patterns, and never sees pipeline A's output.

Owner: person B
"""

from __future__ import annotations

from pathlib import Path

import yaml

from backend.common.schema_check import validate

PIPELINE_ID = "b_limits"

_TIER_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2, "GREY": 3}

_HERE = Path(__file__).resolve().parent
_DEFAULT_LIMITS_PATH = _HERE / "limits_table.yaml"
_SCHEMA_PATH = _HERE.parents[2] / "data" / "schemas" / "proposal.schema.json"

# (bound, tier, comparison) checked most severe first; the first hit wins.
_CHECKS = (
    ("red_low", "RED", "below"),
    ("red_high", "RED", "above"),
    ("yellow_low", "YELLOW", "below"),
    ("yellow_high", "YELLOW", "above"),
)

_default_limits: dict | None = None


def _load_default_limits() -> dict:
    global _default_limits
    if _default_limits is None:
        with _DEFAULT_LIMITS_PATH.open(encoding="utf-8") as f:
            _default_limits = yaml.safe_load(f) or {}
    return _default_limits


def _breach(value: float, limits: dict) -> tuple[str, str, float] | None:
    """Return (tier, bound name, bound value) for the most severe limit crossed."""
    for bound, tier, direction in _CHECKS:
        threshold = limits.get(bound)
        if threshold is None:  # not yet sourced: nothing to check against
            continue
        threshold = float(threshold)
        if (direction == "below" and value < threshold) or (direction == "above" and value > threshold):
            return tier, bound, threshold
    return None


def run(readings: list[dict], context: dict) -> dict:
    """Check every reading against the limits table; return one Proposal.

    The table comes from ``context["rules"]["limits"]`` (so Earth can replay
    with an alternate table) and falls back to limits_table.yaml beside this
    file. A value exactly on a limit is inside it. A reading whose unit differs
    from the table's cannot be compared, which is reported as GREY rather than
    guessed at. This pipeline never claims a data fault.
    """
    rules = context.get("rules") or {}
    table = rules.get("limits")
    if table is None:
        table = _load_default_limits()
    channels: dict = table.get("channels") or {}

    tier = "GREEN"
    reasons: list[str] = []
    reading_ids: list[str] = []
    rule_ids: list[str] = []

    def flag(reading: dict, new_tier: str, reason: str, rule_id: str) -> None:
        nonlocal tier
        if _TIER_ORDER[new_tier] > _TIER_ORDER[tier]:
            tier = new_tier
        reasons.append(reason)
        if reading["id"] not in reading_ids:
            reading_ids.append(reading["id"])
        if rule_id not in rule_ids:
            rule_ids.append(rule_id)

    for reading in readings:
        channel = reading["channel"]
        limits = channels.get(channel)
        if not limits:
            continue

        expected_unit = limits.get("unit")
        if expected_unit and reading["unit"] != expected_unit:
            flag(
                reading,
                "GREY",
                f"{channel} reported in {reading['unit']!r} but limits are in {expected_unit!r}; cannot verify",
                f"{channel}.unit",
            )
            continue

        value = float(reading["value"])
        breach = _breach(value, limits)
        if breach is not None:
            breach_tier, bound, threshold = breach
            side = "below" if bound.endswith("low") else "above"
            flag(
                reading,
                breach_tier,
                f"{channel}={value:g} {expected_unit or reading['unit']} is {side} the"
                f" {bound.split('_')[0]} limit of {threshold:g}",
                f"{channel}.{bound}",
            )

    proposal = {
        "pipeline_id": PIPELINE_ID,
        "tier": tier,
        "reasons": reasons,
        "data_fault": False,
        "reading_ids": reading_ids,
        "rule_ids": rule_ids,
    }
    validate(proposal, str(_SCHEMA_PATH))
    return proposal
