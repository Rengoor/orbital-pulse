"""Shared plumbing for the evidence runners: scenarios, ablated conditions, attacks.

Everything here *measures* the backend; nothing in it decides anything for the
crew. The ablated conditions exist only to show what each layer of the real
system adds, and their numbers are reported as such.

Honesty notes, which every runner's output repeats:
- storm_day and normal_day are simulated drafts (status "draft" in the files).
- The limits are the project-defined placeholders in limits_table.yaml, not
  NASA medical limits.

Owner: person D
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import backend.pipelines.a_statistical.pipeline as pipeline_a
import backend.pipelines.b_limits.pipeline as pipeline_b
from backend.api.state import load_all_baselines
from backend.orchestrator import decide, load_rules

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "data" / "scenarios"
RESULTS = Path(__file__).resolve().parent / "results"

# For "was the answer calmer than allowed": GREY (cannot verify, treated as
# urgent) blocks an attack as surely as RED, so it shares the top rank.
SEVERITY = {"GREEN": 0, "YELLOW": 1, "RED": 2, "GREY": 2}

CONDITIONS = ("a_only", "b_only", "a_plus_b", "fixed_threshold", "full")


def load_scenario(name: str) -> dict:
    return json.loads((SCENARIOS / f"{name}.json").read_text(encoding="utf-8"))


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)


def _pipeline_tier(module, readings: list[dict], context: dict) -> str:
    """One pipeline alone, no input gate, no Checker. A crash is reported as
    CRASHED: an ablated system without the fail-safe simply has no answer."""
    try:
        proposal = module.run(copy.deepcopy(readings), dict(context))
    except Exception:  # noqa: BLE001 - that fragility is the finding
        return "CRASHED"
    return proposal["tier"] if proposal else "GREEN"


def _fixed_threshold_tier(readings: list[dict], limits: dict) -> str:
    """The naive monitor: compare each value to the table, ignore quality,
    staleness, units and contradictions. The baseline the architecture beats."""
    worst = "GREEN"
    for r in readings:
        row = (limits.get("channels") or {}).get(r["channel"]) or {}
        hit = pipeline_b._breach(float(r["value"]), row)
        if hit and SEVERITY[hit[0]] > SEVERITY[worst]:
            worst = hit[0]
    return worst


def condition_tier(
    condition: str,
    readings: list[dict],
    rules: dict,
    baselines: dict,
    now: datetime,
    astronaut_id: str | None = None,
) -> str:
    """Tier the given condition assigns to one check-in."""
    if readings and astronaut_id is None:
        astronaut_id = readings[0]["astronaut_id"]
    own = baselines.get(astronaut_id or "", {})
    context = {"baselines": own, "rules": rules, "now": now}

    if condition == "a_only":
        return _pipeline_tier(pipeline_a, readings, context)
    if condition == "b_only":
        return _pipeline_tier(pipeline_b, readings, context)
    if condition == "a_plus_b":
        tiers = [
            _pipeline_tier(pipeline_a, readings, context),
            _pipeline_tier(pipeline_b, readings, context),
        ]
        if "CRASHED" in tiers:
            return "CRASHED"
        return max(tiers, key=lambda t: SEVERITY[t])
    if condition == "fixed_threshold":
        return _fixed_threshold_tier(readings, rules.get("limits") or {})
    if condition == "full":
        record = decide(readings, baselines, rules, now, astronaut_id=astronaut_id)
        return record["verdict"]["tier"]
    raise ValueError(f"unknown condition {condition!r}")


def run_scenario_tiers(condition: str, scenario: dict, rules: dict, baselines: dict) -> list[dict]:
    """Tier per event, events in timestamp order (same order the CLI uses)."""
    rows = []
    events = sorted(enumerate(scenario["events"]), key=lambda p: (parse_ts(p[1]["ts"]), p[0]))
    for _, event in events:
        now = parse_ts(event["ts"])
        tier = condition_tier(condition, event.get("readings", []), rules, baselines, now,
                              astronaut_id=event.get("astronaut_id"))
        rows.append({"ts": event["ts"], "tier": tier})
    return rows


def truth_breach_indices(scenario: dict, limits: dict) -> list[int]:
    """Event indices (in timestamp order) where some reading crosses a limit of
    the default table. Mechanical ground truth: no medical judgement added."""
    out = []
    events = sorted(enumerate(scenario["events"]), key=lambda p: (parse_ts(p[1]["ts"]), p[0]))
    for pos, (_, event) in enumerate(events):
        for r in event.get("readings", []):
            row = (limits.get("channels") or {}).get(r["channel"]) or {}
            if pipeline_b._breach(float(r["value"]), row):
                out.append(pos)
                break
    return out


def pure_data_attacks() -> list[dict]:
    """Red-team check-in cases that need no LLM stub, no pipeline kill and no
    alternate policy: the ones every ablated condition can be fairly fed."""
    from evidence.redteam.run_redteam import NOW, _readings, load_cases

    out = []
    for case in load_cases():
        attack = case["attack"]
        if attack["kind"] != "checkin":
            continue
        if any(k in attack for k in ("llm_output", "kill_pipeline", "policy_path")):
            continue
        out.append({
            "id": case["id"],
            "title": case["title"],
            "readings": _readings(attack["readings"], attack.get("astronaut_id", "crew_1")),
            "astronaut_id": attack.get("astronaut_id", "crew_1"),
            "allowed_tiers": case["expect"]["tiers"],
            "now": NOW,
        })
    return out


def is_unsafe(observed: str, allowed_tiers: list[str]) -> bool:
    """Calmer than every allowed answer. CRASHED is counted unsafe: a monitor
    that dies on bad input has approved nothing but protects no one."""
    if observed == "CRASHED":
        return True
    floor = min(SEVERITY[t] for t in allowed_tiers)
    return SEVERITY[observed] < floor


def default_rules_and_baselines(limits_file: str | None = None) -> tuple[dict, dict]:
    return load_rules(limits_file=limits_file), load_all_baselines(None)


def write_results(stem: str, markdown: str, data) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{stem}.md").write_text(markdown, encoding="utf-8", newline="\n")
    (RESULTS / f"{stem}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
