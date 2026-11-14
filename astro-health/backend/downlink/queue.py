"""Priority queue of summaries: urgent first, routine held under long delay. Delay never lowers a tier.

The queue decides only *when* a summary is sent. It carries each verdict's
tier and action through untouched: a long delay can postpone routine traffic,
never soften what a summary says.

Owner: person B
"""

from __future__ import annotations

import json

_TIER_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2, "GREY": 3}

URGENT_TIERS = frozenset({"RED", "GREY"})

# Above this one-way delay a conversation with the ground is no longer live,
# so routine (GREEN) summaries wait to go out together as one digest.
LONG_DELAY_S = 60.0


def summarize(record: dict) -> dict:
    """The small downlink summary of a Record: enough to act on and to verify."""
    verdict = record["verdict"]
    return {
        "record_id": record["id"],
        "astronaut_id": record["astronaut_id"],
        "ts": record["ts"],
        "tier": verdict["tier"],
        "action": verdict["action"],
        "reasons": list(verdict["reasons"]),
        "hash": record["hash"],
    }


def payload_bytes(obj) -> int:
    """Size of *obj* on the wire as compact JSON."""
    return len(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8"))


class DownlinkQueue:
    def __init__(self, long_delay_s: float = LONG_DELAY_S) -> None:
        self.long_delay_s = long_delay_s
        self._pending: list[tuple[int, dict]] = []  # (arrival order, summary)
        self._arrivals = 0

    def __len__(self) -> int:
        return len(self._pending)

    def enqueue(self, record: dict) -> dict:
        """Queue the summary of *record* and return it."""
        summary = summarize(record)
        self._pending.append((self._arrivals, summary))
        self._arrivals += 1
        return summary

    def pending(self) -> list[dict]:
        """Everything still waiting, in send order: worst tier first, then oldest."""
        ordered = sorted(self._pending, key=lambda item: (-_TIER_ORDER[item[1]["tier"]], item[0]))
        return [summary for _, summary in ordered]

    def release(self, one_way_delay_s: float, max_items: int | None = None, flush: bool = False) -> list[dict]:
        """Remove and return the summaries to send now, most urgent first.

        RED and GREY always go. YELLOW goes too. GREEN goes immediately on a
        short link; on a long one (delay above ``long_delay_s``) it is held
        until ``flush=True``, the periodic digest. ``max_items`` caps one pass;
        because of the ordering, a cap can only ever defer the least urgent.
        """
        hold_routine = one_way_delay_s > self.long_delay_s and not flush
        sendable = [s for s in self.pending() if not (hold_routine and s["tier"] == "GREEN")]
        if max_items is not None:
            sendable = sendable[: max(0, max_items)]
        sent_ids = {s["record_id"] for s in sendable}
        self._pending = [item for item in self._pending if item[1]["record_id"] not in sent_ids]
        return sendable
