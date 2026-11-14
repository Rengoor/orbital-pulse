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
    TIER_ORDER,
    gate_data_fault,
    gate_grey_escalation,
    gate_whitelist,
    gate_worst_of,
)
from backend.common.schema_check import validate

CHECKER_VERSION = "0.1.0"
_VERDICT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "schemas" / "verdict.schema.json"
)
_FALLBACK_ACTION = "CONTACT_GROUND_URGENT"
ADVISORY_PIPELINE_IDS = frozenset({"d_llm"})


def _adjudicate_tier(
    proposals: list[dict],
    readings: list[dict],
    tolerances: dict[str, float] | None = None,
    reevaluate: Callable[[list[dict]], list[dict]] | None = None,
) -> str:
    """Gates 1-3 in order: worst_of -> data_fault -> grey_escalation."""
    tier = gate_worst_of(proposals)
    tier = gate_data_fault(proposals, tier, readings=readings, reevaluate=reevaluate)
    return gate_grey_escalation(readings, proposals, tier, tolerances=tolerances)


def _hash_policy(policy_path: str) -> str:
    """Return the SHA-256 hex digest of the policy.yaml file bytes."""
    return hashlib.sha256(Path(policy_path).read_bytes()).hexdigest()


def _default_action(tier: str, policy: dict) -> str:
    """Return the canonical default action for *tier* from *policy*."""
    return policy.get("default_actions", {}).get(tier, _FALLBACK_ACTION)


def check(
    proposals: list[dict],
    readings: list[dict],
    policy_path: str,
    *,
    reevaluate: Callable[[list[dict]], list[dict]] | None = None,
) -> dict:
    """Apply gates in order and return a schema-validated Verdict."""
    policy_text = Path(policy_path).read_bytes()
    policy: dict = yaml.safe_load(policy_text) or {}
    policy_actions: list[str] = policy.get("actions", [])
    action_order: list[str] | None = policy.get("action_order")
    tolerances: dict[str, float] | None = policy.get("contradiction_tolerances")
    ruleset_hash = hashlib.sha256(policy_text).hexdigest()

    tier = _adjudicate_tier(proposals, readings, tolerances=tolerances, reevaluate=reevaluate)

    core = [p for p in proposals if p.get("pipeline_id") not in ADVISORY_PIPELINE_IDS]
    if core and len(core) != len(proposals):
        core_tier = _adjudicate_tier(core, readings, tolerances=tolerances, reevaluate=reevaluate)
        if TIER_ORDER[core_tier] > TIER_ORDER[tier]:
            tier = core_tier

    action = gate_whitelist(_default_action(tier, policy), policy_actions, action_order=action_order)
    reasons = [reason for p in proposals for reason in p.get("reasons", [])]

    verdict: dict = {
        "tier": tier,
        "action": action,
        "reasons": reasons,
        "overruled_pipelines": sorted(
            {p["pipeline_id"] for p in proposals if TIER_ORDER[p["tier"]] < TIER_ORDER[tier]}
        ),
        "checker_version": CHECKER_VERSION,
        "ruleset_hash": ruleset_hash,
    }
    validate(verdict, str(_VERDICT_SCHEMA_PATH))
    return verdict
