"""decide(readings, baselines, rules, now) -> Record. Runs pipelines blind, calls the Checker, builds the record. Pure core: no clock, no database, no network inside.

Stages, in order:
  1. Input integrity gate   which readings are usable (checker/input_gate.py)
  2. Blind pipelines        each sees only the usable readings and the shared context
  3. Checker                one Verdict from all Proposals (checker/checker.py)
  4. Record                 linked, hashed, signed (records/)

If anything in stages 1-3 fails in a way nothing above anticipated, decide()
still returns a signed Record carrying the built-in fail-safe verdict: GREY,
contact ground. A failure of the governance layer is never shown as an
all-clear and never leaves the last good verdict standing as if it were current.

Owner: person A
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as PipelineTimeout
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml

from backend.checker import input_gate
from backend.checker.checker import CHECKER_VERSION, check, load_policy
from backend.pipelines import discover_pipelines
from backend.records.chain import GENESIS, canonical_json, seal
from backend.records.signing import is_demo_key, key_id

logger = logging.getLogger(__name__)

ORCHESTRATOR_VERSION = "0.2.0"
SCHEMA_VERSION = "0.1"

# Resolve paths relative to this file so they work regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
_SCHEMA_DIR = _REPO_ROOT / "data" / "schemas"

DEFAULT_POLICY_PATH = _BACKEND_DIR / "checker" / "policy.yaml"
DEFAULT_CONFIG_PATH = _BACKEND_DIR / "pipelines" / "a_statistical" / "config.yaml"
DEFAULT_LIMITS_PATH = _BACKEND_DIR / "pipelines" / "b_limits" / "limits_table.yaml"

_RECORD_ID_NAMESPACE = uuid.UUID("6f1d2c1e-8f0a-5d43-9b7e-a57c0ea17b00")
_DEFAULT_PIPELINE_TIMEOUT_S = 30.0

# The fail-safe verdict is written here, in code, on purpose: it must not
# depend on policy.yaml, the Checker, or anything else that may be what failed.
FAILSAFE_TIER = "GREY"
FAILSAFE_ACTION = "CONTACT_GROUND_URGENT"


def _load_validator(name: str) -> jsonschema.protocols.Validator:
    with open(_SCHEMA_DIR / name, encoding="utf-8") as f:
        schema = json.load(f)
    return jsonschema.validators.validator_for(schema)(schema)


# Compiled once at import time (cached validators, per the design doc).
_READING_VALIDATOR = _load_validator("reading.schema.json")
_PROPOSAL_VALIDATOR = _load_validator("proposal.schema.json")
_RECORD_VALIDATOR = _load_validator("record.schema.json")


# ---------------------------------------------------------------------------
# Rule loading (I/O helper for callers; decide() itself never loads rules)
# ---------------------------------------------------------------------------

def load_rules(
    config_path: str | os.PathLike | None = None,
    limits_file: str | os.PathLike | None = None,
    policy_path: str | os.PathLike | None = None,
) -> dict:
    """Build the ``rules`` dict that ``decide()`` expects.

    Keys: ``cusum`` and ``patterns`` (pipeline A config), ``limits`` (the
    limits table for pipeline B) and ``policy_path`` (Checker policy file).
    Each argument overrides the corresponding default file.
    """
    with open(config_path or DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    with open(limits_file or DEFAULT_LIMITS_PATH, encoding="utf-8") as f:
        limits = yaml.safe_load(f) or {}

    rules = dict(config)
    rules["limits"] = limits
    rules["policy_path"] = str(policy_path or DEFAULT_POLICY_PATH)
    return rules


def format_ts(now: datetime) -> str:
    """ISO-8601 UTC with a trailing Z. Naive datetimes are taken to be UTC."""
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    return now.isoformat() + "Z"


def _digest(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pipeline dispatch
# ---------------------------------------------------------------------------

def _pipeline_id(module) -> str:
    # backend.pipelines.<name>.pipeline -> <name>
    return module.__name__.split(".")[-2]


def _failed_pipeline_proposal(pipeline_id: str, why: str) -> dict:
    # A silent or broken pipeline is unverifiable data: treat it conservatively.
    return {
        "pipeline_id": pipeline_id,
        "tier": "GREY",
        "reasons": [f"pipeline {pipeline_id!r} {why}"],
        "data_fault": False,
        "reading_ids": [],
        "rule_ids": [],
    }


def _run_pipelines(readings: list[dict], context: dict, pipeline_policy: dict) -> tuple[list[dict], dict[str, str]]:
    """Run every discovered pipeline blind; return (proposals, status per pipeline).

    Statuses: ok, failed (raised), timeout, invalid_output (malformed
    proposal), no_output (an optional pipeline returned nothing), missing (in
    the policy but not discovered), disabled (optional and switched off).
    Each pipeline gets its own copy of the readings and its own context dict,
    and none ever sees another's result.
    """
    modules = {_pipeline_id(m): m for m in discover_pipelines()}
    timeout_s = float(pipeline_policy.get("timeout_s") or _DEFAULT_PIPELINE_TIMEOUT_S)
    proposals: list[dict] = []
    status: dict[str, str] = {}

    executor = ThreadPoolExecutor(max_workers=max(1, len(modules)), thread_name_prefix="pipeline")
    try:
        futures = {
            pid: executor.submit(module.run, copy.deepcopy(readings), dict(context))
            for pid, module in modules.items()
        }
        for pid in sorted(futures):
            try:
                proposal = futures[pid].result(timeout=timeout_s)
            except PipelineTimeout:
                logger.warning("Pipeline %s timed out after %ss", pid, timeout_s)
                status[pid] = "timeout"
                proposals.append(_failed_pipeline_proposal(pid, "timed out"))
                continue
            except Exception as exc:  # noqa: BLE001 - any pipeline failure becomes GREY
                logger.warning("Pipeline %s raised: %s", pid, exc)
                status[pid] = "failed"
                proposals.append(_failed_pipeline_proposal(pid, "failed to run"))
                continue

            if proposal is None:
                # Optional pipeline declined (e.g. unparseable LLM output).
                status[pid] = "no_output"
                continue

            if not _PROPOSAL_VALIDATOR.is_valid(proposal):
                logger.warning("Pipeline %s returned a schema-invalid proposal", pid)
                status[pid] = "invalid_output"
                proposals.append(_failed_pipeline_proposal(pid, "returned an invalid proposal"))
                continue

            status[pid] = "ok"
            proposals.append(proposal)
    finally:
        # Never wait on a pipeline that has already been written off.
        executor.shutdown(wait=False, cancel_futures=True)

    for pid in pipeline_policy.get("required") or []:
        status.setdefault(pid, "missing")
    for pid in pipeline_policy.get("optional") or []:
        status.setdefault(pid, "disabled")

    if not proposals:
        # Nothing looked at the data, so nothing can vouch for it.
        proposals.append(_failed_pipeline_proposal("orchestrator", "found no pipeline output"))

    return proposals, status


# ---------------------------------------------------------------------------
# Fail-safe
# ---------------------------------------------------------------------------

def failsafe_verdict(why: str) -> dict:
    """The verdict issued when the governance layer itself cannot run.

    Depends on nothing but this file. It does not try to fix or diagnose
    anything: it states that no verified decision exists and escalates.
    """
    return {
        "tier": FAILSAFE_TIER,
        "action": FAILSAFE_ACTION,
        "reasons": [f"FAIL-SAFE: no verified decision could be made ({why})"],
        "overruled_pipelines": [],
        "disagreement_status": "UNVERIFIABLE",
        "checker_version": CHECKER_VERSION,
        "ruleset_hash": "unavailable",
        "failsafe": True,
        "decision_trace": {
            "final_tier": FAILSAFE_TIER,
            "action_authorized": FAILSAFE_ACTION,
            "failsafe": True,
            "explanation": (
                "GREY: the decision system itself failed, so no assessment can be trusted. "
                f"Cause: {why}. Authorized action: {FAILSAFE_ACTION}."
            ),
        },
    }


# ---------------------------------------------------------------------------
# The pure core
# ---------------------------------------------------------------------------

def _baselines_digest(baselines: dict) -> str:
    plain = {
        channel: dataclasses.asdict(stats) if dataclasses.is_dataclass(stats) else stats
        for channel, stats in sorted(baselines.items())
    }
    return _digest(plain)


def decide(
    readings: list[dict],
    baselines: dict,
    rules: dict,
    now: datetime,
    *,
    prev_hash: str = GENESIS,
    astronaut_id: str | None = None,
    signing_key: str | None = None,
    clock_source: str = "caller",
    force_failsafe: str | None = None,
) -> dict:
    """Gate the inputs, run every pipeline blind, adjudicate, return a signed Record.

    Parameters
    ----------
    readings:
        Reading dicts; each is validated against reading.schema.json.
    baselines:
        ``{astronaut_id: {channel: BaselineStats}}``.
    rules:
        See ``load_rules()``. Missing keys fall back to pipeline defaults and
        the default policy file.
    now:
        Explicit clock. Never read from the system inside this function.
    prev_hash:
        Hash of the previous Record in the chain (``"GENESIS"`` for the first).
    astronaut_id:
        Used when ``readings`` is empty; otherwise taken from the readings.
    signing_key:
        HMAC key; defaults to the ``SIGNING_KEY`` environment variable.
    clock_source:
        Where ``now`` came from ("server", "request", "scenario", ...). Stored
        in the execution manifest; it does not affect the verdict.
    force_failsafe:
        When set, skip the assessment and record the fail-safe verdict with
        this text as the cause. For callers that caught a failure decide()
        could not, and still owe the crew a Record.

    Same inputs always give the same Record, including id, hash and signature.

    Raises
    ------
    ValueError
        If a reading fails schema validation or readings span several
        astronauts. These are caller errors. Any other failure produces a
        fail-safe Record instead of an exception.
    """
    for i, reading in enumerate(readings):
        error = jsonschema.exceptions.best_match(_READING_VALIDATOR.iter_errors(reading))
        if error is not None:
            raise ValueError(
                f"readings[{i}] failed reading.schema.json validation: {error.message}"
            )

    reading_owners = {r["astronaut_id"] for r in readings}
    if len(reading_owners) > 1:
        raise ValueError(
            f"readings span several astronauts ({sorted(reading_owners)}); one check-in is one astronaut"
        )
    if reading_owners:
        astronaut_id = next(iter(reading_owners))
    elif astronaut_id is None:
        astronaut_id = "crew_1"

    readings = copy.deepcopy(readings)
    ts = format_ts(now)
    policy_path = str(rules.get("policy_path") or DEFAULT_POLICY_PATH)
    own_baselines = baselines.get(astronaut_id, {})

    proposals: list[dict] = []
    integrity: dict | None = None
    pipeline_status: dict[str, str] = {}
    policy_hash = "unavailable"

    try:
        if force_failsafe is not None:
            raise RuntimeError(force_failsafe)
        policy, policy_hash = load_policy(policy_path)

        # Stage 1: which readings are usable at all.
        integrity = input_gate.evaluate(readings, now, policy.get("data_requirements") or {})
        usable = input_gate.usable_readings(readings, integrity)

        # Stage 2: blind pipelines. Shared context is baselines, rules, now -
        # never another pipeline's output.
        context = {"baselines": own_baselines, "rules": rules, "now": now}
        proposals, pipeline_status = _run_pipelines(usable, context, policy.get("pipelines") or {})

        # Stage 3: the referee.
        verdict = check(proposals, usable, policy_path, integrity=integrity, pipeline_status=pipeline_status)
    except Exception as exc:  # noqa: BLE001 - the governance layer failed: fail safe, never open
        logger.exception("decide() could not complete; issuing the fail-safe verdict")
        verdict = failsafe_verdict(f"{type(exc).__name__}: {exc}")

    provenance = []
    for r in readings:
        p = r.get("provenance")
        if p and p not in provenance:
            provenance.append(p)

    # Everything besides the readings that could change this verdict. A replay
    # that differs can be traced to the entry that differs. policy_path is a
    # machine-specific location, so the policy is identified by its hash.
    config = {k: v for k, v in rules.items() if k not in ("limits", "policy_path")}
    llm_enabled = os.environ.get("LLM_ENABLED", "0") == "1"
    manifest = {
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "checker_version": CHECKER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "policy_hash": policy_hash,
        "config_hash": _digest(config),
        "limits_hash": _digest(rules.get("limits")),
        "baselines_hash": _baselines_digest(own_baselines),
        "pipelines": pipeline_status,
        "llm": {"enabled": llm_enabled, "model": os.environ.get("LLM_MODEL") if llm_enabled else None},
        "clock_source": clock_source,
        "random_seed": None,  # nothing in the decision path draws random numbers
        "signing": {"key_id": key_id(signing_key), "demo_key": is_demo_key(signing_key)},
        "failsafe": bool(verdict.get("failsafe")),
    }

    record = {
        "id": str(
            uuid.uuid5(
                _RECORD_ID_NAMESPACE,
                canonical_json([prev_hash, ts, astronaut_id, readings]),
            )
        ),
        "ts": ts,
        "astronaut_id": astronaut_id,
        "readings": readings,
        "integrity": integrity or {"readings": [], "summary": None},
        "proposals": proposals,
        "verdict": verdict,
        "provenance": provenance,
        "versions": {
            "orchestrator": ORCHESTRATOR_VERSION,
            "checker": CHECKER_VERSION,
            "rules": _digest({"config": config, "limits": rules.get("limits"), "policy": policy_hash}),
        },
        "execution_manifest": manifest,
        "key_id": manifest["signing"]["key_id"],
    }
    # Link to the previous Record, hash, sign (backend/records).
    record = seal(record, prev_hash, signing_key)

    error = jsonschema.exceptions.best_match(_RECORD_VALIDATOR.iter_errors(record))
    if error is not None:
        raise ValueError(f"Record failed record.schema.json validation: {error.message}")

    return record
