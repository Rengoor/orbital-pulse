"""Decision card builder: provenance (dataset ID, analyte or module, timestamp) and real/simulated labels.

A card is the small, display-ready view of one Record: what tier, what to do,
which real datasets it rests on, and which inputs were simulated.

``build_trust_summary`` is the data behind the "Why should I trust this
decision?" panel. Both views only repeat what the Checker decided and
recorded; neither interprets anything, so the frontend cannot drift from the
governance logic.

Owner: person B
"""

from __future__ import annotations

from pathlib import Path

from backend.common.schema_check import validate

_CARD_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "schemas" / "card.schema.json"

_TIER_HEADLINES = {
    "GREEN": "All signals nominal",
    "YELLOW": "Drift or borderline reading",
    "RED": "Needs the crew medical officer",
    "GREY": "Data cannot be verified",
}

_STATUS_TEXT = {
    "AGREEMENT": "All assessments agree.",
    "DISAGREEMENT": "The assessments did not agree; the most cautious one decided.",
    "PARTIAL_ASSESSMENT": "Not every assessment could run.",
    "UNVERIFIABLE": "The data could not be verified.",
}


def build_card(record: dict) -> dict:
    """Return a schema-valid Card for *record*."""
    verdict = record["verdict"]
    tier = verdict["tier"]

    headline = _TIER_HEADLINES.get(tier, tier)
    reasons = verdict.get("reasons") or []
    if reasons and tier != "GREEN":
        headline = f"{headline}: {reasons[0]}"

    provenance: list[dict] = []
    for item in record.get("provenance") or []:
        if item not in provenance:
            provenance.append(item)

    # Say plainly which inputs were simulated, channel by channel.
    simulated_labels = sorted(
        {f"{r['channel']}: simulated" for r in record.get("readings", []) if r.get("source") == "simulated"}
    )

    card = {
        "record_id": record["id"],
        "astronaut_id": record["astronaut_id"],
        "ts": record["ts"],
        "tier": tier,
        "headline": headline,
        "action": verdict["action"],
        "provenance": provenance,
        "simulated_labels": simulated_labels,
    }
    for optional in ("disagreement_status", "known_severity", "additional_actions"):
        if verdict.get(optional):
            card[optional] = verdict[optional]
    explanation = (verdict.get("decision_trace") or {}).get("explanation")
    if explanation:
        card["explanation"] = explanation

    validate(card, str(_CARD_SCHEMA_PATH))
    return card


def build_trust_summary(record: dict, chain_valid: bool, reviews: list[dict]) -> dict:
    """Plain answers to "why should I trust this decision?" for one Record.

    No hashes or YAML here: those are for the Earth console. Each entry is a
    short statement plus the facts behind it.
    """
    verdict = record["verdict"]
    trace = verdict.get("decision_trace") or {}
    manifest = record.get("execution_manifest") or {}
    quality = trace.get("data_quality") or {}
    statuses = trace.get("pipeline_status") or {}
    status = verdict.get("disagreement_status")

    assessments = [
        {"pipeline_id": p["pipeline_id"], "tier": p["tier"], "advisory": p.get("advisory", False)}
        for p in trace.get("contributing_proposals") or []
    ]
    not_run = sorted(pid for pid, s in statuses.items() if s not in ("ok", "disabled"))
    signing = manifest.get("signing") or {}

    return {
        "record_id": record["id"],
        "tier": verdict["tier"],
        "action": verdict["action"],
        "additional_actions": verdict.get("additional_actions", []),
        "known_severity": verdict.get("known_severity"),
        "failsafe": bool(verdict.get("failsafe")),
        "explanation": trace.get("explanation"),
        "assessments": {
            "contributed": assessments,
            "did_not_run": not_run,
            "status": status,
            "summary": _STATUS_TEXT.get(status, "Agreement between assessments is unknown."),
        },
        "data": {
            "status": quality.get("status", "not_assessed"),
            "usable": quality.get("valid"),
            "total": quality.get("total"),
            "problems": quality.get("issues", []),
            "simulated_inputs": sorted(
                {r["channel"] for r in record.get("readings", []) if r.get("source") == "simulated"}
            ),
        },
        "rules": {
            "triggered": trace.get("triggered_rules", []),
            "steps": [g for g in trace.get("gates", []) if g.get("changed")],
            "limits_are_official": False if any(
                "project-defined" in reason for reason in verdict.get("reasons", [])
            ) else None,
        },
        "record": {
            "recorded": True,
            "chain_intact": chain_valid,
            "signed_with_demo_key": signing.get("demo_key"),
        },
        "human_review": {
            "status": "reviewed" if reviews else "pending",
            "outcomes": [r["outcome"] for r in reviews],
            "simulated": True,
        },
    }
