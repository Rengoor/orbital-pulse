# SMALL TRUSTED CORE — requires two reviewers on every change (see CODEOWNERS)
"""The referee: takes all Proposals, applies gates, returns one Verdict.

Owner: person A and person B
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from backend.checker.gates import (
    TIER_ORDER,
    gate_data_fault,
    gate_grey_escalation,
    gate_whitelist,
    gate_worst_of,
)
from backend.common.schema_check import validate

# Semantic version of this checker module.
CHECKER_VERSION = "0.1.0"

# Absolute path to the verdict schema, resolved relative to this file's location.
_VERDICT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "schemas" / "verdict.schema.json"
)

# Fallback action when the tier is not found in policy.yaml::default_actions.
_FALLBACK_ACTION = "CONTACT_GROUND_URGENT"

# Advisory pipelines: may raise the tier, can never lower it. Their data_fault
# claims must not be able to unlock a downgrade or suppress GREY escalation.
ADVISORY_PIPELINE_IDS = frozenset({"d_llm"})


def _adjudicate_tier(proposals: list[dict], readings: list[dict]) -> str:
    """Gates 1-3 in order: worst_of -> data_fault -> grey_escalation."""
    tier = gate_worst_of(proposals)
    tier = gate_data_fault(proposals, tier)
    return gate_grey_escalation(readings, proposals, tier)


def _hash_policy(policy_path: str) -> str:
    """Return the SHA-256 hex digest of the policy.yaml file bytes."""
    return hashlib.sha256(Path(policy_path).read_bytes()).hexdigest()


def _default_action(tier: str, policy: dict) -> str:
    """Return the canonical default action for *tier* from *policy*.

    Falls back to CONTACT_GROUND_URGENT when the tier is absent from
    policy["default_actions"], so an unknown tier is always treated as
    maximally urgent.
    """
    return policy.get("default_actions", {}).get(tier, _FALLBACK_ACTION)


def check(
    proposals: list[dict],
    readings: list[dict],
    policy_path: str,
) -> dict:
    """Apply gates in order and return a schema-validated Verdict.

    Gate order:
      1. gate_worst_of(proposals)        → tier
      2. gate_data_fault(proposals, tier) → tier (may lower by one step)
      3. gate_grey_escalation(readings, proposals, tier) → tier (may raise to GREY)
         (then the advisory floor: never below the tier the non-LLM pipelines
         reach on their own)
      4. _default_action(tier)            → action
      5. gate_whitelist(action, policy_actions) → action

    Parameters
    ----------
    proposals:
        Non-empty list of Proposal dicts from all active pipelines.
    readings:
        Original readings for the check window (used by grey-escalation gate).
    policy_path:
        Path to policy.yaml.  Its bytes are hashed and stored in the Verdict.

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
    # --- Load policy --------------------------------------------------------
    policy_text = Path(policy_path).read_bytes()
    policy: dict = yaml.safe_load(policy_text)

    policy_actions: list[str] = policy.get("actions", [])

    # --- Compute ruleset hash -----------------------------------------------
    # Same digest as _hash_policy(policy_path), taken over the exact bytes that
    # were parsed above so the hash can never describe a different file state.
    ruleset_hash = hashlib.sha256(policy_text).hexdigest()

    # --- Apply gates in order -----------------------------------------------
    # Gates 1-3: worst-of tier, data-fault downgrade, GREY escalation.
    tier = _adjudicate_tier(proposals, readings)

    # Advisory floor: the verdict is never lower than what the non-advisory
    # pipelines produce on their own, so an advisory (LLM) proposal can raise
    # the tier but can never lower it, whatever it claims about data faults.
    core = [p for p in proposals if p.get("pipeline_id") not in ADVISORY_PIPELINE_IDS]
    if core and len(core) != len(proposals):
        core_tier = _adjudicate_tier(core, readings)
        if TIER_ORDER[core_tier] > TIER_ORDER[tier]:
            tier = core_tier

    # Gate 4: Default action for the resulting tier
    action = _default_action(tier, policy)

    # Gate 5: Whitelist enforcement
    action = gate_whitelist(action, policy_actions)

    # --- Collect reasons from all proposals ---------------------------------
    reasons: list[str] = []
    for p in proposals:
        reasons.extend(p.get("reasons", []))

    # --- Build Verdict -------------------------------------------------------
    verdict: dict = {
        "tier": tier,
        "action": action,
        "reasons": reasons,
        "overruled_pipelines": sorted(
            {
                p["pipeline_id"]
                for p in proposals
                if TIER_ORDER[p["tier"]] < TIER_ORDER[tier]
            }
        ),
        "checker_version": CHECKER_VERSION,
        "ruleset_hash": ruleset_hash,
    }

    # --- Validate against schema before returning ---------------------------
    validate(verdict, str(_VERDICT_SCHEMA_PATH))

    return verdict
