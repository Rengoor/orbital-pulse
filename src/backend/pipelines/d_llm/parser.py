"""Strict JSON-schema parse; anything unparseable is discarded and logged.

Owner: person A
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import jsonschema

logger = logging.getLogger(__name__)

PIPELINE_ID = "d_llm"

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "schemas" / "proposal.schema.json"
)
with open(_SCHEMA_PATH, encoding="utf-8") as _f:
    _PROPOSAL_SCHEMA = json.load(_f)
_VALIDATOR = jsonschema.validators.validator_for(_PROPOSAL_SCHEMA)(_PROPOSAL_SCHEMA)

_DECODER = json.JSONDecoder()

# Hard rule 3 of prompt.md, enforced here rather than trusted: a proposal whose
# reasons talk about dosing, drugs or treatment never reaches the Checker.
# "dose rate" / "radiation dose" are measurements, not treatment, and are allowed.
_FORBIDDEN = re.compile(
    r"\b((?<!radiation\s)dos(e|es|ed|age|ages|ing)(?![\s-]*rate)|drugs?|medicat\w*|medicines?"
    r"|treat(s|ed|ing|ment|ments)?|therap\w*|prescri\w*|administer\w*"
    r"|inject\w*|infus\w*|pills?|tablets?|capsules?)\b"
    r"|\d\s*(mg|mcg|ug|ml|iu)\b",
    re.IGNORECASE,
)

_LOG_LIMIT = 500


def _extract_first_json_object(raw: str):
    """Return the first JSON value that decodes at an opening brace, or None.

    Tolerates surrounding prose and markdown code fences by trying each
    opening brace in turn.
    """
    start = raw.find("{")
    while start != -1:
        try:
            obj, _ = _DECODER.raw_decode(raw, start)
        except (ValueError, RecursionError):
            start = raw.find("{", start + 1)
            continue
        return obj
    return None


def parse_llm_response(raw: str) -> dict | None:
    """Extract and validate a Proposal from raw LLM output.

    Returns None (after logging a warning) when *raw* holds no JSON object,
    when the object fails proposal.schema.json, when it claims to come from a
    different pipeline, or when its reasons mention a dose, drug or treatment.
    Never raises.
    """
    try:
        if not isinstance(raw, str):
            logger.warning("LLM response is not text; discarded")
            return None

        obj = _extract_first_json_object(raw)
        if not isinstance(obj, dict):
            logger.warning("LLM response contains no JSON object: %r", raw[:_LOG_LIMIT])
            return None

        error = jsonschema.exceptions.best_match(_VALIDATOR.iter_errors(obj))
        if error is not None:
            logger.warning(
                "LLM proposal fails schema (%s): %r", error.message, raw[:_LOG_LIMIT]
            )
            return None

        if obj["pipeline_id"] != PIPELINE_ID:
            logger.warning("LLM proposal claims pipeline_id %r; discarded", obj["pipeline_id"])
            return None

        if any(_FORBIDDEN.search(reason) for reason in obj["reasons"]):
            logger.warning(
                "LLM proposal mentions a dose, drug or treatment; discarded: %r",
                raw[:_LOG_LIMIT],
            )
            return None

        return obj
    except Exception:  # noqa: BLE001 - the contract is "never raises"
        logger.warning("LLM response could not be parsed; discarded", exc_info=True)
        return None
