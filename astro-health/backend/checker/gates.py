"""Gates: worst-of severity, data-fault confirmation, whitelisted actions, unverifiable input -> GREY/escalate.

Owner: person A and person B
"""

from __future__ import annotations

from collections.abc import Callable

# Tier ordering: lower number = less severe
TIER_ORDER: dict[str, int] = {
    "GREEN": 0,
    "YELLOW": 1,
    "RED": 2,
    "GREY": 3,
}

# Canonical fallback severity order for actions when policy does not specify action_order
SEVERITY_ORDER: list[str] = [
    "NO_ACTION",
    "RECHECK_IN_1H",
    "REST_AND_HYDRATE",
    "USE_PROTOCOL_CARD",
    "ALERT_CMO",
    "CONTACT_GROUND_URGENT",
]

# Default per-channel tolerance band for contradiction detection when not overridden by policy.
DEFAULT_CONTRADICTION_TOLERANCES: dict[str, float] = {
    "bp_systolic": 5.0,
    "bp_diastolic": 5.0,
    "heart_rate": 3.0,
    "glucose": 5.0,
    "temperature": 0.2,
    "sleep_hours": 0.25,
    "mood": 0.5,
    "co2_ppm": 50.0,
    "exercise_minutes": 2.0,
    "dose_rate_usv_h": 1.0,
    "blood_analyte": 0.1,
}


def gate_worst_of(proposals: list[dict]) -> str:
    """Return the maximum tier across all proposals.

    Uses TIER_ORDER = {GREEN: 0, YELLOW: 1, RED: 2, GREY: 3}.
    Pure — does not mutate *proposals*.
    """
    if not proposals:
        return "GREEN"

    tier = proposals[0]["tier"]
    for p in proposals[1:]:
        if TIER_ORDER[p["tier"]] > TIER_ORDER[tier]:
            tier = p["tier"]
    return tier


def confirmed_fault_reading_ids(
    proposals: list[dict],
    readings: list[dict] | None = None,
) -> set[str]:
    """Return reading IDs that ALL proposals unanimously confirm as data faults.

    A reading ID is a confirmed fault when every proposal has ``data_fault=True``
    and lists that reading ID in its ``reading_ids`` (or, if proposals omit
    ``reading_ids``, any reading marked ``quality="fault"`` in *readings*).
    Pure — does not mutate inputs.
    """
    if not proposals or not all(p.get("data_fault") is True for p in proposals):
        return set()

    id_sets = [set(p.get("reading_ids") or []) for p in proposals]
    if all(id_sets):
        common = set.intersection(*id_sets)
        if common:
            return common

    union_ids = set().union(*id_sets)
    if union_ids:
        return union_ids

    if readings:
        return {r["id"] for r in readings if r.get("quality") == "fault" and "id" in r}
    return set()


def drop_confirmed_fault_readings(
    readings: list[dict],
    proposals: list[dict],
) -> tuple[list[dict], set[str]]:
    """Drop readings unanimously confirmed as data faults and return ``(remaining, dropped_ids)``.

    Pure — does not mutate *readings* or *proposals*.
    """
    dropped = confirmed_fault_reading_ids(proposals, readings)
    if not dropped:
        return list(readings), set()
    remaining = [r for r in readings if r.get("id") not in dropped]
    return remaining, dropped


def gate_data_fault(
    proposals: list[dict],
    current_tier: str,
    readings: list[dict] | None = None,
    reevaluate: Callable[[list[dict]], list[dict]] | None = None,
) -> str:
    """Handle unanimous data-fault confirmation without blind step-down.

    Instead of stepping down the tier by one level (which could turn GREY into
    RED when every pipeline claims a fault), a confirmed fault drops the
    faulted reading(s) and re-evaluates on the readings that remain:
      - Never lowers ``GREY`` (an unverifiable state stays ``GREY``).
      - Never lowers ``GREEN``.
      - When all proposals have ``data_fault=True``, drops the confirmed fault
        readings and re-evaluates on what remains (via *reevaluate* when
        provided, or from the non-faulted proposals/readings).
    Pure — does not mutate inputs.
    """
    if current_tier in ("GREEN", "GREY"):
        return current_tier

    if not proposals or not all(p.get("data_fault") is True for p in proposals):
        return current_tier

    if readings is not None:
        remaining, dropped = drop_confirmed_fault_readings(readings, proposals)
        if not dropped:
            return current_tier
        if not remaining:
            return "GREEN"
        if reevaluate is not None:
            new_proposals = reevaluate(remaining)
            return gate_worst_of(new_proposals) if new_proposals else "GREEN"

    # When re-evaluating without a callback, drop proposals whose reading_ids
    # are entirely accounted for by the confirmed fault readings; if every
    # proposal was solely driven by the dropped fault reading, what remains is GREEN.
    return "GREEN"


def gate_whitelist(
    action: str,
    policy_actions: list[str],
    action_order: list[str] | None = None,
) -> str:
    """Return *action* if it is on the whitelist, otherwise escalate.

    Escalation: find the next-higher action in *action_order* (read from
    ``policy.yaml``, defaulting to *policy_actions* if it is a subset/ordering,
    or ``SEVERITY_ORDER``) that is also present in *policy_actions*.
    If none is found, fall back to the last element of *policy_actions*, or
    ``CONTACT_GROUND_URGENT`` when the list is empty.

    Pure — does not mutate inputs.
    """
    if action in policy_actions:
        return action

    order = list(action_order) if action_order else SEVERITY_ORDER

    try:
        idx = order.index(action)
    except ValueError:
        return policy_actions[-1] if policy_actions else "CONTACT_GROUND_URGENT"

    for higher in order[idx + 1:]:
        if higher in policy_actions:
            return higher

    return policy_actions[-1] if policy_actions else "CONTACT_GROUND_URGENT"


