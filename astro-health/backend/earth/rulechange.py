"""Time machine: apply a proposed rule change to past records; report changed decisions and new unsafe approvals.

Owner: person B
"""

from __future__ import annotations

from backend.earth.replay import replay

_TIER_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2, "GREY": 3}


def rulechange(records: list[dict], baselines: dict, proposed_rules: dict) -> dict:
    """Replay *records* (oldest first) under *proposed_rules* and diff the decisions.

    A row is ``changed`` when tier or action differs, and ``unsafe`` when the
    proposed rules would have given a less severe tier than the decision that
    was actually taken. Unsafe rows are the ones a reviewer must read before a
    rule change is accepted. Nothing is stored and no past Record is altered.
    """
    rows = []
    for record in records:
        old = record["verdict"]
        new = replay(record, baselines, proposed_rules)["verdict"]
        rows.append(
            {
                "record_id": record["id"],
                "astronaut_id": record["astronaut_id"],
                "ts": record["ts"],
                "old_tier": old["tier"],
                "new_tier": new["tier"],
                "old_action": old["action"],
                "new_action": new["action"],
                "changed": (old["tier"], old["action"]) != (new["tier"], new["action"]),
                "unsafe": _TIER_ORDER[new["tier"]] < _TIER_ORDER[old["tier"]],
            }
        )
    return {
        "total": len(rows),
        "changed": sum(r["changed"] for r in rows),
        "unsafe": sum(r["unsafe"] for r in rows),
        "rows": rows,
    }
