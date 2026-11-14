"""Tests for d_llm.

Owner: person A
"""

import json
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.checker.checker import check
from backend.checker.gates import TIER_ORDER
from backend.orchestrator import decide
from backend.pipelines.d_llm import pipeline as llm_pipeline
from backend.pipelines.d_llm.parser import parse_llm_response

_REPO = Path(__file__).resolve().parents[2]
_POLICY_PATH = str(_REPO / "backend" / "checker" / "policy.yaml")
with open(_REPO / "data" / "schemas" / "proposal.schema.json") as _f:
    _PROPOSAL_SCHEMA = json.load(_f)

_NOW = datetime(2026, 11, 14, 8, 0, 0)
_TIERS = ["GREEN", "YELLOW", "RED", "GREY"]


def _valid(**overrides) -> dict:
    return {
        "pipeline_id": "d_llm",
        "tier": "YELLOW",
        "reasons": ["heart rate trending upward across the window"],
        "data_fault": False,
        "reading_ids": ["r1"],
        **overrides,
    }


def _reading(rid="r1", value=72.0, quality="ok"):
    return {
        "id": rid,
        "astronaut_id": "crew_1",
        "ts": "2026-11-14T08:00:00Z",
        "channel": "heart_rate",
        "value": value,
        "unit": "bpm",
        "source": "simulated",
        "quality": quality,
    }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parser_accepts_bare_json():
    assert parse_llm_response(json.dumps(_valid())) == _valid()


def test_parser_accepts_json_in_a_code_fence_with_prose():
    raw = "Here is my assessment:\n```json\n" + json.dumps(_valid(), indent=2) + "\n```\nThanks."
    assert parse_llm_response(raw) == _valid()


def test_parser_skips_a_non_json_brace_before_the_object():
    raw = "Considering {the window}: " + json.dumps(_valid())
    assert parse_llm_response(raw) == _valid()


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "I think this looks fine.",
        "{not json at all",
        "[1, 2, 3]",
        '"just a string"',
        json.dumps({"tier": "RED"}),                                # missing required fields
        json.dumps(_valid(tier="PURPLE")),                          # tier outside the enum
        json.dumps(_valid(tier="red")),                             # wrong case
        json.dumps(_valid(reasons="one string, not a list")),
        json.dumps(_valid(data_fault="false")),                     # string, not boolean
        json.dumps(_valid(reading_ids=[1, 2])),
        json.dumps(_valid(pipeline_id="b_limits")),                 # impersonating another pipeline
        json.dumps(_valid())[:-10],                                 # truncated output
    ],
)
def test_parser_discards_bad_output(raw):
    assert parse_llm_response(raw) is None


@pytest.mark.parametrize(
    "reason",
    [
        "Recommend a 400 mg dose of ibuprofen",
        "suggest increasing the dosage",
        "The crew member should take medication for this",
        "Start treatment immediately",
        "administer fluids",
        "consider oxygen therapy",
        "give 2 tablets",
        "prescribe rest",
        "a suitable drug would help",
        "10mg would be appropriate",
    ],
)
def test_parser_discards_any_mention_of_dose_drug_or_treatment(reason):
    assert parse_llm_response(json.dumps(_valid(reasons=["heart rate elevated", reason]))) is None


@pytest.mark.parametrize(
    "reason",
    [
        "dose rate is ten times the earlier readings",
        "radiation dose rising while mood declines",
        "dose_rate_usv_h peaked at 260",
    ],
)
def test_parser_keeps_radiation_dose_rate_observations(reason):
    assert parse_llm_response(json.dumps(_valid(reasons=[reason]))) is not None


@pytest.mark.parametrize("raw", [None, 42, b"bytes", ["list"], {"a": 1}])
def test_parser_never_raises_on_non_text(raw):
    assert parse_llm_response(raw) is None


def test_parser_survives_deeply_nested_input():
    assert parse_llm_response("{" * 100_000) is None
    assert parse_llm_response('{"a":' * 50_000) is None


@given(raw=st.text(max_size=2000))
def test_parser_never_raises(raw):
    """parse_llm_response never raises; returns None or a dict."""
    result = parse_llm_response(raw)
    assert result is None or isinstance(result, dict)


_jsonish = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=10) | st.sampled_from(_TIERS + ["d_llm"]),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(
        st.sampled_from(["pipeline_id", "tier", "reasons", "data_fault", "reading_ids", "x"]),
        children,
        max_size=6,
    ),
    max_leaves=12,
)


@given(
    obj=_jsonish,
    prefix=st.text(max_size=30),
    suffix=st.text(max_size=30),
)
def test_parser_output_always_schema_valid(obj, prefix, suffix):
    """Whenever the parser returns a dict, it is a schema-valid d_llm Proposal."""
    result = parse_llm_response(prefix + json.dumps(obj) + suffix)
    if result is not None:
        jsonschema.validate(result, _PROPOSAL_SCHEMA)
        assert result["pipeline_id"] == "d_llm"


@given(raw=st.text(max_size=2000))
def test_parser_output_always_schema_valid_on_arbitrary_text(raw):
    result = parse_llm_response(raw)
    if result is not None:
        jsonschema.validate(result, _PROPOSAL_SCHEMA)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _fail_if_called(*args, **kwargs):
    raise AssertionError("the LLM must not be called")


