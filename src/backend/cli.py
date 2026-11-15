"""Entry points used by evidence/: run a scenario, replay with alternate rule files (--limits-file etc.), dump records.

    python -m backend.cli run-scenario <scenario_file> [--limits-file P] [--config P] [--out DIR] [--seed N]
    python -m backend.cli replay <record_id_or_file> [--rules P] [--limits-file P] [--out DIR]
    python -m backend.cli dump-records [--astronaut ID] [--format json|csv]
    python -m backend.cli anchor [--out FILE]
    python -m backend.cli verify-anchor <anchor_file>

Records persist only when a store is named, with --store or RECORDS_PATH (a
SQLite file, the same one the API uses). ``replay <record_id>`` and
``dump-records`` read from that store.

Owner: person A
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from backend.api.state import load_all_baselines
from backend.earth.replay import divergence
from backend.earth.replay import replay as replay_decision
from backend.orchestrator import decide, load_rules
from backend.records.anchor import build_anchor, check_against_anchor
from backend.records.chain import GENESIS
from backend.records.store import RecordStore

_CSV_FIELDS = [
    "id", "ts", "astronaut_id", "tier", "action", "reasons", "prev_hash", "hash", "signature",
]


class CliError(Exception):
    """A problem with the arguments or input files; reported without a traceback."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_everything(seed: int | None) -> None:
    """Fix every random source. decide() is deterministic already; this covers
    anything stochastic a pipeline or caller adds later."""
    if seed is None:
        return
    random.seed(seed)
    try:
        import numpy

        numpy.random.seed(seed)
    except ImportError:
        pass


