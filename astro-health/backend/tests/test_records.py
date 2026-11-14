"""Tests for records.

Owner: person B
"""

import copy
import hashlib
import hmac
import json
import threading
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.orchestrator import decide
from backend.records.cards import build_card
from backend.records.chain import (
    GENESIS,
    canonical_json,
    compute_hash,
    first_broken_link,
    seal,
    verify_entry,
)
from backend.records.signing import default_signing_key, sign, verify
from backend.records.store import RecordStore

_REPO = Path(__file__).resolve().parents[2]
with open(_REPO / "data" / "schemas" / "card.schema.json") as _f:
    _CARD_SCHEMA = json.load(_f)

_NOW = datetime(2026, 11, 14, 8, 0, 0)


def _reading(rid="r1", astronaut_id="crew_1", channel="heart_rate", value=72.0, unit="bpm", **extra):
    return {
        "id": rid,
        "astronaut_id": astronaut_id,
        "ts": "2026-11-14T08:00:00Z",
        "channel": channel,
        "value": value,
        "unit": unit,
        "source": "simulated",
        **extra,
    }


def _chain(n: int, key: str | None = None) -> list[dict]:
    entries, prev = [], GENESIS
    for i in range(n):
        entry = seal({"id": f"e{i}", "payload": i}, prev, key)
        entries.append(entry)
        prev = entry["hash"]
    return entries


def _record(i: int, prev_hash: str, astronaut_id="crew_1", **reading) -> dict:
    return decide(
        [_reading(f"r{i}", astronaut_id=astronaut_id, **reading)],
        {},
        {},
        _NOW.replace(minute=i),
        prev_hash=prev_hash,
    )


# ---------------------------------------------------------------------------
# signing
# ---------------------------------------------------------------------------

def test_sign_is_hmac_sha256():
    expected = hmac.new(b"k", b"message", hashlib.sha256).hexdigest()
    assert sign("message", "k") == expected
    assert len(expected) == 64


def test_verify_accepts_only_the_right_key_and_message():
    signature = sign("message", "k")
    assert verify("message", signature, "k")
    assert not verify("message", signature, "other-key")
    assert not verify("massage", signature, "k")
    assert not verify("message", signature[:-1] + ("0" if signature[-1] != "0" else "1"), "k")


@pytest.mark.parametrize("bad", [None, 42, b"bytes", ""])
def test_verify_rejects_malformed_signatures_without_raising(bad):
    assert verify("message", bad, "k") is False


def test_default_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "from-env")
    assert default_signing_key() == "from-env"
    assert sign("m") == sign("m", "from-env")
    monkeypatch.delenv("SIGNING_KEY")
    assert sign("m") == sign("m", "demo-only-change-me")


# ---------------------------------------------------------------------------
# chain
# ---------------------------------------------------------------------------

def test_canonical_json_ignores_key_order_and_whitespace():
    assert canonical_json({"b": 1, "a": [1, 2]}) == canonical_json({"a": [1, 2], "b": 1}) == '{"a":[1,2],"b":1}'


def test_compute_hash_excludes_hash_and_signature_only():
    entry = {"id": "e", "payload": 1, "prev_hash": GENESIS}
    base = compute_hash(entry)
    assert compute_hash({**entry, "hash": "x", "signature": "y"}) == base
    assert compute_hash({**entry, "payload": 2}) != base
    assert compute_hash({**entry, "prev_hash": "other"}) != base


def test_seal_links_hashes_signs_and_leaves_the_input_alone():
    entry = {"id": "e0", "payload": 1}
    sealed = seal(entry, "abc", "k")
    assert entry == {"id": "e0", "payload": 1}
    assert sealed["prev_hash"] == "abc"
    assert sealed["hash"] == compute_hash(sealed)
    assert sealed["signature"] == sign(sealed["hash"], "k")
    assert verify_entry(sealed, "k")
    assert not verify_entry(sealed, "wrong-key")


def test_intact_chain_has_no_broken_link():
    assert first_broken_link([]) is None
    assert first_broken_link(_chain(5)) is None


@pytest.mark.parametrize("position", [0, 2, 4])
def test_editing_any_entry_is_found_at_that_entry(position):
    chain = _chain(5)
    chain[position]["payload"] = "edited"
    assert first_broken_link(chain) == f"e{position}"


def test_rehashing_an_edit_without_the_key_is_still_found():
    chain = _chain(3, key="real-key")
    chain[1]["payload"] = "edited"
    chain[1]["hash"] = compute_hash(chain[1])
    assert first_broken_link(chain, signing_key="real-key") == "e1"