@pytest.mark.parametrize("value", [None, "0", "", "true", "yes", "2"])
def test_pipeline_returns_none_without_calling_llm_when_disabled(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("LLM_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LLM_ENABLED", value)
    monkeypatch.setattr(llm_pipeline, "call_llm", _fail_if_called)
    assert llm_pipeline.run([_reading()], {"now": _NOW}) is None


def test_pipeline_returns_parsed_proposal_when_enabled(monkeypatch):
    seen = {}

    def fake_llm(system_prompt, user_message):
        seen["system"], seen["user"] = system_prompt, user_message
        return json.dumps(_valid(tier="RED"))

    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm_pipeline, "call_llm", fake_llm)
    proposal = llm_pipeline.run([_reading()], {"now": _NOW, "baselines": {}, "rules": {}})

    assert proposal["tier"] == "RED"
    jsonschema.validate(proposal, _PROPOSAL_SCHEMA)
    # The prompt carries the three hard rules; the message carries the readings.
    assert "JSON only" in seen["system"]
    sent = json.loads(seen["user"])
    assert sent["readings"][0]["id"] == "r1"
    assert "astronaut_id" not in sent["readings"][0]


def test_pipeline_strips_data_fault_claims_and_unknown_reading_ids(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(
        llm_pipeline,
        "call_llm",
        lambda s, u: json.dumps(_valid(data_fault=True, reading_ids=["r1", "invented"])),
    )
    proposal = llm_pipeline.run([_reading()], {"now": _NOW})
    assert proposal["data_fault"] is False
    assert proposal["reading_ids"] == ["r1"]


@pytest.mark.parametrize(
    "output",
    ["sorry, I cannot help with that", json.dumps(_valid(reasons=["take a 5 mg dose"])), None],
)
def test_pipeline_returns_none_on_unusable_output(monkeypatch, output):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm_pipeline, "call_llm", lambda s, u: output)
    assert llm_pipeline.run([_reading()], {"now": _NOW}) is None


def test_pipeline_returns_none_when_the_call_fails(monkeypatch):
    def boom(system_prompt, user_message):
        raise RuntimeError("network down")

    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm_pipeline, "call_llm", boom)
    assert llm_pipeline.run([_reading()], {"now": _NOW}) is None


def test_call_llm_talks_only_to_the_local_server(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, json, timeout):
        seen.update(url=url, body=json)
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"message": {"content": "reply text"}}, request=request)

    for var in ("OLLAMA_HOST", "LLM_MODEL", "LLM_TIMEOUT_S"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(httpx, "post", fake_post)

    assert llm_pipeline.call_llm("system rules", "user data") == "reply text"
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["body"]["model"] == llm_pipeline.DEFAULT_MODEL
    assert seen["body"]["stream"] is False
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9999/")
    monkeypatch.setenv("LLM_MODEL", "mistral")
    llm_pipeline.call_llm("s", "u")
    assert seen["url"] == "http://127.0.0.1:9999/api/chat"
    assert seen["body"]["model"] == "mistral"


def test_pipeline_returns_none_when_no_local_server_is_running(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setenv("LLM_TIMEOUT_S", "2")
    assert llm_pipeline.run([_reading()], {"now": _NOW}) is None


def test_prompt_states_the_three_hard_rules():
    prompt = (Path(llm_pipeline.__file__).parent / "prompt.md").read_text(encoding="utf-8").lower()
    assert "json only" in prompt
    assert "never lower a tier" in prompt
    for word in ("dose", "drug", "treatment"):
        assert word in prompt


# ---------------------------------------------------------------------------
# Orchestrator integration (A-11.4) and tier monotonicity
# ---------------------------------------------------------------------------

def test_none_from_llm_has_no_effect_on_the_verdict(monkeypatch):
    readings = [_reading()]

    monkeypatch.delenv("LLM_ENABLED", raising=False)
    baseline = decide(readings, {}, {}, _NOW)

    # Enabled, but the model returns garbage: the proposal is silently skipped.
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm_pipeline, "call_llm", lambda s, u: "no json here")
    with_failed_llm = decide(readings, {}, {}, _NOW)

    assert with_failed_llm["verdict"] == baseline["verdict"]
    assert with_failed_llm["proposals"] == baseline["proposals"]
    assert all(p["pipeline_id"] != "d_llm" for p in with_failed_llm["proposals"])


def test_enabled_llm_proposal_reaches_the_record_and_can_raise(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm_pipeline, "call_llm", lambda s, u: json.dumps(_valid(tier="RED")))
    record = decide([_reading()], {}, {}, _NOW)
    assert "d_llm" in [p["pipeline_id"] for p in record["proposals"]]
    assert record["verdict"]["tier"] == "RED"


@pytest.mark.parametrize("llm_tier", _TIERS)
@pytest.mark.parametrize("core_tier", _TIERS)
def test_llm_tier_monotonicity(core_tier, llm_tier):
    """For every tier pair, the verdict with the LLM is never below the verdict without it."""
    core = [
        {"pipeline_id": "a_statistical", "tier": core_tier, "reasons": ["x"], "data_fault": False}
    ]
    llm = parse_llm_response(json.dumps(_valid(tier=llm_tier)))
    without = check(core, [_reading()], _POLICY_PATH)
    with_llm = check(core + [llm], [_reading()], _POLICY_PATH)
    assert TIER_ORDER[with_llm["tier"]] >= TIER_ORDER[without["tier"]]
    assert TIER_ORDER[with_llm["tier"]] == max(TIER_ORDER[core_tier], TIER_ORDER[llm_tier])
