"""Re-run the decision for a record with the same inputs and rule versions; report divergence.

Owner: person B
"""

from __future__ import annotations

from datetime import datetime

from backend.orchestrator import decide


def replay(record: dict, baselines: dict, rules: dict, signing_key: str | None = None) -> dict:
    """Re-run decide() on a stored Record's own inputs under *rules*.

    Because decide() is pure, unchanged rules and baselines reproduce *record*
    exactly, hash and signature included. Any difference is a real divergence.
    """
    return decide(
        readings=record["readings"],
        baselines=baselines,
        rules=rules,
        now=datetime.fromisoformat(record["ts"].replace("Z", "+00:00")),
        prev_hash=record["prev_hash"],
        astronaut_id=record["astronaut_id"],
        signing_key=signing_key,
    )


def divergence(original: dict, replayed: dict) -> dict:
    """Describe how a replayed Record differs from the original.

    ``identical``: same hash, so the same Record.
    ``decision_changed``: tier or action differs.
    """
    old, new = original.get("verdict", {}), replayed.get("verdict", {})
    return {
        "record_id": original.get("id"),
        "identical": original.get("hash") == replayed.get("hash"),
        "decision_changed": (old.get("tier"), old.get("action")) != (new.get("tier"), new.get("action")),
        "old_tier": old.get("tier"),
        "new_tier": new.get("tier"),
        "old_action": old.get("action"),
        "new_action": new.get("action"),
        "rules_changed": original.get("versions", {}).get("rules") != replayed.get("versions", {}).get("rules"),
    }
