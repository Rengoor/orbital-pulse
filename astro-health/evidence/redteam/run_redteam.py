"""Runs every file in redteam/cases/ and asserts zero unsafe approvals.

Each case is an attack on the decision system: bad data, a failing component,
a misbehaving language model, or tampering with the records. The runner
carries out the attack against the real backend code and checks that it was
blocked. An *unsafe approval* is an attack that got a calmer answer than the
case allows, for example GREEN on stale data.

    python -m evidence.redteam.run_redteam            # table + evidence/results/redteam.{md,json}
    python -m evidence.redteam.run_redteam --no-write

Exit code 0 only when every attack was blocked.

Owner: person D
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import backend.pipelines.a_statistical.pipeline as pipeline_a
import backend.pipelines.b_limits.pipeline as pipeline_b
from backend.earth.verify import verify_chain
from backend.orchestrator import decide, load_rules
from backend.pipelines.d_llm import pipeline as pipeline_llm
from backend.records.anchor import build_anchor, check_against_anchor
from backend.records.chain import GENESIS, compute_hash
from backend.records.store import RecordStore

CASES_DIR = Path(__file__).resolve().parent / "cases"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
NOW = datetime(2026, 11, 14, 12, 0, 0)
_PIPELINES = {"a_statistical": pipeline_a, "b_limits": pipeline_b}


def _readings(specs: list[dict], astronaut_id: str) -> list[dict]:
    """Expand the compact case form into schema-valid readings."""
    out = []
    for spec in specs:
        spec = dict(spec)
        ts = NOW - timedelta(seconds=spec.pop("age_s", 0))
        out.append({"astronaut_id": astronaut_id, "ts": ts.isoformat() + "Z", "source": "simulated", **spec})
    return out


@contextlib.contextmanager
def _patched(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


@contextlib.contextmanager
def _env(name, value):
    before = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = before


def _decide(attack: dict, readings: list[dict], prev_hash: str = GENESIS, now: datetime = NOW) -> dict:
    rules = load_rules()
    if attack.get("policy_path"):
        rules["policy_path"] = attack["policy_path"]
    astronaut_id = attack.get("astronaut_id", "crew_1")

    with contextlib.ExitStack() as stack:
        if "llm_output" in attack:
            reply = attack["llm_output"]
            reply = reply if isinstance(reply, str) else json.dumps(reply)
            stack.enter_context(_env("LLM_ENABLED", "1"))
            stack.enter_context(_patched(pipeline_llm, "call_llm", lambda system, user: reply))
        else:
            stack.enter_context(_env("LLM_ENABLED", None))
        if attack.get("kill_pipeline"):
            def crash(readings, context):
                raise RuntimeError("pipeline killed by red team")

            stack.enter_context(_patched(_PIPELINES[attack["kill_pipeline"]], "run", crash))
        return decide(_readings(readings, astronaut_id), {}, rules, now, prev_hash=prev_hash, astronaut_id=astronaut_id)


def _chain(attack: dict, store: RecordStore) -> list[dict]:
    for i, readings in enumerate(attack["readings"]):
        store.append_with(lambda prev, i=i, readings=readings: _decide(attack, readings, prev, NOW + timedelta(minutes=i)))
    return store.all()


def run_case(case: dict) -> dict:
    """Carry out one attack. Returns the case with ``observed`` and ``blocked``."""
    attack, expect = case["attack"], case["expect"]
    problems: list[str] = []

    if attack["kind"] == "checkin":
        record = _decide(attack, attack["readings"])
        verdict = record["verdict"]
        observed = f"{verdict['tier']} / {verdict['action']}"
        if verdict["tier"] not in expect["tiers"]:
            problems.append(f"tier {verdict['tier']} is not one of {expect['tiers']}")
        for field, wanted in (expect.get("verdict") or {}).items():
            if verdict.get(field) != wanted:
                problems.append(f"verdict.{field} is {verdict.get(field)!r}, expected {wanted!r}")
        statuses = record["execution_manifest"]["pipelines"]
        for name, wanted in (expect.get("pipeline_status") or {}).items():
            if statuses.get(name) != wanted:
                problems.append(f"pipeline {name} is {statuses.get(name)!r}, expected {wanted!r}")
        # Nothing the attacker said may survive into what the crew is shown.
        shown = json.dumps([verdict["reasons"], verdict.get("decision_trace", {}).get("explanation"), record["proposals"]])
        for text in expect.get("forbid") or []:
            if text.lower() in shown.lower():
                problems.append(f"forbidden text {text!r} reached the record")

    elif attack["kind"] == "tamper":
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordStore(Path(tmp) / "records.db")
            records = _chain(attack, store)
            victim = copy.deepcopy(records[attack["edit_index"]])
            was = victim["verdict"]["tier"]
            victim["verdict"].update(tier="GREEN", action="NO_ACTION", reasons=[])
            victim["hash"] = compute_hash(victim)  # the attacker recomputes the hash
            with store._conn:
                store._conn.execute("UPDATE records SET body = ? WHERE id = ?", (json.dumps(victim), victim["id"]))
            result = verify_chain(store.all())
            store.close()
        observed = "tampering detected at the edited record" if not result["valid"] else f"edit of a {was} verdict went unnoticed"
        if result["valid"] != expect["chain_valid"] or result.get("broken_at") != victim["id"]:
            problems.append("the chain still verified after a record was edited")

    elif attack["kind"] == "truncate":
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordStore(Path(tmp) / "records.db")
            records = _chain(attack, store)
            anchor = build_anchor(records, NOW)
            with store._conn:
                store._conn.execute("DELETE FROM records WHERE seq > ?", (len(records) - attack["drop_last"],))
            remaining = store.all()
            chain_alone = verify_chain(remaining)["valid"]
            result = check_against_anchor(remaining, anchor)
            store.close()
        observed = f"chain alone: {'valid' if chain_alone else 'broken'}; checkpoint: {result['reason']}"
        if result["valid"] != expect["anchor_valid"]:
            problems.append("the checkpoint did not notice the missing records")

    else:
        raise ValueError(f"unknown attack kind {attack['kind']!r}")

    return {
        "id": case["id"],
        "title": case["title"],
        "area": case["area"],
        "description": case["description"],
        "observed": observed,
        "blocked": not problems,
        "problems": problems,
    }


def load_cases() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(CASES_DIR.glob("*.json"))]


def run_all() -> list[dict]:
    # The attacks make pipelines fail on purpose; their warnings are expected.
    logging.disable(logging.CRITICAL)
    try:
        with _env("SIGNING_KEY", os.environ.get("SIGNING_KEY") or "redteam-run-key"):
            return [run_case(case) for case in load_cases()]
    finally:
        logging.disable(logging.NOTSET)


def to_markdown(results: list[dict]) -> str:
    unsafe = [r for r in results if not r["blocked"]]
    lines = [
        "# Red-team results",
        "",
        f"{len(results)} attacks, {len(results) - len(unsafe)} blocked, **{len(unsafe)} unsafe approvals**.",
        "",
        "Generated by `python -m evidence.redteam.run_redteam`. Each row is a real run against the backend code.",
        "",
        "| # | Area | Attack | What happened | Blocked |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r['area']} | **{r['title']}.** {r['description']} | {r['observed']} | {'yes' if r['blocked'] else 'NO: ' + '; '.join(r['problems'])} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-write", action="store_true", help="print only; do not write evidence/results/")
    args = parser.parse_args(argv)

    results = run_all()
    for r in results:
        print(f"{'BLOCKED' if r['blocked'] else 'UNSAFE ':8} {r['id']:32} {r['observed']}")
        for problem in r["problems"]:
            print(f"         -> {problem}")
    unsafe = sum(not r["blocked"] for r in results)
    print(f"\n{len(results)} attacks, {len(results) - unsafe} blocked, {unsafe} unsafe approvals")

    if not args.no_write:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "redteam.md").write_text(to_markdown(results), encoding="utf-8", newline="\n")
        (RESULTS_DIR / "redteam.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 1 if unsafe else 0


if __name__ == "__main__":
    sys.exit(main())
