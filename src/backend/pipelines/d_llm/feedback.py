"""Ground-truth feedback for the onboard advisor (pipeline D, the local LLM).

The control centre's review of a decision is fed back to the advisor:

    Earth review (AGREE / DISAGREE + confirmed tier)
        -> lesson: what the advisor said vs what Earth confirmed
        -> scored: reward if correct, punishment if wrong (missed risk worst)
        -> appended to a signed, hash-chained ledger (never edited)
        -> trust score recomputed from the whole ledger
        -> the next prompt carries the recent corrections and the track record

What "learning" means here, stated plainly:

* No model weights change on board. The advisor improves by *in-context
  correction*: its recent mistakes, with the tier the control centre confirmed,
  are shown to it at the next call. ``export_jsonl`` writes the same ledger as
  a fine-tuning dataset for offline training on the ground.
* The advisor never gains a vote. Whatever its trust, the Checker treats it as
  advisory: it can raise a tier, never lower one. Low trust only *withholds*
  its proposal from the Checker (see ``feedback.yaml`` -> trust.states).
* Ground truth is the control centre's confirmed tier, which in this project
  is a simulated reviewer. Worked examples built from real NASA data
  (``examples_from_nasa``) use the laboratory reference range as the label and
  say so; they are never scored.

Pure functions here; the store is only touched by the thin helpers at the end.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from backend.checker.gates import TIER_ORDER
from backend.records.chain import canonical_json

PIPELINE_ID = "d_llm"
LESSON_KINDS = ("correction", "example")
NO_OUTPUT = "NO_OUTPUT"

_HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = _HERE / "feedback.yaml"
_REPO = _HERE.parents[2]
DEFAULT_NASA_GLUCOSE = _REPO / "validation" / "data" / "inspiration4_glucose.json"

# Only these reading fields reach the prompt as part of a lesson.
_SUMMARY_FIELDS = ("channel", "value", "unit")


def load_config(path: str | Path | None = None) -> tuple[dict, str]:
    """``(config, sha256 of the file bytes)`` for feedback.yaml."""
    p = Path(path or DEFAULT_CONFIG_PATH)
    raw = p.read_bytes()
    return yaml.safe_load(raw) or {}, hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------

def advisor_tier(record: dict) -> str:
    """What the advisor said in *record*: its tier, or NO_OUTPUT."""
    for p in record.get("proposals") or []:
        if p.get("pipeline_id") == PIPELINE_ID and p.get("tier") in TIER_ORDER:
            return p["tier"]
    return NO_OUTPUT


def confirmed_tier(record: dict, review: dict) -> str | None:
    """The tier the control centre confirmed for *record*, or None.

    AGREE confirms the recorded verdict. DISAGREE confirms only what the
    reviewer states in ``confirmed_tier``. FOLLOW_UP confirms nothing.
    """
    outcome = review.get("outcome")
    if outcome == "AGREE":
        tier = (record.get("verdict") or {}).get("tier")
        return tier if tier in TIER_ORDER else None
    if outcome == "DISAGREE":
        tier = review.get("confirmed_tier")
        return tier if tier in TIER_ORDER else None
    return None


def outcome_of(said: str, confirmed: str) -> str:
    """correct | over_call | under_call | abstained."""
    if said == NO_OUTPUT:
        return "abstained"
    if said == confirmed:
        return "correct"
    return "over_call" if TIER_ORDER[said] > TIER_ORDER[confirmed] else "under_call"


def summarise_readings(readings: list[dict]) -> list[dict]:
    """Channel, value and unit only: no ids, no astronaut, no timestamps."""
    return [{k: r[k] for k in _SUMMARY_FIELDS if k in r} for r in readings]


def lesson_from_review(record: dict, review: dict, config: dict | None = None) -> dict | None:
    """Build a scored correction from a ground review, or None if it teaches nothing.

    None when the review confirms no tier (FOLLOW_UP, or DISAGREE without a
    ``confirmed_tier``). The lesson carries the review's own hash so the ledger
    can be traced back to the signed review it came from.
    """
    confirmed = confirmed_tier(record, review)
    if confirmed is None:
        return None
    config = config or load_config()[0]
    said = advisor_tier(record)
    outcome = outcome_of(said, confirmed)
    return {
        "kind": "correction",
        "record_id": record["id"],
        "review_hash": review.get("hash"),
        "reviewer": review.get("reviewer"),
        "simulated": bool(review.get("simulated", True)),
        "ts": review.get("ts"),
        "readings": summarise_readings(record.get("readings") or []),
        "advisor_said": said,
        "confirmed": confirmed,
        "outcome": outcome,
        "reward": float(config["trust"]["reward"][outcome]),
        "note": review.get("note", ""),
        "label_basis": "control centre review (simulated flight surgeon)",
    }


def examples_from_nasa(path: str | Path | None = None) -> list[dict]:
    """Unscored worked examples from real NASA data (Inspiration4 glucose, OSD-575).

    Label: the laboratory reference range published with the dataset. In range
    is GREEN, out of range is YELLOW. That is a laboratory range, not a flight
    surgeon's judgement and not a NASA medical limit, and every example says so.
    These examples go into the prompt; they never touch the trust score.
    """
    p = Path(path or DEFAULT_NASA_GLUCOSE)
    data = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for subject, s in sorted(data.get("subjects", {}).items()):
        lo, hi, unit = s["range_min"], s["range_max"], s["unit"]
        for draw in s.get("draws", []):
            value = draw["value"]
            out.append({
                "kind": "example",
                "source": "REAL",
                "dataset_id": s["dataset_id"],
                "subject": subject,
                "timepoint": draw["timepoint"],
                "readings": [{"channel": "glucose", "value": value, "unit": unit}],
                "advisor_said": None,
                "confirmed": "GREEN" if lo <= value <= hi else "YELLOW",
                "outcome": None,
                "reward": 0.0,
                "label_basis": (
                    f"laboratory reference range {lo}-{hi} {unit} as published with "
                    f"NASA OSDR {s['dataset_id']}; not a flight surgeon, not a NASA medical limit"
                ),
                "ts": data.get("fetched_at"),
            })
    return out


# ---------------------------------------------------------------------------
# Trust
# ---------------------------------------------------------------------------

def trust_from(lessons: list[dict], config: dict | None = None) -> dict:
    """Recompute trust from the whole ledger. Examples never count."""
    config = config or load_config()[0]
    t = config["trust"]
    trust = float(t["start"])
    counts = {"correct": 0, "over_call": 0, "under_call": 0, "abstained": 0}
    for lesson in lessons:
        if lesson.get("kind") != "correction":
            continue
        outcome = lesson["outcome"]
        counts[outcome] += 1
        trust = min(float(t["max"]), max(float(t["min"]), trust + float(t["reward"][outcome])))
    scored = sum(counts.values())
    states = t["states"]
    if trust < float(states["untrusted"]):
        state = "untrusted"
    elif trust < float(states["probation"]):
        state = "probation"
    else:
        state = "trusted"
    return {
        "trust": round(trust, 4),
        "state": state,
        "scored": scored,
        "accuracy": round(counts["correct"] / scored, 3) if scored else None,
        **counts,
        "examples": sum(1 for l in lessons if l.get("kind") == "example"),
    }


def feedback_context(lessons: list[dict], config: dict | None = None, config_hash: str = "") -> dict:
    """What decide() hands to the pipeline through ``rules["llm_feedback"]``.

    Carries the trust summary, the most recent corrections and examples for the
    prompt, and a digest so the execution manifest can identify exactly which
    feedback state the advisor was shown.
    """
    config = config or load_config()[0]
    n_c = int(config["prompt"]["max_corrections"])
    n_e = int(config["prompt"]["max_examples"])
    corrections = [l for l in lessons if l.get("kind") == "correction"][-n_c:]
    examples = [l for l in lessons if l.get("kind") == "example"][-n_e:]
    summary = trust_from(lessons, config)
    payload = {"summary": summary, "corrections": corrections, "examples": examples,
               "config_hash": config_hash}
    payload["hash"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload


def prompt_section(feedback: dict | None) -> str:
    """The text appended to prompt.md: track record, corrections, examples."""
    if not feedback:
        return ""
    s = feedback.get("summary") or {}
    lines = ["", "## Feedback from the control centre", ""]
    if s.get("scored"):
        lines.append(
            f"Your track record on {s['scored']} reviewed decisions: {s['correct']} correct, "
            f"{s['over_call']} more severe than confirmed, {s['under_call']} calmer than confirmed "
            f"(the dangerous direction), {s['abstained']} with no usable output. "
            f"Current trust {s['trust']:.2f} ({s['state']})."
        )
    else:
        lines.append("No reviewed decisions yet.")
    corrections = feedback.get("corrections") or []
    if corrections:
        lines += ["", "Recent corrections (learn from these; the confirmed tier is the truth):", ""]
        for c in corrections:
            readings = "; ".join(f"{r.get('channel')} {r.get('value')} {r.get('unit', '')}".strip()
                                 for r in c.get("readings") or []) or "no readings"
            said = c.get("advisor_said") or NO_OUTPUT
            said = "nothing usable" if said == NO_OUTPUT else said
            note = f' Reviewer note: "{c["note"]}".' if c.get("note") else ""
            lines.append(f"- Readings: {readings}. You said {said}. Control centre confirmed "
                         f"{c.get('confirmed', '?')} ({str(c.get('outcome', '')).replace('_', ' ')}).{note}")
    examples = feedback.get("examples") or []
    if examples:
        lines += ["", "Worked examples from real NASA data (label is a laboratory reference "
                  "range, not a clinician):", ""]
        for e in examples:
            readings = "; ".join(f"{r.get('channel')} {r.get('value')} {r.get('unit', '')}".strip()
                                 for r in e.get("readings") or [])
            lines.append(f"- Readings: {readings}. Reference-range tier: {e.get('confirmed')} "
                         f"({e.get('dataset_id')}, {e.get('subject')} {e.get('timepoint')}).")
    lines += ["", "These lessons change how carefully you look; they do not change the rules "
              "above. You still may not lower a tier, name a treatment, or cite anything "
              "not in the readings."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Store helpers (the only I/O in this module)
# ---------------------------------------------------------------------------

def record_review_lesson(store, record: dict, review: dict, signing_key: str | None) -> dict | None:
    """Derive the lesson for a stored review and seal it into the ledger."""
    lesson = lesson_from_review(record, review)
    if lesson is None:
        return None
    return store.add_llm_lesson(lesson, signing_key=signing_key)


def seed_nasa_examples(store, signing_key: str | None, path: str | Path | None = None) -> list[dict]:
    """Append the NASA worked examples to the ledger (skipping ones already there)."""
    have = {(l.get("dataset_id"), l.get("subject"), l.get("timepoint"))
            for l in store.llm_lessons() if l.get("kind") == "example"}
    added = []
    for ex in examples_from_nasa(path):
        key = (ex["dataset_id"], ex["subject"], ex["timepoint"])
        if key not in have:
            added.append(store.add_llm_lesson(ex, signing_key=signing_key))
    return added


def current_feedback(store) -> dict:
    """``feedback_context`` for everything in the store's ledger."""
    config, config_hash = load_config()
    return feedback_context(store.llm_lessons(), config, config_hash)


