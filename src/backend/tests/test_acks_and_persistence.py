"""Acknowledgements (signed, chained, verdict-neutral) and downlink queue persistence."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from backend.api.main import create_app
from backend.downlink.queue import PersistentDownlinkQueue
from backend.records.acknowledge import build_ack
from backend.records.store import RecordStore

_READING = {
    "id": "hr-1",
    "astronaut_id": "crew_1",
    "ts": "2026-11-14T08:00:00Z",
    "channel": "heart_rate",
    "value": 150.0,
    "unit": "bpm",
    "source": "simulated",
    "quality": "ok",
}
_NOW = "2026-11-14T08:00:30Z"


def _request(app, method: str, url: str, **kwargs) -> httpx.Response:
    async def go():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(go())


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "test-ack-signing-key")
    for var in ("RECORDS_PATH", "BASELINES_PATH", "LLM_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    return create_app()


def _checkin(app) -> dict:
    resp = _request(app, "POST", "/checkin", json={
        "astronaut_id": "crew_1", "readings": [_READING], "now": _NOW,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- acknowledgements ---------------------------------------------------------

def test_ack_is_signed_chained_and_changes_nothing(app):
    record_id = _checkin(app)["record_id"]
    before = _request(app, "GET", f"/records/{record_id}").json()

    resp = _request(app, "POST", f"/records/{record_id}/ack",
                    json={"acknowledged_by": "crew_1", "note": "seen on HUD"})
    assert resp.status_code == 200, resp.text
    ack = resp.json()
    assert ack["record_id"] == record_id
    assert ack["acknowledged_by"] == "crew_1"
    assert ack["signature"] and ack["hash"] and ack["prev_hash"] == "GENESIS"

    # The Record under acknowledgement is byte-identical afterwards.
    after = _request(app, "GET", f"/records/{record_id}").json()
    assert after == before

    listed = _request(app, "GET", f"/records/{record_id}/acks").json()
    assert [a["acknowledged_by"] for a in listed["acks"]] == ["crew_1"]
    assert listed["chain"] == {"valid": True, "broken_at": None}


def test_ack_chain_links_and_detects_tampering(app):
    record_id = _checkin(app)["record_id"]
    for who in ("crew_1", "cmo_rahman"):
        _request(app, "POST", f"/records/{record_id}/ack", json={"acknowledged_by": who})

    store = app.state.ctx.store
    acks = store.acks()
    assert acks[1]["prev_hash"] == acks[0]["hash"]

    # An attacker rewriting who acknowledged breaks the chain.
    import json as _json
    doctored = dict(acks[0], acknowledged_by="someone_else")
    with store._conn:
        store._conn.execute("UPDATE acks SET body = ? WHERE seq = 1",
                            (_json.dumps(doctored, sort_keys=True),))
    valid, broken_at = store.verify_acks()
    assert valid is False and broken_at == 0


def test_ack_requires_an_existing_record_and_a_name(app):
    assert _request(app, "POST", "/records/nope/ack",
                    json={"acknowledged_by": "crew_1"}).status_code == 404
    record_id = _checkin(app)["record_id"]
    assert _request(app, "POST", f"/records/{record_id}/ack",
                    json={"acknowledged_by": "   "}).status_code == 422


def test_build_ack_rejects_blank_acknowledger():
    with pytest.raises(ValueError, match="acknowledged_by"):
        build_ack("rec-1", "", signing_key="k")


# -- downlink persistence -------------------------------------------------------

def test_downlink_queue_survives_a_restart(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "test-ack-signing-key")
    monkeypatch.setenv("RECORDS_PATH", str(tmp_path / "records.db"))
    for var in ("BASELINES_PATH", "LLM_ENABLED"):
        monkeypatch.delenv(var, raising=False)

    app1 = create_app()
    record_id = _checkin(app1)["record_id"]
    assert len(app1.state.ctx.queue) == 1
    app1.state.ctx.store.close()

    # A new process: the queued summary and its anchor are still there.
    app2 = create_app()
    pending = _request(app2, "GET", "/earth/downlink").json()
    assert [s["record_id"] for s in pending["pending"]] == [record_id]
    assert len(pending["anchors"]) == 1

    # Release removes it from the store too.
    sent = _request(app2, "POST", "/earth/downlink/release",
                    json={"one_way_delay_s": 0.0}).json()["sent"]
    assert [s["record_id"] for s in sent] == [record_id]
    app2.state.ctx.store.close()

    app3 = create_app()
    assert _request(app3, "GET", "/earth/downlink").json()["pending"] == []
    assert len(_request(app3, "GET", "/earth/downlink").json()["anchors"]) == 1
    app3.state.ctx.store.close()


def test_persistent_queue_resumes_arrival_order(tmp_path: Path):
    db = tmp_path / "q.db"
    record = {
        "id": "rec-a", "astronaut_id": "crew_1", "ts": "2026-11-14T08:00:00Z",
        "verdict": {"tier": "GREEN", "action": "NO_ACTION", "reasons": []},
        "prev_hash": "x", "hash": "h1",
    }
    store = RecordStore(db)
    queue = PersistentDownlinkQueue(store)
    queue.enqueue(record, signing_key="k")
    store.close()

    store2 = RecordStore(db)
    queue2 = PersistentDownlinkQueue(store2)
    assert len(queue2) == 1
    queue2.enqueue({**record, "id": "rec-b", "hash": "h2"}, signing_key="k")
    # Oldest first within a tier: the pre-restart summary keeps its place.
    assert [s["record_id"] for s in queue2.pending()] == ["rec-a", "rec-b"]
    store2.close()
