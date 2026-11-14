"""Decision card builder: provenance (dataset ID, analyte or module, timestamp) and real/simulated labels.

A card is the small, display-ready view of one Record: what tier, what to do,
which real datasets it rests on, and which inputs were simulated.

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
    validate(card, str(_CARD_SCHEMA_PATH))
    return card