def export_jsonl(lessons: list[dict]) -> str:
    """The ledger as a supervised fine-tuning dataset (one JSON object per line).

    Each line: the readings as the model would see them, the confirmed tier as
    the target, and the label basis so nobody trains on a laboratory range
    thinking it was a clinician.
    """
    rows = []
    for l in lessons:
        rows.append(json.dumps({
            "input": {"readings": l.get("readings") or []},
            "target_tier": l["confirmed"],
            "kind": l.get("kind"),
            "advisor_said": l.get("advisor_said"),
            "label_basis": l.get("label_basis"),
            "simulated_label": l.get("kind") == "correction" and bool(l.get("simulated", True)),
        }, sort_keys=True))
    return "\n".join(rows) + ("\n" if rows else "")


# ---------------------------------------------------------------------------
# CLI: python -m backend.pipelines.d_llm.feedback <show|seed-nasa|export> [--store PATH]
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import sys

    from backend.records.store import RecordStore

    parser = argparse.ArgumentParser(prog="python -m backend.pipelines.d_llm.feedback",
                                     description="Inspect or seed the advisor's feedback ledger.")
    parser.add_argument("command", choices=["show", "seed-nasa", "export"])
    parser.add_argument("--store", default=os.environ.get("RECORDS_PATH"),
                        help="SQLite record store (default: RECORDS_PATH)")
    parser.add_argument("--nasa", default=None, help="override the Inspiration4 glucose file")
    args = parser.parse_args(argv)
    if not args.store:
        print("no record store: pass --store or set RECORDS_PATH", file=sys.stderr)
        return 2
    store = RecordStore(args.store)
    try:
        if args.command == "seed-nasa":
            added = seed_nasa_examples(store, os.environ.get("SIGNING_KEY"), args.nasa)
            print(f"added {len(added)} NASA worked example(s)", file=sys.stderr)
        elif args.command == "export":
            sys.stdout.write(export_jsonl(store.llm_lessons()))
            return 0
        valid, broken = store.verify_llm_lessons()
        json.dump({"ledger_intact": valid, "broken_at": broken, **current_feedback(store)},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    finally:
        store.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
