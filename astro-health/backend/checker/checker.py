# SMALL TRUSTED CORE — requires two reviewers on every change (see CODEOWNERS)
"""The referee: takes all Proposals, applies gates, returns one Verdict.

Owner: person A and person B
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import yaml

from backend.checker.gates import (
    PIPELINE_NOT_RUNNING,
    PIPELINE_OK,
    TIER_ORDER,
    confirmed_fault_reading_ids,
    gate_data_fault,
    gate_data_requirements,
    gate_grey_escalation,
    gate_pipeline_availability,
    gate_whitelist,
    gate_worst_of,
)
from backend.common.schema_check import validate

# Semantic version of this checker module.
CHECKER_VERSION = "0.2.0"

# Absolute path to the verdict schema, resolved relative to this file's location.
_VERDICT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "schemas" / "verdict.schema.json"
)

# Fallback action when the tier is not found in policy.yaml::default_actions.
_FALLBACK_ACTION = "CONTACT_GROUND_URGENT"

UNVERIFIABLE = "GREY"

# Advisory pipelines: may raise the tier, can never lower it. Their data_fault
# claims must not be able to unlock a downgrade or suppress GREY escalation.
ADVISORY_PIPELINE_IDS = frozenset({"d_llm"})


def _hash_policy(policy_path: str) -> str:
    """Return the SHA-256 hex digest of the policy.yaml file bytes."""
    return hashlib.sha256(Path(policy_path).read_bytes()).hexdigest()


def load_policy(policy_path: str) -> tuple[dict, str]:
    """Read policy.yaml once; return (policy, SHA-256 of the exact bytes parsed)."""
    policy_bytes = Path(policy_path).read_bytes()
    policy = yaml.safe_load(policy_bytes)
    if not isinstance(policy, dict):
        raise ValueError(f"{policy_path} does not contain a policy mapping")
    return policy, hashlib.sha256(policy_bytes).hexdigest()


def _default_action(tier: str, policy: dict) -> str:
    """Return the canonical default action for *tier* from *policy*.

    Falls back to CONTACT_GROUND_URGENT when the tier is absent from
    policy["default_actions"], so an unknown tier is always treated as
    maximally urgent.
    """
    return policy.get("default_actions", {}).get(tier, _FALLBACK_ACTION)


Reevaluate = Callable[[list[dict]], list[dict]]


def _adjudicate_tier(
    proposals: list[dict],
    readings: list[dict],
    steps: list[dict] | None = None,
    tolerances: dict[str, float] | None = None,
    reevaluate: Reevaluate | None = None,
) -> str:
    """Gates 1-3 in order: worst_of -> data_fault -> grey_escalation."""

    def note(gate: str, before: str | None, after: str, detail: str) -> None:
        if steps is not None:
            steps.append(
                {
                    "gate": gate,
                    "tier_in": before,
                    "tier_out": after,
                    "changed": before is not None and before != after,
                    "detail": detail,
                }
            )

    tier = gate_worst_of(proposals)
    note("worst_of", None, tier, "most severe tier proposed by any pipeline")

    lowered = gate_data_fault(proposals, tier, readings=readings, reevaluate=reevaluate)
    note(
        "data_fault",
        tier,
        lowered,
        "every pipeline confirmed a data fault: those readings were dropped and the rest re-evaluated"
        if lowered != tier
        else "no confirmed data fault changed the tier",
    )
    tier = lowered

    escalated = gate_grey_escalation(readings, proposals, tier, tolerances=tolerances)
    note(
        "grey_escalation",
        tier,
        escalated,
        "a sensor-reported fault that no pipeline accounts for, or readings that contradict each other"
        if escalated != tier
        else "no unexplained sensor fault or contradiction",
    )
    return escalated


def _known_severity(
    proposals: list[dict],
    readings: list[dict] | None = None,
    reevaluate: Reevaluate | None = None,
) -> str | None:
    """Worst medical severity among proposals that could assess the data.

    GREY proposals say "I cannot tell", so they contribute nothing here. The
    result is never GREY; None means no pipeline produced a medical severity.
    """
    known = [p for p in proposals if p["tier"] != UNVERIFIABLE]
    if not known:
        return None
    return gate_data_fault(proposals, gate_worst_of(known), readings=readings, reevaluate=reevaluate)


def _disagreement_status(tier: str, proposals: list[dict], pipeline_status: dict | None) -> str:
    """How much the assessments behind this verdict agree. Informational only:
    it never changes the tier, and nothing here averages or votes."""
    if pipeline_status and any(
        s != PIPELINE_OK and s not in PIPELINE_NOT_RUNNING for s in pipeline_status.values()
    ):
        return "PARTIAL_ASSESSMENT"
    if tier == UNVERIFIABLE:
        return "UNVERIFIABLE"
    if len({p["tier"] for p in proposals}) > 1:
        return "DISAGREEMENT"
    return "AGREEMENT"


def _explain(tier: str, action: str, proposals: list[dict], unverifiable: list[str], known: str | None) -> str:
    """One plain-language paragraph the frontend can show as-is."""
    views = ", ".join(f"{p['pipeline_id']} proposed {p['tier']}" for p in proposals) or "no pipeline reported"
    if tier == UNVERIFIABLE:
        why = unverifiable[0] if unverifiable else "an assessment could not verify its inputs"
        text = f"GREY: the data cannot support a verified verdict ({why}). Assessments: {views}."
        if known and known != "GREEN":
            text += f" The worst severity that is still known is {known}."
    else:
        text = f"{tier}: the most severe proposal sets the verdict. Assessments: {views}."
    return f"{text} Authorized action: {action}."


def check(
    proposals: list[dict],
    readings: list[dict],
    policy_path: str,
    integrity: dict | None = None,
    pipeline_status: dict[str, str] | None = None,
    *,
    reevaluate: Reevaluate | None = None,
) -> dict:
    """Apply gates in order and return a schema-validated Verdict.

    Gate order:
      1. gate_worst_of(proposals)        → tier
      2. gate_data_fault(proposals, tier) → tier (a fault every pipeline confirms
         drops those readings and re-evaluates on the rest; never a blind step down)
      3. gate_grey_escalation(readings, proposals, tier) → tier (may raise to GREY)
         (then the advisory floor: never below the tier the non-LLM pipelines
         reach on their own)
      4. gate_data_requirements(integrity, policy)        → GREY when not met
      5. gate_pipeline_availability(pipeline_status, ...) → GREY when a required pipeline is absent
      6. _default_action(tier)            → action
      7. gate_whitelist(action, policy_actions) → action

    GREY is not a point on the medical severity scale: it says the evidence
    cannot be verified. A GREY verdict therefore also reports ``known_severity``
    (the worst severity the usable evidence still shows) and, when that calls
    for a different action, lists it in ``additional_actions`` so that an
    unverifiable input can never hide a known medical alert.

    Parameters
    ----------
    proposals:
        Non-empty list of Proposal dicts from all active pipelines.
    readings:
        The readings the pipelines saw (used by the grey-escalation gate).
    policy_path:
        Path to policy.yaml.  Its bytes are hashed and stored in the Verdict.
    integrity:
        Report from input_gate.evaluate(). When omitted, gate 4 is skipped.
    pipeline_status:
        ``{pipeline_id: status}`` from the orchestrator. When omitted, gate 5
        is skipped.
    reevaluate:
        ``reevaluate(remaining_readings) -> proposals``: re-runs the pipelines
        on what is left after confirmed-fault readings are dropped.

    Returns
    -------
    dict
        A Verdict dict validated against verdict.schema.json.

    Raises
    ------
    ValueError
        If the produced Verdict fails schema validation.
    FileNotFoundError
        If *policy_path* does not exist.
    """
    # --- Load policy and compute the ruleset hash over the bytes parsed --------
    policy, ruleset_hash = load_policy(policy_path)
    policy_actions: list[str] = policy.get("actions", [])
    action_order: list[str] | None = policy.get("action_order")
    tolerances: dict[str, float] | None = policy.get("contradiction_tolerances")

    # --- Gates 1-3 -----------------------------------------------------------
    steps: list[dict] = []
    tier = _adjudicate_tier(proposals, readings, steps, tolerances=tolerances, reevaluate=reevaluate)

    # Advisory floor: the verdict is never lower than what the non-advisory
    # pipelines produce on their own, so an advisory (LLM) proposal can raise
    # the tier but can never lower it, whatever it claims about data faults.
    core = [p for p in proposals if p.get("pipeline_id") not in ADVISORY_PIPELINE_IDS]
    known = _known_severity(proposals, readings, reevaluate)
    if core and len(core) != len(proposals):
        core_tier = _adjudicate_tier(core, readings, tolerances=tolerances, reevaluate=reevaluate)
        floored = core_tier if TIER_ORDER[core_tier] > TIER_ORDER[tier] else tier
        steps.append(
            {
                "gate": "advisory_floor",
                "tier_in": tier,
                "tier_out": floored,
                "changed": floored != tier,
                "detail": "an advisory pipeline may raise the tier, never lower it",
            }
        )
        tier = floored
        core_known = _known_severity(core, readings, reevaluate)
        if core_known is not None and (known is None or TIER_ORDER[core_known] > TIER_ORDER[known]):
            known = core_known

    # --- Gate 4: data requirements ---------------------------------------------
    unverifiable: list[str] = []
    data_reasons: list[str] = []
    if integrity is not None:
        # Fault correction is not medical recovery: a reading dropped as a
        # confirmed fault no longer counts as evidence. If too little is left,
        # the data requirements below fail and the verdict is GREY, not GREEN.
        dropped = confirmed_fault_reading_ids(proposals, readings)
        if dropped:
            integrity = {
                **integrity,
                "readings": [
                    {**e, "status": "confirmed_fault", "issues": [*e["issues"], "confirmed_data_fault"]}
                    if e["reading_id"] in dropped and e["status"] in ("valid", "fault")
                    else e
                    for e in integrity["readings"]
                ],
            }
        found = data_reasons = gate_data_requirements(integrity, policy.get("data_requirements") or {})
        unverifiable += found
        steps.append(
            {
                "gate": "data_requirements",
                "tier_in": tier,
                "tier_out": UNVERIFIABLE if found else tier,
                "changed": bool(found) and tier != UNVERIFIABLE,
                "detail": "; ".join(found) or "data requirements met",
            }
        )
        if found:
            tier = UNVERIFIABLE

    # --- Gate 5: pipeline availability -----------------------------------------
    if pipeline_status is not None:
        found = gate_pipeline_availability(pipeline_status, (policy.get("pipelines") or {}).get("required") or [])
        unverifiable += found
        steps.append(
            {
                "gate": "pipeline_availability",
                "tier_in": tier,
                "tier_out": UNVERIFIABLE if found else tier,
                "changed": bool(found) and tier != UNVERIFIABLE,
                "detail": "; ".join(found) or "every required pipeline reported",
            }
        )
        if found:
            tier = UNVERIFIABLE

    # --- Gates 6-7: the one authorized action ----------------------------------
    action = gate_whitelist(_default_action(tier, policy), policy_actions, action_order=action_order)

    # What is known must not be lost because something else is unknown.
    additional_actions: list[str] = []
    if tier == UNVERIFIABLE and known is not None:
        known_action = gate_whitelist(_default_action(known, policy), policy_actions, action_order=action_order)
        mildest = (policy.get("severity_order") or ["GREEN"])[0]
        if known != mildest and known_action != action:
            additional_actions.append(known_action)

    # --- Collect reasons ---------------------------------------------------------
    reasons: list[str] = list(unverifiable)
    for p in proposals:
        reasons.extend(p.get("reasons", []))

    overruled = sorted(
        {p["pipeline_id"] for p in proposals if TIER_ORDER[p["tier"]] < TIER_ORDER[tier]}
    )
    status = _disagreement_status(tier, proposals, pipeline_status)

    summary = (integrity or {}).get("summary")
    if summary is None:
        data_quality = {"status": "not_assessed"}
    else:
        unusable = summary["stale"] + summary["invalid"]
        data_quality = {
            "status": "insufficient" if data_reasons else ("degraded" if unusable or summary["fault"] else "ok"),
            **summary,
            "issues": [
                {"reading_id": e["reading_id"], "channel": e["channel"], "status": e["status"], "issues": e["issues"]}
                for e in integrity["readings"]
                if e["status"] != "valid"
            ],
        }

    # --- Build Verdict -------------------------------------------------------
    verdict: dict = {
        "tier": tier,
        "action": action,
        "reasons": reasons,
        "overruled_pipelines": overruled,
        "disagreement_status": status,
        "checker_version": CHECKER_VERSION,
        "ruleset_hash": ruleset_hash,
        "decision_trace": {
            "final_tier": tier,
            "action_authorized": action,
            "additional_actions": additional_actions,
            "known_severity": known,
            "disagreement_status": status,
            "contributing_proposals": [
                {
                    "pipeline_id": p["pipeline_id"],
                    "tier": p["tier"],
                    "data_fault": p["data_fault"],
                    "rule_ids": list(p.get("rule_ids") or []),
                    "advisory": p["pipeline_id"] in ADVISORY_PIPELINE_IDS,
                }
                for p in proposals
            ],
            "triggered_rules": sorted({rule for p in proposals for rule in (p.get("rule_ids") or [])}),
            "pipeline_status": dict(pipeline_status or {}),
            "data_quality": data_quality,
            "gates": steps,
            "policy_hash": ruleset_hash,
            "explanation": _explain(tier, action, proposals, unverifiable, known),
        },
    }
    if known is not None:
        verdict["known_severity"] = known
    if additional_actions:
        verdict["additional_actions"] = additional_actions

    # --- Validate against schema before returning ---------------------------
    validate(verdict, str(_VERDICT_SCHEMA_PATH))

    return verdict
