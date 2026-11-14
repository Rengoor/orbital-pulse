"""Gates: worst-of severity, data-fault confirmation, whitelisted actions, unverifiable input -> GREY/escalate.

Owner: person A and person B
"""

from __future__ import annotations

# Tier ordering: lower number = less severe
TIER_ORDER: dict[str, int] = {
    "GREEN": 0,
    "YELLOW": 1,
    "RED": 2,
    "GREY": 3,
}

# One-step downgrade map (Gate 2)
_TIER_DOWN: dict[str, str] = {
    "GREY": "RED",
    "RED": "YELLOW",
    "YELLOW": "GREEN",
}

# Canonical severity order for actions (Gate 4)
SEVERITY_ORDER: list[str] = [
    "NO_ACTION",
    "RECHECK_IN_1H",
    "REST_AND_HYDRATE",
    "USE_PROTOCOL_CARD",
    "ALERT_CMO",
    "CONTACT_GROUND_URGENT",
]


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


def gate_data_fault(proposals: list[dict], current_tier: str) -> str:
    """Return potentially lowered tier when ALL proposals flag data_fault=True.

    Lowers by exactly one step (GREY→RED, RED→YELLOW, YELLOW→GREEN).
    Never lowers GREEN. Never goes below GREEN.
    Pure — does not mutate *proposals*.
    """
    if current_tier == "GREEN":
        return current_tier

    if proposals and all(p.get("data_fault") is True for p in proposals):
        return _TIER_DOWN[current_tier]

    return current_tier


def gate_whitelist(action: str, policy_actions: list[str]) -> str:
    """Return *action* if it is on the whitelist, otherwise escalate.

    Escalation: find the next-higher action in SEVERITY_ORDER that is also
    present in *policy_actions*. If none is found, fall back to the last
    element of *policy_actions*, or CONTACT_GROUND_URGENT when the list is
    empty.

    Pure — does not mutate inputs.
    """
    if action in policy_actions:
        return action

    # Find next-higher whitelisted action
    try:
        idx = SEVERITY_ORDER.index(action)
    except ValueError:
        # Unknown action — return most severe available
        return policy_actions[-1] if policy_actions else "CONTACT_GROUND_URGENT"

    for higher in SEVERITY_ORDER[idx + 1:]:
        if higher in policy_actions:
            return higher

    # Fallback
    return policy_actions[-1] if policy_actions else "CONTACT_GROUND_URGENT"


def gate_grey_escalation(
    readings: list[dict],
    proposals: list[dict],
    current_tier: str,
) -> str:
    """Return GREY when any reading has quality='fault' and no proposal claims
    that reading's id as a known data fault.

    A reading is *verified* as a data fault when at least one proposal has
    data_fault=True and lists the reading's id in its reading_ids.
    If any fault reading is *unverified*, and the current tier is not already
    GREY, escalate to GREY.

    Pure — does not mutate inputs.
    """
    fault_reading_ids: set[str] = {
        r["id"] for r in readings if r.get("quality") == "fault"
    }

    if not fault_reading_ids:
        return current_tier

    # Collect reading_ids that pipelines have explicitly flagged as data faults
    pipeline_fault_reading_ids: set[str] = set()
    for p in proposals:
        if p.get("data_fault") is True:
            pipeline_fault_reading_ids.update(p.get("reading_ids") or [])

    unverified_faults = fault_reading_ids - pipeline_fault_reading_ids

    if unverified_faults and TIER_ORDER[current_tier] < TIER_ORDER["GREY"]:
        return "GREY"

    return current_tier
