"""decide(readings, baselines, rules, now) -> Record. Runs pipelines blind, calls the Checker, builds the record. Pure core: no clock, no database, no network inside.

Owner: person A
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml

from backend.checker.checker import CHECKER_VERSION, check
from backend.pipelines import discover_pipelines
from backend.records.chain import GENESIS, canonical_json, seal

logger = logging.getLogger(__name__)

ORCHESTRATOR_VERSION = "0.1.0"

# Resolve paths relative to this file so they work regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
_SCHEMA_DIR = _REPO_ROOT / "data" / "schemas"

DEFAULT_POLICY_PATH = _BACKEND_DIR / "checker" / "policy.yaml"
DEFAULT_CONFIG_PATH = _BACKEND_DIR / "pipelines" / "a_statistical" / "config.yaml"
DEFAULT_LIMITS_PATH = _BACKEND_DIR / "pipelines" / "b_limits" / "limits_table.yaml"

_RECORD_ID_NAMESPACE = uuid.UUID("6f1d2c1e-8f0a-5d43-9b7e-a57c0ea17b00")


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


def _run_pipelines(readings: list[dict], context: dict) -> list[dict]:
    proposals: list[dict] = []

    for module in discover_pipelines():
        pid = _pipeline_id(module)
        try:
            # Each pipeline gets its own copy so none can see or disturb another.
            proposal = module.run(copy.deepcopy(readings), dict(context))
        except Exception as exc:  # noqa: BLE001 — any pipeline failure becomes GREY
            logger.warning("Pipeline %s raised: %s", pid, exc)
            proposals.append(_failed_pipeline_proposal(pid, "failed to run"))
            continue

        if proposal is None:
            # Optional pipeline declined (e.g. LLM disabled or unparseable output).
            continue

        if not _PROPOSAL_VALIDATOR.is_valid(proposal):
            logger.warning("Pipeline %s returned a schema-invalid proposal", pid)
            proposals.append(_failed_pipeline_proposal(pid, "returned an invalid proposal"))
            continue

        proposals.append(proposal)

    if not proposals:
        # Nothing looked at the data, so nothing can vouch for it.
        proposals.append(_failed_pipeline_proposal("orchestrator", "found no pipeline output"))

    return proposals


# ---------------------------------------------------------------------------
# The pure core
# ---------------------------------------------------------------------------

def decide(
    readings: list[dict],
    baselines: dict,
    rules: dict,
    now: datetime,
    *,
    prev_hash: str = GENESIS,
    astronaut_id: str | None = None,
    signing_key: str | None = None,
) -> dict:
    """Run every pipeline blind, adjudicate through the Checker, return a signed Record.

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

    Same inputs always give the same Record, including id, hash and signature.

    Raises
    ------
    ValueError
        If a reading fails schema validation or readings span several astronauts.
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

    # Shared context: baselines, rules, now — never another pipeline's output.
    context = {
        "baselines": baselines.get(astronaut_id, {}),
        "rules": rules,
        "now": now,
    }
    proposals = _run_pipelines(readings, context)

    policy_path = str(rules.get("policy_path") or DEFAULT_POLICY_PATH)
    verdict = check(
        proposals,
        readings,
        policy_path,
        reevaluate=lambda remaining: _run_pipelines(remaining, context),
    )

    ts = format_ts(now)
    provenance = []
    for r in readings:
        p = r.get("provenance")
        if p and p not in provenance:
            provenance.append(p)

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
        "proposals": proposals,
        "verdict": verdict,
        "provenance": provenance,
        "versions": {
            "orchestrator": ORCHESTRATOR_VERSION,
            "checker": CHECKER_VERSION,
            "rules": hashlib.sha256(canonical_json(rules).encode("utf-8")).hexdigest(),
        },
    }
    # Link to the previous Record, hash, sign (backend/records).
    record = seal(record, prev_hash, signing_key)

    error = jsonschema.exceptions.best_match(_RECORD_VALIDATOR.iter_errors(record))
    if error is not None:
        raise ValueError(f"Record failed record.schema.json validation: {error.message}")

    return record

