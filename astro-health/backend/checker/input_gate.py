"""Input integrity gate: decides whether each reading is usable. Sits between Gather and Evaluate.

This is a validation step, not a medical one. It never looks at whether a
value is healthy, only at whether it can be trusted as data: is it fresh, in
the expected unit, uniquely identified, traceable to its source, and not
contradicted by another reading. What a failed check means for the verdict is
the Checker's decision (gates.gate_data_requirements), not this module's.

Statuses:
  valid    usable
  fault    the sensor itself reported quality="fault" (handled by the GREY escalation gate)
  stale    older than the policy allows
  invalid  cannot be used: wrong unit, bad or future timestamp, duplicate id,
           contradicted by another reading, or real-data source with no provenance

Owner: person A and person B
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.checker.gates import detect_contradictions

USABLE_STATUSES = ("valid", "fault")

_REAL_DATA_SOURCES = ("nasa_osdr", "nasa_radlab", "nasa_donki")


def _to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _parse_ts(ts) -> datetime | None:
    try:
        return _to_utc(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


def evaluate(
    readings: list[dict],
    now: datetime,
    requirements: dict | None = None,
    tolerances: dict[str, float] | None = None,
) -> dict:
    """Return an integrity report for *readings* at decision time *now*.

    Pure: no clock, no I/O, inputs untouched. The report lists every reading
    with its status and the issues found, preserves the real/simulated label,
    and summarises the counts.
    """
    requirements = requirements or {}
    channel_rules: dict = requirements.get("channels") or {}
    default_max_age = requirements.get("max_reading_age_s")
    max_future = requirements.get("max_future_skew_s")
    now_utc = _to_utc(now)

    # Readings on the same channel and timestamp that differ by more than the
    # policy tolerance for that channel contradict each other.
    contradicting = detect_contradictions(readings, tolerances=tolerances)

    seen_ids: set = set()
    entries: list[dict] = []

    for r in readings:
        channel = r.get("channel")
        rules = channel_rules.get(channel) or {}
        issues: list[str] = []
        stale = False

        if r.get("id") in seen_ids:
            issues.append("duplicate_id")
        seen_ids.add(r.get("id"))

        value = r.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            issues.append("value_not_a_finite_number")

        expected_unit = rules.get("unit")
        if expected_unit and r.get("unit") != expected_unit:
            issues.append(f"unit_mismatch: got {r.get('unit')!r}, expected {expected_unit!r}")

        ts = _parse_ts(r.get("ts"))
        if ts is None:
            issues.append("unreadable_timestamp")
        else:
            age_s = (now_utc - ts).total_seconds()
            max_age = rules.get("max_reading_age_s", default_max_age)
            if max_future is not None and age_s < -float(max_future):
                issues.append(f"timestamp_in_future: {-age_s:.0f}s ahead of the decision time")
            elif max_age is not None and age_s > float(max_age):
                stale = True

        if r.get("id") in contradicting:
            issues.append("contradicts_another_reading_at_the_same_time")

        if r.get("source") in _REAL_DATA_SOURCES and not r.get("provenance"):
            issues.append("real_data_source_without_provenance")

        if issues:
            status = "invalid"
        elif stale:
            status = "stale"
            issues.append(f"older than {float(max_age):.0f}s")
        elif r.get("quality") == "fault":
            status = "fault"
            issues.append("sensor_reported_fault")
        else:
            status = "valid"

        entries.append(
            {
                "reading_id": r.get("id"),
                "channel": channel,
                "status": status,
                "issues": issues,
                "simulated": r.get("source") == "simulated",
            }
        )

    summary = {s: sum(e["status"] == s for e in entries) for s in ("valid", "fault", "stale", "invalid")}
    summary["total"] = len(entries)
    return {"readings": entries, "summary": summary}


def usable_readings(readings: list[dict], report: dict) -> list[dict]:
    """The readings the pipelines may see: everything the gate did not reject."""
    usable = [e["status"] in USABLE_STATUSES for e in report["readings"]]
    return [r for r, ok in zip(readings, usable) if ok]
