"""Delay-aware autonomy: who can take part in a decision in time.

For every verdict, compare how soon its action must start (autonomy.yaml)
with how soon Earth could answer: round-trip light time at the current link
plus an assumed ground turnaround. The result is a handoff record in its own
hash-linked, signed chain:

    GROUND_IN_LOOP     Earth's answer arrives before the action's deadline.
    ONBOARD_AUTHORITY  It cannot: the crew acts on the onboard verdict alone,
                       and ground confirms or corrects later.
    ROUTINE            The action has no deadline; ground reviews it in the
                       normal course.

A handoff never changes a verdict, a tier or an action. It is computed after
the Record is logged and only says who can be in the loop in time, so Earth can
later audit which decisions the crew had to own alone.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from backend.common.schema_check import validate
from backend.downlink.delay import DISTANCES_KM, delay_for

DEFAULT_AUTONOMY_PATH = Path(__file__).resolve().parents[1] / "checker" / "autonomy.yaml"
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "schemas" / "handoff.schema.json"

MODES = ("GROUND_IN_LOOP", "ONBOARD_AUTHORITY", "ROUTINE")
LINK_LABELS = {"leo": "Low Earth orbit", "moon": "Moon", "mars_near": "Mars (closest)", "mars_far": "Mars (farthest)"}


def load_autonomy_policy(path: str | Path | None = None) -> tuple[dict, str]:
    """(policy, sha256 of the file's bytes)."""
    raw = Path(path or DEFAULT_AUTONOMY_PATH).read_bytes()
    policy = yaml.safe_load(raw) or {}
    if not isinstance(policy.get("action_deadline_s"), dict):
        raise ValueError("autonomy policy has no action_deadline_s table")
    return policy, hashlib.sha256(raw).hexdigest()


def link_for(preset: str | None = None, one_way_delay_s: float | None = None, label: str | None = None) -> dict:
    """A link description from a named preset, or a custom one-way delay."""
    if one_way_delay_s is not None:
        if one_way_delay_s < 0:
            raise ValueError("one_way_delay_s must be non-negative")
        return {"preset": None, "label": label or f"Custom ({one_way_delay_s:g} s one way)",
                "one_way_delay_s": float(one_way_delay_s)}
    preset = preset or "moon"
    if preset not in DISTANCES_KM:
        raise ValueError(f"unknown link preset {preset!r}; expected one of {sorted(DISTANCES_KM)}")
    return {"preset": preset, "label": label or LINK_LABELS.get(preset, preset), "one_way_delay_s": delay_for(preset)}


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.rstrip("Z")[:26])


def _fmt(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds") + "Z"


def assess(record: dict, link: dict, policy: dict, policy_hash: str) -> dict:
    """Return the (unsealed) handoff for one Record under *link*.

    The deadline is the tightest one among the verdict's action and any
    additional actions, so a GREY verdict hiding a known RED is judged by the
    RED's urgency too.
    """
    verdict = record["verdict"]
    actions = [verdict["action"], *verdict.get("additional_actions", [])]
    table = policy["action_deadline_s"]
    unknown = [a for a in actions if a not in table]
    if unknown:
        raise ValueError(f"autonomy policy has no deadline for {unknown}")
    deadlines = [table[a] for a in actions if table[a] is not None]
    deadline = min(deadlines) if deadlines else None

    one_way = float(link["one_way_delay_s"])
    turnaround = float(policy.get("ground_turnaround_s", 0))
    earth_answer_s = 2 * one_way + turnaround

    if deadline is None:
        mode = "ROUTINE"
    elif earth_answer_s <= deadline:
        mode = "GROUND_IN_LOOP"
    else:
        mode = "ONBOARD_AUTHORITY"

    decided = _parse_ts(record["ts"])
    handoff = {
        "record_id": record["id"],
        "astronaut_id": record["astronaut_id"],
        "mode": mode,
        "tier": verdict["tier"],
        "actions": actions,
        "action_deadline_s": deadline,
        "link": {"preset": link.get("preset"), "label": link["label"], "one_way_delay_s": round(one_way, 3)},
        "ground_turnaround_s": turnaround,
        "earth_answer_s": round(earth_answer_s, 3),
        "verdict_reaches_earth_at": _fmt(decided + timedelta(seconds=one_way)),
        "earliest_ground_answer_at": _fmt(decided + timedelta(seconds=earth_answer_s)),
        "policy_version": str(policy.get("version", "")),
        "policy_hash": policy_hash,
        "ts": _fmt(datetime.now(timezone.utc).replace(tzinfo=None)),
    }
    validate(handoff, str(_SCHEMA_PATH))
    return handoff


def review_arrival(review: dict, one_way_delay_s: float, now: datetime | None = None) -> dict:
    """When a ground review reaches the crew, given the light delay.

    The delay used is the link in force now: a simplification, since the
    link changes slowly compared with one review's travel time.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    arrives = _parse_ts(review["ts"]) + timedelta(seconds=one_way_delay_s)
    return {"arrives_at": _fmt(arrives), "arrived": now >= arrives}
