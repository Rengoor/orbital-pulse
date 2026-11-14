"""Optional pipeline, off by default (LLM_ENABLED=0). Same run() signature as the others.

Owner: person A
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from backend.pipelines.d_llm.parser import parse_llm_response

logger = logging.getLogger(__name__)

PIPELINE_ID = "d_llm"
# A local model served by Ollama on loopback only. Override with env vars.
DEFAULT_HOST = "http://localhost:11434"   # OLLAMA_HOST (must be loopback)
DEFAULT_MODEL = "llama3.2"                # LLM_MODEL
DEFAULT_TIMEOUT_S = 120.0                 # LLM_TIMEOUT_S: local models can be slow
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _require_loopback_host(host: str) -> str:
    """Validate that *host* resolves strictly to a local loopback address.

    Raises ValueError if the scheme is not http or the hostname is not on
    loopback, preventing any reading from ever leaving the local machine.
    """
    cleaned = host.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme != "http" or (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"OLLAMA_HOST must be a local loopback http URL (localhost, 127.0.0.1, ::1); got {host!r}"
        )
    return cleaned

_PROPOSAL_FORMAT = {
    "type": "object",
    "required": ["pipeline_id", "tier", "reasons", "data_fault", "reading_ids"],
    "properties": {
        "pipeline_id": {"const": PIPELINE_ID},
        "tier": {"enum": ["GREEN", "YELLOW", "RED", "GREY"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "data_fault": {"type": "boolean"},
        "reading_ids": {"type": "array", "items": {"type": "string"}},
    },
}

_PROMPT_PATH = Path(__file__).resolve().parent / "prompt.md"

# Only what the model needs to assess the window; no astronaut identifier.
_READING_FIELDS = ("id", "ts", "channel", "analyte", "value", "unit", "quality")


def _build_user_message(readings: list[dict], context: dict) -> str:
    now = context.get("now")
    return json.dumps(
        {
            "now": now.isoformat() if hasattr(now, "isoformat") else None,
            "readings": [
                {k: r[k] for k in _READING_FIELDS if k in r} for r in readings
            ],
        },
        default=str,
    )


def call_llm(system_prompt: str, user_message: str) -> str | None:
    """Ask the local model for one reply and return its text.

    Talks to an Ollama server on this machine over loopback HTTP only: no API
    key, and no reading ever leaves the host. Raises ValueError if OLLAMA_HOST
    points outside loopback, or on connection/HTTP errors; run() handles them.
    """
    import httpx  # imported lazily: only needed when the pipeline is enabled

    base_url = _require_loopback_host(os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    response = httpx.post(
        f"{base_url}/api/chat",
        json={
            "model": os.environ.get("LLM_MODEL", DEFAULT_MODEL),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            # Constrain the reply to the Proposal shape; the parser still checks it.
            "format": _PROPOSAL_FORMAT,
            "options": {"temperature": 0},
        },
        timeout=float(os.environ.get("LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
        trust_env=False,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w]*\d)")


def ungrounded(proposal: dict, readings: list[dict]) -> str | None:
    """Return why *proposal* is not grounded in *readings*, or None when it is.

    A language model can state things that were never in its input. Two checks
    catch the forms that matter here:

    * every reading id it cites must be one it was actually given;
    * every figure in its reasons (two or more digits, or with a decimal
      point) must be the value of a reading it was given. Single digits are
      allowed so it can count ("3 readings").

    An ungrounded proposal is discarded whole, like any other unusable output.
    """
    known_ids = {r.get("id") for r in readings}
    invented = [rid for rid in proposal.get("reading_ids") or [] if rid not in known_ids]
    if invented:
        return f"cites reading ids it was not given: {invented}"

    values = [float(r["value"]) for r in readings if isinstance(r.get("value"), (int, float))]
    for reason in proposal.get("reasons") or []:
        for token in _NUMBER.findall(reason):
            if "." not in token and len(token.lstrip("-")) < 2:
                continue
            number = float(token)
            if not any(abs(number - v) <= max(0.05, abs(v) * 0.005) for v in values):
                return f"states a figure ({token}) that is not in the readings"
    return None


def run(readings: list[dict], context: dict) -> dict | None:
    """Return an advisory Proposal, or None when there is nothing usable.

    None is returned when LLM_ENABLED != "1", when the call fails, when the
    model's output does not survive the parser, and when it cites readings or
    figures it was never given (see ``ungrounded``). The orchestrator skips
    None, so the other pipelines carry the decision. The Checker guarantees
    this proposal can raise the verdict but never lower it.
    """
    if os.environ.get("LLM_ENABLED", "0") != "1":
        return None

    try:
        raw = call_llm(
            _PROMPT_PATH.read_text(encoding="utf-8"),
            _build_user_message(readings, context),
        )
    except Exception as exc:  # noqa: BLE001 - a failed LLM call is not an error
        logger.warning("LLM call failed; skipping d_llm proposal: %s", exc)
        return None

    if raw is None:
        return None

    proposal = parse_llm_response(raw)
    if proposal is None:
        return None

    problem = ungrounded(proposal, readings)
    if problem is not None:
        logger.warning("LLM proposal is not grounded in the readings (%s); discarded", problem)
        return None

    # Confirming a data fault is not the LLM's job (prompt.md, rule 2).
    proposal["data_fault"] = False
    return proposal
