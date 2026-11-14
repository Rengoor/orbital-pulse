"""Tests for downlink.

Owner: person B
"""

import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.downlink.delay import (
    DISTANCES_KM,
    delay_for,
    one_way_delay_s,
    round_trip_delay_s,
)
from backend.downlink.queue import (
    LONG_DELAY_S,
    DownlinkQueue,
    payload_bytes,
    summarize,
)

_TIERS = ["GREEN", "YELLOW", "RED", "GREY"]
_ACTIONS = {
    "GREEN": "NO_ACTION",
    "YELLOW": "REST_AND_HYDRATE",
    "RED": "ALERT_CMO",
    "GREY": "CONTACT_GROUND_URGENT",
}
_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2, "GREY": 3}

MOON = one_way_delay_s(DISTANCES_KM["moon"])
MARS = one_way_delay_s(DISTANCES_KM["mars_far"])


def _record(i: int, tier: str) -> dict:
    return {
        "id": f"rec{i}",
        "astronaut_id": "crew_1",
        "ts": f"2026-11-14T08:{i:02d}:00Z",
        "prev_hash": "x",
        "readings": [{"id": f"r{i}-{n}", "channel": "heart_rate", "value": 72.0 + n} for n in range(20)],
        "proposals": [{"pipeline_id": "a_statistical", "tier": tier, "reasons": [], "data_fault": False}],
        "verdict": {"tier": tier, "action": _ACTIONS[tier], "reasons": [f"reason {i}"]},
        "hash": f"hash{i}",
        "signature": "sig",
    }


def _queue(tiers, **kwargs) -> DownlinkQueue:
    queue = DownlinkQueue(**kwargs)
    for i, tier in enumerate(tiers):
        queue.enqueue(_record(i, tier))
    return queue


# ---------------------------------------------------------------------------
# delay
# ---------------------------------------------------------------------------

def test_moon_delay_is_about_1_3_seconds():
    assert delay_for("moon") == pytest.approx(1.28, abs=0.05)


def test_mars_delay_spans_roughly_4_to_22_minutes():
    assert 3 * 60 <= delay_for("mars_near") <= 5 * 60
    assert 21 * 60 <= delay_for("mars_far") <= 23 * 60


def test_low_earth_orbit_is_effectively_live():
    assert delay_for("leo") < 0.01


def test_round_trip_is_twice_one_way():
    assert round_trip_delay_s(384_400.0) == pytest.approx(2 * one_way_delay_s(384_400.0))


def test_delay_rejects_nonsense():
    with pytest.raises(ValueError):
        one_way_delay_s(-1)
    with pytest.raises(ValueError, match="unknown location"):
        delay_for("pluto")
    assert one_way_delay_s(0) == 0


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------

def test_summary_carries_the_verdict_and_hash_but_no_raw_readings():
    record = _record(1, "RED")
    summary = summarize(record)
    assert summary == {
        "record_id": "rec1",
        "astronaut_id": "crew_1",
        "ts": "2026-11-14T08:01:00Z",
        "tier": "RED",
        "action": "ALERT_CMO",
        "reasons": ["reason 1"],
        "hash": "hash1",
    }
    assert payload_bytes(summary) < payload_bytes(record) / 4


def test_enqueue_does_not_alias_or_change_the_record():
    record = _record(1, "RED")
    before = copy.deepcopy(record)
    summary = DownlinkQueue().enqueue(record)
    summary["reasons"].append("edited")
    assert record == before


def test_urgent_first_then_oldest_first():
    queue = _queue(["GREEN", "RED", "YELLOW", "GREY", "RED", "GREEN"])
    assert [(s["tier"], s["record_id"]) for s in queue.pending()] == [
        ("GREY", "rec3"), ("RED", "rec1"), ("RED", "rec4"),
        ("YELLOW", "rec2"), ("GREEN", "rec0"), ("GREEN", "rec5"),
    ]


def test_short_delay_sends_everything():
    queue = _queue(["GREEN", "RED", "YELLOW", "GREEN"])
    sent = queue.release(MOON)
    assert [s["tier"] for s in sent] == ["RED", "YELLOW", "GREEN", "GREEN"]
    assert len(queue) == 0
    assert queue.release(MOON) == []


def test_long_delay_holds_routine_but_never_urgent():
    queue = _queue(["GREEN", "RED", "YELLOW", "GREEN", "GREY"])
    sent = queue.release(MARS)
    assert [s["tier"] for s in sent] == ["GREY", "RED", "YELLOW"]
    assert [s["tier"] for s in queue.pending()] == ["GREEN", "GREEN"]

    # Still held on the next pass; released together as the digest.
    assert queue.release(MARS) == []
    assert [s["record_id"] for s in queue.release(MARS, flush=True)] == ["rec0", "rec3"]
    assert len(queue) == 0


def test_delay_exactly_at_the_threshold_is_not_long():
    queue = _queue(["GREEN"])
    assert len(queue.release(LONG_DELAY_S)) == 1


def test_threshold_is_configurable():
    queue = _queue(["GREEN"], long_delay_s=1.0)
    assert queue.release(MOON) == []          # 1.28 s now counts as long
    assert len(queue) == 1


def test_max_items_defers_only_the_least_urgent():
    queue = _queue(["GREEN", "RED", "YELLOW", "GREY"])
    assert [s["tier"] for s in queue.release(MOON, max_items=2)] == ["GREY", "RED"]
    assert [s["tier"] for s in queue.pending()] == ["YELLOW", "GREEN"]
    assert queue.release(MOON, max_items=0) == []
    assert [s["tier"] for s in queue.release(MOON, max_items=10)] == ["YELLOW", "GREEN"]


@given(
    tiers=st.lists(st.sampled_from(_TIERS), max_size=20),
    delay=st.floats(min_value=0, max_value=3000, allow_nan=False),
    max_items=st.none() | st.integers(min_value=0, max_value=25),
    flush=st.booleans(),
)
def test_delay_never_lowers_a_tier_or_loses_a_summary(tiers, delay, max_items, flush):
    queue = _queue(tiers)
    original = {f"rec{i}": (tier, _ACTIONS[tier]) for i, tier in enumerate(tiers)}

    sent = queue.release(delay, max_items=max_items, flush=flush)
    held = queue.pending()

    # Nothing lost, nothing duplicated, nothing invented.
    assert sorted(s["record_id"] for s in sent + held) == sorted(original)
    # Tier and action arrive exactly as decided, however long the delay.
    for summary in sent + held:
        assert (summary["tier"], summary["action"]) == original[summary["record_id"]]
    # Sent in order of urgency.
    assert [_ORDER[s["tier"]] for s in sent] == sorted((_ORDER[s["tier"]] for s in sent), reverse=True)
    # Nothing held back is more urgent than something that was sent.
    if sent and held and max_items is not None:
        assert max(_ORDER[s["tier"]] for s in held) <= min(_ORDER[s["tier"]] for s in sent) or delay > LONG_DELAY_S


@given(tiers=st.lists(st.sampled_from(_TIERS), max_size=20), delay=st.floats(min_value=0, max_value=3000, allow_nan=False))
def test_urgent_summaries_are_never_held_by_delay(tiers, delay):
    queue = _queue(tiers)
    queue.release(delay)
    assert all(s["tier"] == "GREEN" for s in queue.pending())