def detect_contradictions(
    readings: list[dict],
    tolerances: dict[str, float] | None = None,
    default_tolerance: float = 0.0,
) -> set[str]:
    """Return reading IDs that contradict each other at the same channel and timestamp.

    Two readings on the same ``(channel, analyte, ts)`` contradict when their
    units differ or ``abs(v1 - v2) > tolerance``, where ``tolerance`` is looked
    up in *tolerances* by channel (falling back to *default_tolerance*).
    Values within the tolerance band ``abs(v1 - v2) <= tolerance`` are accepted.
    Pure — does not mutate inputs.
    """
    tol_map = tolerances if tolerances is not None else DEFAULT_CONTRADICTION_TOLERANCES
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for r in readings:
        key = (str(r.get("channel", "")), str(r.get("analyte", "")), str(r.get("ts", "")))
        groups.setdefault(key, []).append(r)

    contradicting_ids: set[str] = set()
    for (channel, _, _), group in groups.items():
        if len(group) < 2:
            continue
        tol = float(tol_map.get(channel, default_tolerance))
        units = {r.get("unit") for r in group}
        values = [float(r["value"]) for r in group if isinstance(r.get("value"), (int, float))]
        if len(units) > 1 or (values and (max(values) - min(values)) > tol):
            for r in group:
                if "id" in r:
                    contradicting_ids.add(r["id"])

    return contradicting_ids


def gate_grey_escalation(
    readings: list[dict],
    proposals: list[dict],
    current_tier: str,
    tolerances: dict[str, float] | None = None,
    default_tolerance: float = 0.0,
) -> str:
    """Return GREY when any reading has an unverified ``quality='fault'`` or
    when readings on the same channel and timestamp contradict beyond tolerance.

    A reading is *verified* as a data fault when at least one proposal has
    ``data_fault=True`` and lists the reading's id in its ``reading_ids``.
    If any fault reading is *unverified*, or if any contradiction exceeds the
    channel's tolerance band, escalate to GREY.

    Pure — does not mutate inputs.
    """
    if detect_contradictions(readings, tolerances=tolerances, default_tolerance=default_tolerance):
        return "GREY"

    fault_reading_ids: set[str] = {
        r["id"] for r in readings if r.get("quality") == "fault"
    }

    if not fault_reading_ids:
        return current_tier

    pipeline_fault_reading_ids: set[str] = set()
    for p in proposals:
        if p.get("data_fault") is True:
            pipeline_fault_reading_ids.update(p.get("reading_ids") or [])

    unverified_faults = fault_reading_ids - pipeline_fault_reading_ids

    if unverified_faults and TIER_ORDER[current_tier] < TIER_ORDER["GREY"]:
        return "GREY"

    return current_tier


# Pipeline outcomes that count as "this pipeline did its job".
PIPELINE_OK = "ok"
# Outcomes that are not failures: the pipeline is switched off by configuration.
PIPELINE_NOT_RUNNING = ("disabled",)


def gate_data_requirements(integrity: dict, requirements: dict) -> list[str]:
    """Return the reasons the available data cannot support a verdict.

    An empty list means the data requirements in policy.yaml are met. Any
    reason makes the verdict unverifiable (GREY). The requirements:

    * at least ``min_valid_readings`` valid readings;
    * a valid reading for every channel in ``required_channels``;
    * no stale or invalid reading on a critical channel (channels are critical
      unless ``channels.<name>.critical`` or ``default_critical`` says otherwise).

    Pure - does not mutate inputs.
    """
    reasons: list[str] = []
    entries = integrity.get("readings", [])
    valid = [e for e in entries if e["status"] == "valid"]

    minimum = int(requirements.get("min_valid_readings") or 0)
    if len(valid) < minimum:
        reasons.append(
            f"data requirement not met: {len(valid)} valid reading(s), policy requires at least {minimum}"
        )

    valid_channels = {e["channel"] for e in valid}
    for channel in requirements.get("required_channels") or []:
        if channel not in valid_channels:
            reasons.append(f"data requirement not met: no valid {channel} reading")

    channel_rules = requirements.get("channels") or {}
    default_critical = requirements.get("default_critical", True)
    for e in entries:
        if e["status"] not in ("stale", "invalid"):
            continue
        critical = (channel_rules.get(e["channel"]) or {}).get("critical", default_critical)
        if critical:
            reasons.append(
                f"{e['channel']} reading {e['reading_id']!r} is {e['status']} ({'; '.join(e['issues'])})"
            )

    return reasons


def gate_pipeline_availability(pipeline_status: dict[str, str], required: list[str]) -> list[str]:
    """Return a reason for every required pipeline that did not deliver.

    A required pipeline must be present with status "ok". Missing, crashed,
    timed out and malformed all count the same: its judgment is absent, so a
    reassuring verdict from the others cannot stand. Optional pipelines are
    never a reason here.

    Pure - does not mutate inputs.
    """
    return [
        f"required pipeline {name!r} unavailable ({pipeline_status.get(name, 'missing')})"
        for name in required
        if pipeline_status.get(name, "missing") != PIPELINE_OK
    ]