def test_a_full_forgery_with_the_key_breaks_the_next_link():
    """Even with the key, rewriting one entry changes its hash, orphaning its successor."""
    chain = _chain(3, key="k")
    chain[1] = seal({"id": "e1", "payload": "edited"}, chain[0]["hash"], "k")
    assert first_broken_link(chain, signing_key="k") == "e2"


def test_removed_reordered_and_inserted_entries_are_found():
    chain = _chain(4)
    assert first_broken_link(chain[:1] + chain[2:]) == "e2"            # e1 removed
    assert first_broken_link([chain[1], chain[0]] + chain[2:]) == "e1"  # swapped
    assert first_broken_link(chain[1:]) == "e1"                         # genesis removed
    rogue = seal({"id": "rogue"}, chain[1]["hash"])
    assert first_broken_link(chain[:2] + [rogue] + chain[2:]) == "e2"


def test_upto_id_stops_the_walk():
    chain = _chain(4)
    chain[3]["payload"] = "edited"
    assert first_broken_link(chain, upto_id="e2") is None
    assert first_broken_link(chain, upto_id="e3") == "e3"


@given(
    payloads=st.lists(st.integers(), min_size=1, max_size=8),
    data=st.data(),
)
def test_any_single_field_edit_is_detected(payloads, data):
    chain, prev = [], GENESIS
    for i, payload in enumerate(payloads):
        chain.append(seal({"id": f"e{i}", "payload": payload}, prev))
        prev = chain[-1]["hash"]
    assert first_broken_link(chain) is None

    position = data.draw(st.integers(min_value=0, max_value=len(chain) - 1))
    field = data.draw(st.sampled_from(["payload", "prev_hash", "hash", "signature"]))
    chain[position][field] = "tampered"
    assert first_broken_link(chain) == f"e{position}"


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    s = RecordStore()
    yield s
    s.close()


def _fill(store, n=3, astronauts=("crew_1",)) -> list[dict]:
    return [
        store.append_with(lambda prev, i=i: _record(i, prev, astronaut_id=astronauts[i % len(astronauts)]))
        for i in range(n)
    ]


def test_empty_store(store):
    assert store.all() == []
    assert store.list() == []
    assert store.get("nope") is None
    assert store.latest("crew_1") is None
    assert store.verify_chain() == (True, None)
    assert store.reviews() == []
    assert store.verify_reviews() == (True, None)


def test_append_links_each_record_to_the_previous_hash(store):
    records = _fill(store, 4)
    assert records[0]["prev_hash"] == GENESIS
    for previous, current in zip(records, records[1:]):
        assert current["prev_hash"] == previous["hash"]
    assert store.all() == records
    assert store.verify_chain() == (True, None)


def test_reads(store):
    records = _fill(store, 5, astronauts=("crew_1", "crew_2"))
    assert store.get(records[2]["id"]) == records[2]
    assert store.latest("crew_1") == records[4]
    assert store.latest("crew_2") == records[3]
    assert store.list() == records[::-1]
    assert store.list(astronaut_id="crew_2") == [records[3], records[1]]
    assert store.list(limit=2) == [records[4], records[3]]
    assert store.list(astronaut_id="nobody") == []


def test_returned_records_are_copies(store):
    record = _fill(store, 1)[0]
    store.get(record["id"])["verdict"]["tier"] = "GREEN-ish"
    assert store.get(record["id"]) == record


def test_duplicate_record_id_is_refused(store):
    record = _fill(store, 1)[0]
    with pytest.raises(Exception):
        store.append_with(lambda prev: record)
    assert len(store.all()) == 1


def test_a_failed_build_appends_nothing(store):
    _fill(store, 1)

    def boom(prev_hash):
        raise RuntimeError("decide failed")

    with pytest.raises(RuntimeError):
        store.append_with(boom)
    assert len(store.all()) == 1
    assert store.verify_chain() == (True, None)


def test_store_offers_no_way_to_update_or_delete():
    # Records, reviews, acks and handoffs are append-only chains with no update or
    # delete. The downlink_* methods manage the transient send queue, whose
    # rows are summaries removed when sent; the chained originals stay.
    public = {name for name in dir(RecordStore) if not name.startswith("_")}
    assert public == {
        "add_ack", "add_handoff", "add_review", "acks", "all", "append_with", "close",
        "downlink_add", "downlink_load", "downlink_remove", "get", "handoffs", "latest",
        "latest_handoff", "latest_review_for", "list", "reviews", "verify_acks",
        "verify_chain", "verify_handoffs", "verify_reviews",
    }
    chain_methods = public - {"downlink_add", "downlink_load", "downlink_remove", "close"}
    assert not any(m.startswith(("update", "delete", "remove")) for m in chain_methods)


