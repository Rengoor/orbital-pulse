"""Re-run the decision for a record with the same inputs and rule versions; report divergence.

Owner: person B
"""

from __future__ import annotations

from datetime import datetime

from backend.orchestrator import decide


def replay(record: dict, baselines: dict, rules: dict, signing_key: str | None = None) -> dict:
    """Re-run decide() on a stored Record's own inputs under *rules*.

    Because decide() is pure, unchanged rules, baselines and environment
    reproduce *record* exactly, hash and signature included. Any difference is
    a real divergence, and ``divergence()`` says where it came from.

    A replay under different rules is a counterfactual: it is returned for
    comparison and never stored or allowed to replace the original.
    """
    return decide(
        readings=record["readings"],
        baselines=baselines,
        rules=rules,
        now=datetime.fromisoformat(record["ts"].replace("Z", "+00:00")),
        prev_hash=record["prev_hash"],
        astronaut_id=record["astronaut_id"],
        signing_key=signing_key,
        clock_source=(record.get("execution_manifest") or {}).get("clock_source", "caller"),
    )


def manifest_diff(original: dict, replayed: dict) -> dict:
    """Entries of the execution manifest that differ: ``{key: [original, replayed]}``."""
    old = original.get("execution_manifest") or {}
    new = replayed.get("execution_manifest") or {}
    return {key: [old.get(key), new.get(key)] for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)}


def divergence(original: dict, replayed: dict) -> dict:
    """Describe how a replayed Record differs from the original.

    ``identical``: same hash, so the same Record.
    ``decision_changed``: tier or action differs.
    ``environment_changed``: which parts of the decision environment (policy,
    limits, config, baselines, pipeline availability, versions, key) were not
    the same as when the original was made. An unexplained change, one where
    the decision differs but the environment does not, means the stored Record
    itself was altered.
    """
    old, new = original.get("verdict", {}), replayed.get("verdict", {})
    changed = manifest_diff(original, replayed)
    decision_changed = (old.get("tier"), old.get("action")) != (new.get("tier"), new.get("action"))
    return {
        "record_id": original.get("id"),
        "identical": original.get("hash") == replayed.get("hash"),
        "decision_changed": decision_changed,
        "old_tier": old.get("tier"),
        "new_tier": new.get("tier"),
        "old_action": old.get("action"),
        "new_action": new.get("action"),
        "rules_changed": original.get("versions", {}).get("rules") != replayed.get("versions", {}).get("rules"),
        "environment_changed": changed,
        "unexplained": decision_changed and not changed,
    }
