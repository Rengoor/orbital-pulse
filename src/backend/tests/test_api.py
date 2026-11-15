"""Tests for api.

Owner: person A
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jsonschema
import pytest

from backend.api.main import create_app
from backend.earth.verify import verify_record
from backend.orchestrator import decide
from backend.records.chain import GENESIS
from backend.records.chain import compute_hash as compute_record_hash

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMAS = _ROOT / "data" / "schemas"


def _schema(name: str) -> dict:
    with open(_SCHEMAS / name) as f:
        return json.load(f)


_RECORD_SCHEMA = _schema("record.schema.json")
_VERDICT_SCHEMA = _schema("verdict.schema.json")
_REVIEW_SCHEMA = _schema("review.schema.json")
_CARD_SCHEMA = _schema("card.schema.json")


_UNITS = {"heart_rate": "bpm", "dose_rate_usv_h": "uSv/h", "sleep_hours": "h", "mood": "score_1_10"}


def _reading(rid="r1", astronaut_id="crew_1", channel="heart_rate", value=72.0, **extra) -> dict:
    return {
        "id": rid,
        "astronaut_id": astronaut_id,
        "ts": "2026-11-14T08:00:00Z",
        "channel": channel,
        "value": value,
        "unit": _UNITS.get(channel, "x"),
        "source": "simulated",
        **extra,
    }


# A window that breaks the dose-rate red limit (pipeline B) under default rules.
_STORM_READINGS = [
    _reading("s1", channel="dose_rate_usv_h", value=260.0),
    _reading("s2", channel="mood", value=3.0),
    _reading("s3", channel="sleep_hours", value=4.5),
]


_CHECKIN_TIME = "2026-11-14T08:00:30Z"


class Api:
    """Synchronous wrapper around httpx.AsyncClient against the in-process app."""

    def __init__(self, app):
        self.app = app
        self.store = app.state.ctx.store

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def go():
            # Report unhandled errors as the HTTP response a real client would see.
            transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(go())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def checkin(self, astronaut_id="crew_1", readings=None, now=_CHECKIN_TIME) -> dict:
        body = {"astronaut_id": astronaut_id, "readings": readings or []}
        if now is not None:
            body["now"] = now  # the test readings are stamped 08:00, so decide them then
        resp = self.post("/checkin", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()


@pytest.fixture
def api(monkeypatch):
    # Fresh app per test: empty in-memory store, LLM off, nothing written to disk.
    monkeypatch.setenv("SIGNING_KEY", "test-api-signing-key")
    for var in ("RECORDS_PATH", "BASELINES_PATH", "LLM_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    return Api(create_app())


def test_startup_blocks_unset_or_demo_signing_key(monkeypatch):
    monkeypatch.delenv("SIGNING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SIGNING_KEY"):
        create_app()

    monkeypatch.setenv("SIGNING_KEY", "demo-only-change-me")
    with pytest.raises(RuntimeError, match="SIGNING_KEY"):
        create_app()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def test_health_endpoint(api):
    resp = api.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # The key in use is identified, and the demo key is called out as such.
    assert body["signing_key"]["key_id"].startswith("k-")
    assert body["signing_key"]["demo_key"] is False  # the API refuses to start on the demo key


def test_all_seven_routes_are_registered(api):
    paths = {
        (method.upper(), path)
        for path, methods in api.app.openapi()["paths"].items()
        for method in methods
    }
    for route in [
        ("POST", "/checkin"),
        ("GET", "/status/{astronaut_id}"),
        ("GET", "/records"),
        ("GET", "/records/{record_id}"),
        ("GET", "/earth/verify/{record_id}"),
        ("POST", "/earth/replay"),
        ("POST", "/earth/review"),
        ("POST", "/earth/rulechange"),
        ("GET", "/earth/downlink"),
        ("POST", "/earth/downlink/release"),
        ("GET", "/records/{record_id}/card"),
        ("GET", "/health"),
    ]:
        assert route in paths


# ---------------------------------------------------------------------------
# POST /checkin
# ---------------------------------------------------------------------------

def test_checkin_returns_200_with_no_readings(api):
    data = api.checkin("crew_1", [])
    # autonomy: the delay-aware handoff summary (additive field, never part of the verdict).
    assert set(data) == {"record_id", "verdict", "autonomy"}
    assert isinstance(data["record_id"], str)
    jsonschema.validate(data["verdict"], _VERDICT_SCHEMA)


def test_checkin_nominal_reading_is_green(api):
    data = api.checkin("crew_42", [_reading(astronaut_id="crew_42")])
    assert data["verdict"]["tier"] == "GREEN"
    assert data["verdict"]["action"] == "NO_ACTION"


def test_checkin_fills_in_astronaut_id_on_readings(api):
    reading = _reading()
    del reading["astronaut_id"]
    data = api.checkin("crew_9", [reading])
    stored = api.store.get(data["record_id"])
    assert stored["astronaut_id"] == "crew_9"
    assert stored["readings"][0]["astronaut_id"] == "crew_9"


def test_checkin_logs_the_record_before_returning(api):
    data = api.checkin("crew_1", [_reading()])
    stored = api.store.get(data["record_id"])
    assert stored is not None
    assert stored["verdict"] == data["verdict"]
    jsonschema.validate(stored, _RECORD_SCHEMA)
    assert verify_record(stored)


def test_checkin_storm_window_is_red(api):
    data = api.checkin("crew_1", _STORM_READINGS)
    assert data["verdict"]["tier"] == "RED"
    assert data["verdict"]["action"] == "ALERT_CMO"


def test_checkin_unverified_fault_reading_is_grey(api):
    data = api.checkin("crew_1", [_reading(quality="fault")])
    assert data["verdict"]["tier"] == "GREY"
    assert data["verdict"]["action"] == "CONTACT_GROUND_URGENT"


@pytest.mark.parametrize(
    "body",
    [
        {},                                                        # no astronaut_id
        {"astronaut_id": "crew_1", "readings": "not a list"},
        {"astronaut_id": "crew_1", "readings": ["not an object"]},
        {"astronaut_id": 7, "readings": []},
        {"astronaut_id": "crew_1", "readings": [{"id": "r1"}]},    # missing required fields
        {"astronaut_id": "crew_1", "readings": [_reading(channel="telepathy")]},
        {"astronaut_id": "crew_1", "readings": [_reading(value="high")]},
        {"astronaut_id": "crew_1", "readings": [_reading(source="rumour")]},
        {"astronaut_id": "crew_1", "readings": [_reading(quality="perfect")]},
        {"astronaut_id": "crew_1", "readings": [_reading(astronaut_id="crew_2")]},
        {"astronaut_id": "crew_1", "readings": [_reading(), {"id": "r2"}]},  # one bad among good
    ],
)
def test_checkin_rejects_invalid_body_with_422_and_records_nothing(api, body):
    resp = api.post("/checkin", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]
    assert api.store.all() == []


def test_checkin_422_happens_before_decide_is_called(api, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("decide() must not run for an invalid body")

    monkeypatch.setattr("backend.api.routes.checkin.decide", fail)
    resp = api.post("/checkin", json={"astronaut_id": "crew_1", "readings": [{"id": "r1"}]})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"][:3] == ["body", "readings", 0]


def test_unexpected_fault_returns_structured_500(api, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(api.store, "append_with", boom)
    resp = api.post("/checkin", json={"astronaut_id": "crew_1", "readings": []})
    assert resp.status_code == 500
    assert resp.json() == {"error": "internal_error", "detail": "RuntimeError"}
    assert api.store.all() == []


# ---------------------------------------------------------------------------
# GET /status/{astronaut_id}
# ---------------------------------------------------------------------------

def test_status_404_when_no_records(api):
    assert api.get("/status/crew_1").status_code == 404


def test_status_returns_latest_verdict_for_that_astronaut_only(api):
    api.checkin("crew_1", [_reading("a1")])
    latest = api.checkin("crew_1", _STORM_READINGS)
    api.checkin("crew_2", [_reading("b1", astronaut_id="crew_2")])

    resp = api.get("/status/crew_1")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "tier", "action", "additional_actions", "known_severity",
        "disagreement_status", "reasons", "record_id", "ts",
        "autonomy", "ground_review",  # delay-aware handoff and latest ground review
    }  # no raw readings
    assert body["disagreement_status"] == "DISAGREEMENT"  # A said GREEN, B said RED
    assert body["record_id"] == latest["record_id"]
    assert (body["tier"], body["action"]) == ("RED", "ALERT_CMO")
    assert body["reasons"] == latest["verdict"]["reasons"]

    assert api.get("/status/crew_2").json()["tier"] == "GREEN"
    assert api.get("/status/crew_3").status_code == 404


# ---------------------------------------------------------------------------
# GET /records, GET /records/{record_id}
# ---------------------------------------------------------------------------

def test_records_empty_list(api):
    resp = api.get("/records")
    assert resp.status_code == 200
    assert resp.json() == []


def test_records_most_recent_first_with_filter_and_limit(api):
    ids = [
        api.checkin("crew_1", [_reading("a1")])["record_id"],
        api.checkin("crew_2", [_reading("b1", astronaut_id="crew_2")])["record_id"],
        api.checkin("crew_1", [_reading("a2")])["record_id"],
    ]

    everything = api.get("/records").json()
    assert [r["id"] for r in everything] == ids[::-1]
    for record in everything:
        jsonschema.validate(record, _RECORD_SCHEMA)

    crew_1 = api.get("/records", params={"astronaut_id": "crew_1"}).json()
    assert [r["id"] for r in crew_1] == [ids[2], ids[0]]

    assert [r["id"] for r in api.get("/records", params={"limit": 1}).json()] == [ids[2]]
    assert api.get("/records", params={"astronaut_id": "nobody"}).json() == []


@pytest.mark.parametrize("limit", ["0", "-1", "abc"])
def test_records_rejects_bad_limit(api, limit):
    assert api.get("/records", params={"limit": limit}).status_code == 422


def test_record_by_id_returns_full_signed_record(api):
    record_id = api.checkin("crew_1", [_reading()])["record_id"]
    resp = api.get(f"/records/{record_id}")
    assert resp.status_code == 200
    record = resp.json()
    jsonschema.validate(record, _RECORD_SCHEMA)
    assert record["hash"] == compute_record_hash(record)
    assert verify_record(record)
    assert record["readings"][0]["id"] == "r1"


def test_card_for_a_record(api):
    record_id = api.checkin("crew_1", _STORM_READINGS)["record_id"]
    resp = api.get(f"/records/{record_id}/card")
    assert resp.status_code == 200
    card = resp.json()
    jsonschema.validate(card, _CARD_SCHEMA)
    assert (card["record_id"], card["tier"], card["action"]) == (record_id, "RED", "ALERT_CMO")
    assert "dose_rate_usv_h" in card["headline"]
    assert card["simulated_labels"] == [
        "dose_rate_usv_h: simulated", "mood: simulated", "sleep_hours: simulated",
    ]
    assert api.get("/records/nope/card").status_code == 404


def test_record_by_id_404(api):
    assert api.get("/records/does-not-exist").status_code == 404


def test_records_are_read_only(api):
    record_id = api.checkin("crew_1", [])["record_id"]
    assert api.post("/records", json={}).status_code == 405
    assert api.request("DELETE", f"/records/{record_id}").status_code == 405
    assert api.request("PUT", f"/records/{record_id}", json={}).status_code == 405


# ---------------------------------------------------------------------------
# GET /earth/verify/{record_id}
# ---------------------------------------------------------------------------

def _overwrite(api, record: dict) -> None:
    """Edit a stored Record behind the back of the store, as someone with file access could."""
    with api.store._conn:
        api.store._conn.execute(
            "UPDATE records SET body = ? WHERE id = ?", (json.dumps(record), record["id"])
        )


def test_verify_valid_chain(api):
    ids = [api.checkin("crew_1", [_reading(f"r{i}")])["record_id"] for i in range(3)]
    for record_id in ids:
        assert api.get(f"/earth/verify/{record_id}").json() == {"valid": True, "broken_at": None}


def test_verify_404_for_unknown_record(api):
    assert api.get("/earth/verify/nope").status_code == 404


def test_verify_detects_tampering_and_names_the_first_broken_record(api):
    ids = [api.checkin("crew_1", [_reading(f"r{i}")])["record_id"] for i in range(3)]

    # Quietly soften the middle record's verdict after the fact.
    record = api.store.get(ids[1])
    record["verdict"]["reasons"] = ["nothing to see"]
    _overwrite(api, record)

    assert api.get(f"/earth/verify/{ids[0]}").json() == {"valid": True, "broken_at": None}
    assert api.get(f"/earth/verify/{ids[1]}").json() == {"valid": False, "broken_at": ids[1]}
    assert api.get(f"/earth/verify/{ids[2]}").json() == {"valid": False, "broken_at": ids[1]}


def test_verify_detects_a_rehashed_forgery(api):
    """Recomputing the hash after tampering is not enough without the signing key."""
    ids = [api.checkin("crew_1", [_reading(f"r{i}")])["record_id"] for i in range(2)]
    forged = api.store.get(ids[0])
    forged["verdict"]["reasons"] = ["edited after the fact"]
    forged["hash"] = compute_record_hash(forged)
    _overwrite(api, forged)
    assert api.get(f"/earth/verify/{ids[1]}").json() == {"valid": False, "broken_at": ids[0]}


# ---------------------------------------------------------------------------
# POST /earth/replay
# ---------------------------------------------------------------------------

def test_replay_with_same_rules_reproduces_the_record_exactly(api):
    record_id = api.checkin("crew_1", _STORM_READINGS)["record_id"]
    resp = api.post("/earth/replay", json={"record_id": record_id})
    assert resp.status_code == 200
    assert resp.json() == api.store.get(record_id)
    assert len(api.store.all()) == 1  # replays are not stored


def test_replay_with_rules_override_shows_divergence(api):
    record_id = api.checkin("crew_1", _STORM_READINGS)["record_id"]
    resp = api.post("/earth/replay", json={"record_id": record_id, "rules_override": {"limits": {"channels": {}}}})
    assert resp.status_code == 200
    replayed = resp.json()
    jsonschema.validate(replayed, _RECORD_SCHEMA)
    assert replayed["verdict"]["tier"] == "GREEN"
    assert replayed["hash"] != api.store.get(record_id)["hash"]
    assert api.store.get(record_id)["verdict"]["tier"] == "RED"  # original untouched


def test_replay_404_and_422(api):
    assert api.post("/earth/replay", json={"record_id": "nope"}).status_code == 404
    assert api.post("/earth/replay", json={}).status_code == 422
    record_id = api.checkin("crew_1", [])["record_id"]
    # A replay whose policy cannot be loaded fails safe instead of erroring.
    bad = {"record_id": record_id, "rules_override": {"policy_path": "/no/such/policy.yaml"}}
    resp = api.post("/earth/replay", json=bad)
    assert resp.status_code == 200
    assert resp.json()["verdict"]["failsafe"] is True
    assert resp.json()["verdict"]["tier"] == "GREY"


# ---------------------------------------------------------------------------
# POST /earth/review
# ---------------------------------------------------------------------------

def test_review_attaches_a_signed_simulated_review(api):
    record_id = api.checkin("crew_1", _STORM_READINGS)["record_id"]
    before = json.dumps(api.store.get(record_id), sort_keys=True)

    resp = api.post(
        "/earth/review",
        json={"record_id": record_id, "cmo_note": "Agree, keep monitoring.", "outcome": "AGREE"},
    )
    assert resp.status_code == 200
    review = resp.json()
    jsonschema.validate(review, _REVIEW_SCHEMA)
    assert review["prev_hash"] == GENESIS
    assert api.store.verify_reviews() == (True, None)
    assert review["record_id"] == record_id
    assert review["outcome"] == "AGREE"
    assert review["note"] == "Agree, keep monitoring."
    assert review["simulated"] is True
    assert len(review["signature"]) == 64

    assert api.store.reviews(record_id) == [review]
    # Reviews live beside the chain; the Record itself is never rewritten.
    assert json.dumps(api.store.get(record_id), sort_keys=True) == before
    assert api.get(f"/earth/verify/{record_id}").json()["valid"] is True


def test_review_defaults_to_follow_up(api):
    record_id = api.checkin("crew_1", [])["record_id"]
    review = api.post("/earth/review", json={"record_id": record_id, "cmo_note": "?"}).json()
    assert review["outcome"] == "FOLLOW_UP"


def test_review_404_and_422(api):
    assert api.post("/earth/review", json={"record_id": "nope", "cmo_note": ""}).status_code == 404
    record_id = api.checkin("crew_1", [])["record_id"]
    bad = {"record_id": record_id, "cmo_note": "", "outcome": "SHRUG"}
    assert api.post("/earth/review", json=bad).status_code == 422
    assert api.post("/earth/review", json={"cmo_note": "no record id"}).status_code == 422


# ---------------------------------------------------------------------------
# POST /earth/rulechange
# ---------------------------------------------------------------------------

def test_rulechange_reports_changed_and_unsafe_decisions(api):
    green_id = api.checkin("crew_1", [_reading("g1")])["record_id"]
    red_id = api.checkin("crew_1", _STORM_READINGS)["record_id"]

    # Proposed change: drop every limit. The RED day would have been GREEN.
    resp = api.post("/earth/rulechange", json={"rules_override": {"limits": {"channels": {}}}})
    assert resp.status_code == 200
    diff = resp.json()
    assert (diff["total"], diff["changed"], diff["unsafe"]) == (2, 1, 1)
    rows = {r["record_id"]: r for r in diff["rows"]}
    assert rows[green_id]["changed"] is False and rows[green_id]["unsafe"] is False
    assert (rows[red_id]["old_tier"], rows[red_id]["new_tier"]) == ("RED", "GREEN")
    assert rows[red_id]["changed"] is True and rows[red_id]["unsafe"] is True

    # Nothing in the store changed.
    assert api.store.get(red_id)["verdict"]["tier"] == "RED"
    assert len(api.store.all()) == 2


def test_rulechange_stricter_rule_is_changed_but_not_unsafe(api):
    api.checkin("crew_1", [_reading("m1", channel="mood", value=5.0)])
    stricter = {
        "patterns": [
            {"id": "low_mood", "tier": "YELLOW",
             "conditions": [{"channel": "mood", "op": "lt", "threshold": 6.0}]}
        ]
    }
    diff = api.post("/earth/rulechange", json={"rules_override": stricter}).json()
    assert (diff["total"], diff["changed"], diff["unsafe"]) == (1, 1, 0)
    assert diff["rows"][0]["new_tier"] == "YELLOW"


def test_rulechange_no_op_override_changes_nothing(api):
    api.checkin("crew_1", _STORM_READINGS)
    diff = api.post("/earth/rulechange", json={"rules_override": {}}).json()
    assert (diff["total"], diff["changed"], diff["unsafe"]) == (1, 0, 0)


def test_rulechange_requires_an_override(api):
    assert api.post("/earth/rulechange", json={}).status_code == 422


# ---------------------------------------------------------------------------
# GET /earth/downlink, POST /earth/downlink/release
# ---------------------------------------------------------------------------

def test_checkin_automatically_queues_downlink_summary_and_anchor(api):
    r1 = api.checkin("crew_1", [_reading("g1")])["record_id"]
    r2 = api.checkin("crew_1", _STORM_READINGS)["record_id"]

    resp = api.get("/earth/downlink")
    assert resp.status_code == 200
    body = resp.json()
    # Urgent (RED) is ordered before routine (GREEN) in pending queue
    assert [s["record_id"] for s in body["pending"]] == [r2, r1]
    assert [a["record_id"] for a in body["anchors"]] == [r1, r2]
    assert body["anchors"][0]["prev_hash"] == GENESIS
    assert body["anchors"][1]["prev_hash"] == body["anchors"][0]["hash"]

    # Release under long delay: RED goes now, GREEN is held until flush
    rel = api.post("/earth/downlink/release", json={"one_way_delay_s": 500.0}).json()
    assert [s["record_id"] for s in rel["sent"]] == [r2]
    assert rel["pending_count"] == 1
    assert rel["latest_anchor"]["record_id"] == r2

    flushed = api.post("/earth/downlink/release", json={"one_way_delay_s": 500.0, "flush": True}).json()
    assert [s["record_id"] for s in flushed["sent"]] == [r1]
    assert flushed["pending_count"] == 0


# ---------------------------------------------------------------------------
# decide(): the Record shape the API hands out
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 11, 14, 8, 0, 0)


def test_decide_stamps_astronaut_id():
    record = decide(readings=[_reading(astronaut_id="crew_7")], baselines={}, rules={}, now=_NOW)
    assert record["astronaut_id"] == "crew_7"


def test_decide_stamps_ts():
    record = decide(readings=[], baselines={}, rules={}, now=_NOW)
    assert record["ts"] == "2026-11-14T08:00:00Z"


def test_decide_normalises_aware_datetimes_to_utc():
    aware = datetime(2026, 11, 14, 8, 0, 0, tzinfo=timezone.utc)
    assert decide([], {}, {}, aware)["ts"] == "2026-11-14T08:00:00Z"


def test_decide_default_astronaut_id_when_no_readings():
    record = decide(readings=[], baselines={}, rules={}, now=_NOW)
    assert record["astronaut_id"] == "crew_1"


def test_decide_output_passes_record_schema():
    record = decide(readings=[_reading()], baselines={}, rules={}, now=_NOW)
    jsonschema.validate(instance=record, schema=_RECORD_SCHEMA)
    jsonschema.validate(instance=record["verdict"], schema=_VERDICT_SCHEMA)
    assert record["prev_hash"] == GENESIS
    assert verify_record(record)


def test_decide_is_no_longer_the_fixture_stub():
    record = decide(readings=[_reading()], baselines={}, rules={}, now=_NOW)
    assert record["id"] != "rec1"
    assert record["hash"] != "placeholder"
    assert [p["pipeline_id"] for p in record["proposals"]] == ["a_statistical", "b_limits"]


def test_decide_rejects_invalid_and_mixed_readings():
    with pytest.raises(ValueError, match="reading.schema.json"):
        decide([{"astronaut_id": "crew_7"}], {}, {}, _NOW)
    with pytest.raises(ValueError, match="several astronauts"):
        decide([_reading("a"), _reading("b", astronaut_id="crew_2")], {}, {}, _NOW)


def test_decide_does_not_mutate_its_inputs():
    readings = [_reading(provenance={"dataset_id": "OSD-569", "field": "x", "timestamp": "t"})]
    snapshot = json.dumps(readings, sort_keys=True)
    record = decide(readings, {}, {}, _NOW)
    assert json.dumps(readings, sort_keys=True) == snapshot
    assert record["readings"] is not readings
    assert record["provenance"] == [readings[0]["provenance"]]


def test_a_crashing_pipeline_becomes_grey_not_an_error(monkeypatch):
    import backend.pipelines.a_statistical.pipeline as pipeline_a

    def crash(readings, context):
        raise RuntimeError("pipeline A killed")

    monkeypatch.setattr(pipeline_a, "run", crash)
    record = decide([_reading()], {}, {}, _NOW)
    assert record["verdict"]["tier"] == "GREY"
    assert record["verdict"]["action"] == "CONTACT_GROUND_URGENT"
    assert record["proposals"][0]["pipeline_id"] == "a_statistical"


def test_no_pipeline_output_at_all_is_grey(monkeypatch):
    monkeypatch.setattr("backend.orchestrator.discover_pipelines", lambda: [])
    record = decide([_reading()], {}, {}, _NOW)
    assert record["verdict"]["tier"] == "GREY"