def test_records_survive_reopening_the_file(tmp_path):
    path = tmp_path / "nested" / "records.db"
    first = RecordStore(path)
    records = _fill(first, 3)
    first.close()

    second = RecordStore(path)
    assert second.all() == records
    more = second.append_with(lambda prev: _record(9, prev))
    assert more["prev_hash"] == records[-1]["hash"]
    assert second.verify_chain() == (True, None)
    second.close()


def test_tampering_with_the_database_file_is_detected(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(path)
    records = _fill(store, 3)
    victim = copy.deepcopy(records[1])
    victim["verdict"]["reasons"] = ["nothing to see"]
    with store._conn:
        store._conn.execute("UPDATE records SET body = ? WHERE id = ?", (json.dumps(victim), victim["id"]))

    assert store.verify_chain() == (False, records[1]["id"])
    assert store.verify_chain(upto_record_id=records[0]["id"]) == (True, None)

    with store._conn:
        store._conn.execute("DELETE FROM records WHERE id = ?", (records[1]["id"],))
    assert store.verify_chain() == (False, records[2]["id"])
    store.close()


def test_concurrent_appends_form_one_unbroken_chain(store):
    def worker(offset):
        for i in range(10):
            store.append_with(lambda prev, n=offset * 100 + i: _record(n % 60, prev, astronaut_id=f"crew_{offset}_{i}"))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.all()) == 40
    assert store.verify_chain() == (True, None)
    assert len({r["prev_hash"] for r in store.all()}) == 40  # nobody shares a parent


def test_reviews_form_their_own_chain_and_leave_records_alone(store):
    record = _fill(store, 1)[0]
    base = {"record_id": record["id"], "reviewer": "sim", "outcome": "AGREE", "simulated": True, "ts": "t"}
    first = store.add_review({**base, "note": "one"})
    second = store.add_review({**base, "note": "two", "outcome": "FOLLOW_UP"})

    assert first["prev_hash"] == GENESIS
    assert second["prev_hash"] == first["hash"]
    assert store.reviews() == [first, second]
    assert store.reviews(record["id"]) == [first, second]
    assert store.reviews("other") == []
    assert store.verify_reviews() == (True, None)
    assert store.all() == [record]
    assert store.verify_chain() == (True, None)

    edited = {**first, "outcome": "DISAGREE"}
    with store._conn:
        store._conn.execute("UPDATE reviews SET body = ? WHERE seq = 1", (json.dumps(edited),))
    assert store.verify_reviews() == (False, 0)


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------

def test_green_card():
    card = build_card(_record(0, GENESIS))
    jsonschema.validate(card, _CARD_SCHEMA)
    assert card["tier"] == "GREEN"
    assert card["action"] == "NO_ACTION"
    assert card["headline"] == "All signals nominal"
    assert card["simulated_labels"] == ["heart_rate: simulated"]
    assert card["provenance"] == []


def test_alert_card_leads_with_the_first_reason():
    record = _record(0, GENESIS, value=150.0)
    card = build_card(record)
    jsonschema.validate(card, _CARD_SCHEMA)
    assert (card["tier"], card["action"]) == ("RED", "ALERT_CMO")
    assert card["record_id"] == record["id"]
    assert card["headline"].startswith("Needs the crew medical officer: ")
    assert record["verdict"]["reasons"][0] in card["headline"]


def test_card_separates_real_provenance_from_simulated_inputs():
    provenance = {"dataset_id": "OSD-569", "field": "crp", "timestamp": "2021-06-01T00:00:00Z"}
    record = decide(
        [
            _reading("a", channel="blood_analyte", unit="mg/L", value=1.0, source="nasa_osdr", provenance=provenance),
            _reading("b", channel="blood_analyte", unit="mg/L", value=1.1, source="nasa_osdr", provenance=provenance),
            _reading("c", channel="mood", unit="score_1_10", value=7.0),
        ],
        {},
        {},
        _NOW,
    )
    card = build_card(record)
    assert card["provenance"] == [provenance]           # de-duplicated
    assert card["simulated_labels"] == ["mood: simulated"]  # the real channel is not labelled simulated