def _load_structured(path: str) -> dict:
    """Load a YAML or JSON file that must contain a mapping."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)  # YAML is a superset of JSON
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise CliError(f"{path} is not valid YAML/JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CliError(f"{path} must contain a mapping at the top level")
    return data


def _build_rules(config_path: str | None, limits_file: str | None, rules_path: str | None = None) -> dict:
    try:
        rules = load_rules(config_path=config_path, limits_file=limits_file)
    except OSError as exc:
        raise CliError(f"cannot read {exc.filename}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise CliError(f"rule file is not valid YAML: {exc}") from exc
    if rules_path:
        # An alternate rules dict replaces the matching top-level keys. An
        # explicit --limits-file still wins for the limits table.
        override = _load_structured(rules_path)
        if limits_file:
            override.pop("limits", None)
        rules.update(override)
    return rules


def _load_baselines(baselines_path: str | None) -> dict:
    if baselines_path and not Path(baselines_path).is_file():
        raise CliError(f"baselines file {baselines_path} does not exist")
    try:
        return load_all_baselines(baselines_path)
    except (ValueError, AttributeError, TypeError) as exc:
        raise CliError(f"baselines file is not usable: {exc}") from exc


def _open_store(store_path: str | None, required: bool) -> RecordStore | None:
    path = store_path or os.environ.get("RECORDS_PATH")
    if not path:
        if required:
            raise CliError("no record store: pass --store or set RECORDS_PATH")
        return None
    if required and not Path(path).exists():
        raise CliError(f"record store {path} does not exist")
    return RecordStore(path)


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise CliError(f"bad event timestamp {ts!r}: expected ISO-8601") from exc


def _emit(records: list[dict] | dict, out_dir: str | None) -> None:
    """Write Records to stdout as JSON, or one file per Record into *out_dir*."""
    if out_dir is None:
        json.dump(records, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    items = records if isinstance(records, list) else [records]
    for i, record in enumerate(items):
        path = out / f"{i:04d}_{record['id']}.json"
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} record(s) to {out}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Subcommands (importable: evidence/ can call these directly)
# ---------------------------------------------------------------------------

def run_scenario(
    scenario_path: str,
    limits_file: str | None = None,
    config_path: str | None = None,
    out_dir: str | None = None,
    seed: int | None = None,
    store_path: str | None = None,
    baselines_path: str | None = None,
) -> list[dict]:
    """Run decide() once per scenario event in timestamp order.

    Records link through prev_hash exactly as in the live API. Returns the
    Records and writes them to *out_dir* (or stdout when it is None).
    """
    _seed_everything(seed)
    scenario = _load_structured(scenario_path)
    events = scenario.get("events")
    if not isinstance(events, list):
        raise CliError(f"{scenario_path} has no 'events' list")

    rules = _build_rules(config_path, limits_file)
    baselines = _load_baselines(baselines_path)
    store = _open_store(store_path, required=False)

    records: list[dict] = []
    timed = [(_parse_ts(e.get("ts")), i, e) for i, e in enumerate(events)]
    try:
        for now, i, event in sorted(timed, key=lambda t: (t[0], t[1])):
            def build(prev_hash: str, event=event, now=now) -> dict:
                return decide(
                    readings=event.get("readings", []),
                    baselines=baselines,
                    rules=rules,
                    now=now,
                    prev_hash=prev_hash,
                    astronaut_id=event.get("astronaut_id"),
                    clock_source="scenario",
                )

            try:
                if store is not None:
                    record = store.append_with(build)
                else:
                    record = build(records[-1]["hash"] if records else GENESIS)
            except ValueError as exc:
                raise CliError(f"event {i} ({event.get('ts')}): {exc}") from exc
            records.append(record)
    finally:
        # Release the SQLite file so a caller's temporary directory can be
        # removed (Windows refuses to delete an open database file).
        if store is not None:
            store.close()

    _emit(records, out_dir)
    return records


def replay(
    record_id_or_path: str,
    rules_path: str | None = None,
    limits_file: str | None = None,
    out_dir: str | None = None,
    store_path: str | None = None,
    baselines_path: str | None = None,
) -> dict:
    """Re-run decide() with the original inputs of a Record; returns the new Record.

    *record_id_or_path* is a JSON file holding one Record, or a record id to
    look up in the store. A summary of what changed goes to stderr.
    """
    if Path(record_id_or_path).is_file():
        original = _load_structured(record_id_or_path)
    else:
        store = _open_store(store_path, required=True)
        original = store.get(record_id_or_path)
        if original is None:
            raise CliError(f"no record {record_id_or_path!r} in the store (and no such file)")

    rules = _build_rules(None, limits_file, rules_path)
    try:
        new = replay_decision(original, _load_baselines(baselines_path), rules)
    except (ValueError, KeyError) as exc:
        raise CliError(f"cannot replay record: {exc}") from exc

    diff = divergence(original, new)
    if diff["identical"]:
        summary = "identical record (same hash)"
    elif not diff["decision_changed"]:
        summary = f"same decision ({diff['new_tier']} / {diff['new_action']}), different record hash"
    else:
        summary = (
            f"DIVERGED: {diff['old_tier']} / {diff['old_action']}"
            f" -> {diff['new_tier']} / {diff['new_action']}"
        )
    print(f"replay of {original.get('id')}: {summary}", file=sys.stderr)

    _emit(new, out_dir)
    return new


def dump_records(
    astronaut_id: str | None = None,
    fmt: str = "json",
    store_path: str | None = None,
) -> None:
    """Print stored Records, oldest first, as JSON or CSV."""
    store = _open_store(store_path, required=True)
    records = [
        r for r in store.all() if astronaut_id is None or r["astronaut_id"] == astronaut_id
    ]
    if fmt == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=_CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for r in records:
            verdict = r.get("verdict", {})
            writer.writerow(
                {
                    **{k: r.get(k, "") for k in _CSV_FIELDS},
                    "tier": verdict.get("tier", ""),
                    "action": verdict.get("action", ""),
                    "reasons": "; ".join(verdict.get("reasons", [])),
                }
            )
    else:
        json.dump(records, sys.stdout, indent=2)
        sys.stdout.write("\n")


def anchor(out_file: str | None = None, store_path: str | None = None) -> dict:
    """Write a signed checkpoint of the chain head, to be stored away from the records."""
    store = _open_store(store_path, required=True)
    checkpoint = build_anchor(store.all(), datetime.now(timezone.utc))
    text = json.dumps(checkpoint, indent=2) + "\n"
    if out_file:
        Path(out_file).write_text(text, encoding="utf-8")
        count = checkpoint["record_count"]
        print(f"wrote checkpoint of {count} record(s) to {out_file}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return checkpoint


def verify_anchor(anchor_file: str, store_path: str | None = None) -> dict:
    """Check the stored chain against a checkpoint file taken earlier."""
    store = _open_store(store_path, required=True)
    result = check_against_anchor(store.all(), _load_structured(anchor_file))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return result


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    store_help = "SQLite record store (default: $RECORDS_PATH)"
    baselines_help = "pre-flight draws JSON (default: $BASELINES_PATH)"

    p = sub.add_parser("run-scenario", help="run decide() over every event of a scenario file")
    p.add_argument("scenario_file")
    p.add_argument("--limits-file", help="replace b_limits/limits_table.yaml")
    p.add_argument("--config", help="replace a_statistical/config.yaml")
    p.add_argument("--out", help="directory for one JSON file per Record (default: stdout)")
    p.add_argument("--seed", type=int, help="fix the random seed")
    p.add_argument("--store", help=store_help + "; records are appended to it")
    p.add_argument("--baselines", help=baselines_help)

    p = sub.add_parser("replay", help="re-run decide() with the inputs of a stored Record")
    p.add_argument("record", metavar="record_id_or_file")
    p.add_argument("--rules", help="YAML/JSON rules dict merged over the defaults")
    p.add_argument("--limits-file", help="replace b_limits/limits_table.yaml")
    p.add_argument("--out", help="directory for the new Record (default: stdout)")
    p.add_argument("--store", help=store_help)
    p.add_argument("--baselines", help=baselines_help)

    p = sub.add_parser("dump-records", help="print stored Records")
    p.add_argument("--astronaut", help="only this astronaut_id")
    p.add_argument("--format", choices=["json", "csv"], default="json")
    p.add_argument("--store", help=store_help)

    p = sub.add_parser("anchor", help="export a signed checkpoint of the chain head")
    p.add_argument("--out", help="file to write (default: stdout)")
    p.add_argument("--store", help=store_help)

    p = sub.add_parser("verify-anchor", help="check the chain against a checkpoint taken earlier")
    p.add_argument("anchor_file")
    p.add_argument("--store", help=store_help)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run-scenario":
            run_scenario(
                args.scenario_file,
                limits_file=args.limits_file,
                config_path=args.config,
                out_dir=args.out,
                seed=args.seed,
                store_path=args.store,
                baselines_path=args.baselines,
            )
        elif args.command == "replay":
            replay(
                args.record,
                rules_path=args.rules,
                limits_file=args.limits_file,
                out_dir=args.out,
                store_path=args.store,
                baselines_path=args.baselines,
            )
        elif args.command == "anchor":
            anchor(out_file=args.out, store_path=args.store)
        elif args.command == "verify-anchor":
            return 0 if verify_anchor(args.anchor_file, store_path=args.store)["valid"] else 1
        else:
            dump_records(astronaut_id=args.astronaut, fmt=args.format, store_path=args.store)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
