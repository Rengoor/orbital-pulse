"""The onboard advisor's feedback loop (backend/pipelines/d_llm/feedback.py).

What these tests pin down:
* a ground review becomes a scored lesson; FOLLOW_UP and a bare DISAGREE do not;
* correct answers raise trust, a missed risk is punished hardest;
* the ledger is a signed chain, and tampering is detected;
* below the untrusted threshold the advisor's proposal is withheld, and even
  when trusted it is still advisory (the Checker's floor is unchanged);
* the prompt carries the corrections; the record's manifest says which feedback
  state was shown; the NASA worked examples are labelled and never scored.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from backend.checker.checker import check
from backend.earth.review import build_review
from backend.pipelines.d_llm import feedback as fb
from backend.pipelines.d_llm import pipeline as llm_pipeline
from backend.records.store import RecordStore
from backend.tests.test_api import _STORM_READINGS, _reading
from backend.tests.test_api import api  # noqa: F401 - the in-process API fixture

_REPO = Path(__file__).resolve().parents[2]
_POLICY = str(_REPO / "backend" / "checker" / "policy.yaml")
with open(_REPO / "data" / "schemas" / "review.schema.json") as _f:
    _REVIEW_SCHEMA = json.load(_f)
_KEY = "test-key"
_CONFIG = fb.load_config()[0]


def _record(advisor_tier: str | None, verdict_tier: str = "YELLOW", rid: str = "rec-1") -> dict:
    proposals = [{"pipeline_id": "a_statistical", "tier": verdict_tier, "reasons": [], "data_fault": False}]
    if advisor_tier:
        proposals.append({"pipeline_id": "d_llm", "tier": advisor_tier, "reasons": ["x"], "data_fault": False})
    return {
        "id": rid,
        "readings": [{"id": "r1", "astronaut_id": "crew_1", "channel": "heart_rate",
                      "value": 120.0, "unit": "bpm", "ts": "t"}],
        "proposals": proposals,
        "verdict": {"tier": verdict_tier},
    }


def _review(outcome: str, confirmed_tier: str | None = None, note: str = "") -> dict:
    return build_review("rec-1", outcome, note=note, signing_key=_KEY, confirmed_tier=confirmed_tier)


# ---------------------------------------------------------------------------
# Lessons from reviews
# ---------------------------------------------------------------------------

def test_review_schema_accepts_confirmed_tier_and_rejects_bad_ones():
    jsonschema.validate(_review("DISAGREE", "RED"), _REVIEW_SCHEMA)
    with pytest.raises(ValueError, match="confirmed_tier"):
        build_review("rec-1", "DISAGREE", confirmed_tier="PURPLE")


@pytest.mark.parametrize(
    "advisor, outcome, confirmed, expected",
    [
        ("YELLOW", "AGREE", None, "correct"),        # agrees with the recorded YELLOW
        ("GREEN", "AGREE", None, "under_call"),      # advisor calmer than confirmed
        ("RED", "AGREE", None, "over_call"),         # advisor more severe than confirmed
        (None, "AGREE", None, "abstained"),          # advisor produced nothing
        ("GREEN", "DISAGREE", "RED", "under_call"),  # ground says it should have been RED
        ("RED", "DISAGREE", "RED", "correct"),       # advisor was right, the Checker was not
    ],
)
def test_lesson_scores_the_advisor_against_the_confirmed_tier(advisor, outcome, confirmed, expected):
    lesson = fb.lesson_from_review(_record(advisor), _review(outcome, confirmed))
    assert lesson["outcome"] == expected
    assert lesson["reward"] == _CONFIG["trust"]["reward"][expected]
    assert lesson["confirmed"] == (confirmed or "YELLOW")
    assert lesson["readings"] == [{"channel": "heart_rate", "value": 120.0, "unit": "bpm"}]
    assert "astronaut_id" not in json.dumps(lesson["readings"])


def test_reviews_that_confirm_nothing_teach_nothing():
    assert fb.lesson_from_review(_record("GREEN"), _review("FOLLOW_UP")) is None
    assert fb.lesson_from_review(_record("GREEN"), _review("DISAGREE")) is None   # no confirmed_tier


# ---------------------------------------------------------------------------
# Trust: reward, punishment, states
# ---------------------------------------------------------------------------

def _lesson(outcome: str) -> dict:
    return {"kind": "correction", "outcome": outcome}


def test_trust_starts_neutral_and_moves_with_rewards():
    t = _CONFIG["trust"]
    assert fb.trust_from([])["trust"] == t["start"]
    up = fb.trust_from([_lesson("correct")] * 3)
    assert up["trust"] == pytest.approx(t["start"] + 3 * t["reward"]["correct"])
    assert up["accuracy"] == 1.0 and up["scored"] == 3


def test_missing_risk_is_punished_harder_than_a_false_alarm():
    r = _CONFIG["trust"]["reward"]
    assert r["under_call"] < r["over_call"] < 0 < r["correct"]
    assert fb.trust_from([_lesson("under_call")])["trust"] < fb.trust_from([_lesson("over_call")])["trust"]


def test_trust_is_clamped_and_states_follow_thresholds():
    assert fb.trust_from([_lesson("under_call")] * 50)["trust"] == _CONFIG["trust"]["min"]
    assert fb.trust_from([_lesson("under_call")] * 50)["state"] == "untrusted"
    assert fb.trust_from([_lesson("correct")] * 50)["trust"] == _CONFIG["trust"]["max"]
    assert fb.trust_from([_lesson("correct")] * 50)["state"] == "trusted"
    assert fb.trust_from([])["state"] == "probation"


def test_examples_never_change_trust():
    examples = fb.examples_from_nasa()
    assert examples, "the Inspiration4 glucose snapshot should yield worked examples"
    assert fb.trust_from(examples)["trust"] == _CONFIG["trust"]["start"]
    assert fb.trust_from(examples)["examples"] == len(examples)


# ---------------------------------------------------------------------------
# NASA worked examples
# ---------------------------------------------------------------------------

def test_nasa_examples_are_labelled_by_laboratory_range_and_say_so():
    glucose = json.loads((_REPO / "validation" / "data" / "inspiration4_glucose.json").read_text())
    examples = fb.examples_from_nasa()
    assert len(examples) == sum(len(s["draws"]) for s in glucose["subjects"].values())
    for e in examples:
        s = glucose["subjects"][e["subject"]]
        value = e["readings"][0]["value"]
        assert e["confirmed"] == ("GREEN" if s["range_min"] <= value <= s["range_max"] else "YELLOW")
        assert e["kind"] == "example" and e["source"] == "REAL" and e["outcome"] is None
        assert "laboratory reference range" in e["label_basis"]
        assert "not a NASA medical limit" in e["label_basis"]


# ---------------------------------------------------------------------------
# The ledger is a signed chain
# ---------------------------------------------------------------------------

def test_ledger_chains_and_detects_tampering():
    # The store verifies with the environment's SIGNING_KEY, so seal with it (None).
    store = RecordStore()
    a = store.add_llm_lesson(fb.lesson_from_review(_record("GREEN"), _review("AGREE")), signing_key=None)
    b = store.add_llm_lesson(fb.lesson_from_review(_record("YELLOW"), _review("AGREE")), signing_key=None)
    assert a["prev_hash"] == "GENESIS" and b["prev_hash"] == a["hash"]
    assert store.verify_llm_lessons() == (True, None)

    tampered = dict(a, outcome="correct")   # rewrite the punishment into a reward
    with store._conn:
        store._conn.execute("UPDATE llm_feedback SET body = ? WHERE record_id = ? AND seq = 1",
                            (json.dumps(tampered, sort_keys=True), "rec-1"))
    assert store.verify_llm_lessons() == (False, 0)
    store.close()


def test_seeding_nasa_examples_is_idempotent():
    store = RecordStore()
    first = fb.seed_nasa_examples(store, None)
    second = fb.seed_nasa_examples(store, None)
    assert len(first) > 0 and second == []
    assert store.verify_llm_lessons() == (True, None)
    store.close()


# ---------------------------------------------------------------------------
# The pipeline reads its feedback: prompt, withholding, still advisory
# ---------------------------------------------------------------------------

def _rules_with(lessons: list[dict]) -> dict:
    return {"llm_feedback": fb.feedback_context(lessons, _CONFIG, "cfg")}


def _valid_reply(tier="RED"):
    return json.dumps({"pipeline_id": "d_llm", "tier": tier, "reasons": ["heart rate high"],
                       "data_fault": False, "reading_ids": ["r1"]})


def test_prompt_carries_corrections_and_track_record(monkeypatch):
    seen = {}
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm_pipeline, "call_llm", lambda s, u: seen.setdefault("system", s) and _valid_reply())
    lesson = fb.lesson_from_review(_record("GREEN"), _review("DISAGREE", "RED", note="SPE in progress"))
    llm_pipeline.run([_reading()], {"now": None, "rules": _rules_with([lesson])})
    system = seen["system"]
    assert "JSON only" in system                                  # the hard rules are still there
    assert "Feedback from the control centre" in system
    assert "You said GREEN. Control centre confirmed RED (under call)" in system
    assert 'Reviewer note: "SPE in progress"' in system
    assert "Current trust" in system


def test_untrusted_advisor_is_withheld_without_calling_the_model(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    calls = []
    monkeypatch.setattr(llm_pipeline, "call_llm", lambda s, u: calls.append(1) or _valid_reply())
    bad = [_lesson("under_call")] * 10
    assert fb.trust_from(bad)["state"] == "untrusted"
    assert llm_pipeline.run([_reading()], {"now": None, "rules": _rules_with(bad)}) is None
    assert calls == []
    # Corrected back above the threshold, it speaks again.
    recovered = bad + [_lesson("correct")] * 10
    assert fb.trust_from(recovered)["state"] != "untrusted"
    assert llm_pipeline.run([_reading()], {"now": None, "rules": _rules_with(recovered)})["tier"] == "RED"
    assert calls == [1]


def test_a_fully_trusted_advisor_still_cannot_lower_a_tier():
    """Trust changes whether the advisor is heard, never what it may do."""
    core = [{"pipeline_id": "a_statistical", "tier": "RED", "reasons": ["r"], "data_fault": False},
            {"pipeline_id": "b_limits", "tier": "RED", "reasons": ["r"], "data_fault": False}]
    advisor = {"pipeline_id": "d_llm", "tier": "GREEN", "reasons": ["looks fine"], "data_fault": False}
    readings = [_reading("r1", channel="heart_rate", value=170.0)]
    assert fb.trust_from([_lesson("correct")] * 50)["state"] == "trusted"
    verdict = check(core + [advisor], readings, _POLICY)
    assert verdict["tier"] == "RED"


def test_record_manifest_says_which_feedback_the_advisor_saw(monkeypatch):
    from datetime import datetime

    from backend.orchestrator import decide, load_rules

    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setattr(llm_pipeline, "call_llm", lambda s, u: _valid_reply("YELLOW"))
    lessons = [fb.lesson_from_review(_record("GREEN"), _review("AGREE"))]
    rules = {**load_rules(), "llm_feedback": fb.feedback_context(lessons, _CONFIG, "cfg")}
    record = decide([_reading()], {}, rules, datetime(2026, 11, 14, 8, 0, 0))
    shown = record["execution_manifest"]["llm"]["feedback"]
    assert shown["hash"] == rules["llm_feedback"]["hash"]
    assert shown["scored"] == 1 and shown["under_call"] == 1
    # The feedback is not part of the rules digest: a review must not look like a rule change.
    plain = decide([_reading()], {}, load_rules(), datetime(2026, 11, 14, 8, 0, 0))
    assert plain["versions"]["rules"] == record["versions"]["rules"]


# ---------------------------------------------------------------------------
# Through the API: review -> lesson -> ledger -> status / HUD
# ---------------------------------------------------------------------------

def test_review_feeds_the_advisor_ledger_and_the_hud_sees_trust(api, monkeypatch):
    record_id = api.checkin("crew_1", _STORM_READINGS)["record_id"]
    empty = api.get("/earth/llm-feedback").json()
    assert empty["lessons"] == [] and empty["summary"]["state"] == "probation"

    # AGREE confirms the recorded tier; the advisor was off, so it abstained.
    resp = api.post("/earth/review", json={"record_id": record_id, "outcome": "AGREE"})
    assert resp.status_code == 200
    jsonschema.validate(resp.json(), _REVIEW_SCHEMA)
    fed = api.get("/earth/llm-feedback").json()
    assert [l["outcome"] for l in fed["lessons"]] == ["abstained"]
    assert fed["lessons"][0]["review_hash"] == resp.json()["hash"]
    assert fed["chain"] == {"valid": True, "broken_at": None}

    # DISAGREE without a confirmed tier teaches nothing; with one it does.
    api.post("/earth/review", json={"record_id": record_id, "outcome": "DISAGREE"})
    api.post("/earth/review", json={"record_id": record_id, "outcome": "DISAGREE", "confirmed_tier": "RED"})
    fed = api.get("/earth/llm-feedback").json()
    assert [l["confirmed"] for l in fed["lessons"]] == [fed["lessons"][0]["confirmed"], "RED"]
    assert api.post("/earth/review", json={"record_id": record_id, "outcome": "DISAGREE",
                                           "confirmed_tier": "PURPLE"}).status_code == 422

    # NASA worked examples load once and are labelled.
    added = api.post("/earth/llm-feedback/nasa-examples").json()["added"]
    assert added > 0
    assert api.post("/earth/llm-feedback/nasa-examples").json()["added"] == 0
    fed = api.get("/earth/llm-feedback").json()
    assert fed["summary"]["examples"] == added and fed["summary"]["scored"] == 2

    # What the HUD reads: advisor off here, so no live trust and no tier from it.
    status = api.get("/status/crew_1").json()
    assert status["advisor"]["enabled"] is False and status["advisor"]["said"] is None
    assert status["tier"] == "RED"                       # the Checker's tier, untouched

    # Export is a fine-tuning dataset with the label basis on every line.
    rows = [json.loads(line) for line in fb.export_jsonl(api.store.llm_lessons()).splitlines()]
    assert len(rows) == 2 + added
    assert all("label_basis" in r and r["target_tier"] in ("GREEN", "YELLOW", "RED", "GREY") for r in rows)
