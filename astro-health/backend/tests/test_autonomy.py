"""Delay-aware autonomy: handoff records say who can decide in time, and never change a verdict."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.api.main import create_app
from backend.records.handoff import assess, link_for, load_autonomy_policy, review_arrival
from backend.records.store import RecordStore


def _record(action: str, tier: str = "RED", extra: list[str] | None = None) -> dict:
    verdict = {"tier": tier, "action": action}
    if extra:
        verdict["additional_actions"] = extra
    return {"id": "rec-1", "astronaut_id": "A1", "ts": "2026-11-14T09:00:00Z", "verdict": verdict}


@pytest.fixture(scope="module")
def policy():
    return load_autonomy_policy()


def test_mode_depends_on_distance_not_on_the_verdict(policy):
    pol, digest = policy
    rec = _record("ALERT_CMO")
    modes = {p: assess(rec, link_for(p), pol, digest)["mode"] for p in ("leo", "moon", "mars_near", "mars_far")}
    assert modes == {"leo": "GROUND_IN_LOOP", "moon": "GROUND_IN_LOOP",
                     "mars_near": "ONBOARD_AUTHORITY", "mars_far": "ONBOARD_AUTHORITY"}


def test_routine_when_no_deadline(policy):
    pol, digest = policy
    assert assess(_record("NO_ACTION", "GREEN"), link_for("mars_far"), pol, digest)["mode"] == "ROUTINE"


def test_grey_hiding_a_known_red_is_judged_by_the_tightest_deadline(policy):
    pol, digest = policy
    # RECHECK alone would leave ground in the loop at Mars-far; the hidden RED's
    # ALERT_CMO deadline must decide instead.
    h = assess(_record("RECHECK_IN_1H", "GREY", extra=["ALERT_CMO"]), link_for("mars_far"), pol, digest)
    assert h["action_deadline_s"] == pol["action_deadline_s"]["ALERT_CMO"]
    assert h["mode"] == "ONBOARD_AUTHORITY"


def test_timings_are_light_time_plus_turnaround(policy):
    pol, digest = policy
    link = link_for(one_way_delay_s=100)
    h = assess(_record("USE_PROTOCOL_CARD"), link, pol, digest)
    assert h["earth_answer_s"] == 200 + pol["ground_turnaround_s"]
    assert h["verdict_reaches_earth_at"] == "2026-11-14T09:01:40Z"
    assert h["policy_hash"] == digest


def test_unknown_action_is_rejected(policy):
    pol, digest = policy
    with pytest.raises(ValueError):
        assess(_record("OPEN_PURGE_VALVE"), link_for("moon"), pol, digest)


def test_bad_links_are_rejected():
    with pytest.raises(ValueError):
        link_for("venus")
    with pytest.raises(ValueError):
        link_for(one_way_delay_s=-1)


def test_review_arrives_after_the_light_delay():
    now = datetime(2026, 11, 14, 9, 0, 0)
    review = {"ts": "2026-11-14T09:00:00Z"}
    assert review_arrival(review, 60, now=now)["arrived"] is False
    assert review_arrival(review, 60, now=now + timedelta(seconds=61))["arrived"] is True


def test_handoff_chain_detects_tampering(policy):
    pol, digest = policy
    store = RecordStore()
    for preset in ("moon", "mars_far"):
        store.add_handoff(assess(_record("ALERT_CMO"), link_for(preset), pol, digest))
    assert store.verify_handoffs() == (True, None)
    # Edit the first entry in place, as someone with database access could.
    first = store.handoffs()[0]
    first["mode"] = "GROUND_IN_LOOP" if first["mode"] != "GROUND_IN_LOOP" else "ONBOARD_AUTHORITY"
    with store._lock, store._conn:
        store._conn.execute("UPDATE handoffs SET body = ? WHERE seq = 1", (__import__("json").dumps(first),))
    assert store.verify_handoffs()[0] is False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "test-autonomy-signing-key")
    for var in ("RECORDS_PATH", "BASELINES_PATH", "LLM_ENABLED", "LINK_PRESET", "LINK_ONE_WAY_S"):
        monkeypatch.delenv(var, raising=False)
    app = create_app()

    def request(method: str, url: str, **kwargs) -> httpx.Response:
        async def go():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as c:
                return await c.request(method, url, **kwargs)

        return asyncio.run(go())

    return request


def _checkin(client, value: float) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reading = {"id": f"hr-{value}-{ts}", "ts": ts, "channel": "heart_rate", "value": value, "unit": "bpm", "source": "simulated"}
    resp = client("POST", "/checkin", json={"astronaut_id": "A1", "readings": [reading]})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_api_end_to_end(client):
    assert client("GET", "/link").json()["link"]["preset"] == "moon"
    near = _checkin(client, 150)
    assert near["autonomy"]["mode"] == "GROUND_IN_LOOP"

    assert client("POST", "/link", json={"preset": "mars_near"}).status_code == 200
    far = _checkin(client, 150)
    assert far["autonomy"]["mode"] == "ONBOARD_AUTHORITY"
    # The delay never changes the verdict.
    assert far["verdict"]["tier"] == near["verdict"]["tier"] == "RED"
    assert far["verdict"]["action"] == near["verdict"]["action"]

    status = client("GET", "/status/A1").json()
    assert status["autonomy"]["mode"] == "ONBOARD_AUTHORITY"
    assert status["ground_review"] is None

    handoff = client("GET", f"/records/{far['record_id']}/handoff").json()
    assert handoff["handoff"]["mode"] == "ONBOARD_AUTHORITY" and handoff["chain"]["valid"] is True

    earth = client("GET", "/earth/handoffs").json()
    assert earth["counts"]["ONBOARD_AUTHORITY"] == 1 and earth["counts"]["GROUND_IN_LOOP"] == 1

    # A ground review is in transit until the light delay has passed.
    client("POST", "/earth/review", json={"record_id": far["record_id"], "outcome": "AGREE"})
    g = client("GET", "/status/A1").json()["ground_review"]
    assert g["outcome"] == "AGREE" and g["arrived"] is False and g["simulated"] is True
    client("POST", "/link", json={"one_way_delay_s": 0})
    assert client("GET", "/status/A1").json()["ground_review"]["arrived"] is True


def test_link_validation(client):
    assert client("POST", "/link", json={}).status_code == 422
    assert client("POST", "/link", json={"preset": "venus"}).status_code == 422
    assert client("POST", "/link", json={"one_way_delay_s": -5}).status_code == 422
