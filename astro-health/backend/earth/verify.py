"""Verify chain and signatures; detect tampering.

Owner: person B
"""

from __future__ import annotations

from backend.records.chain import first_broken_link, verify_entry


def verify_record(record: dict, signing_key: str | None = None) -> bool:
    """True when one Record's hash and signature match its contents."""
    return verify_entry(record, signing_key)


def verify_chain(
    records: list[dict],
    upto_record_id: str | None = None,
    signing_key: str | None = None,
) -> dict:
    """Walk *records* (oldest first) from genesis.

    Returns ``{"valid": bool, "broken_at": id | None}``, where ``broken_at`` is
    the first Record whose link, hash or signature fails. Everything after a
    broken Record is untrustworthy too, so only the first is reported.
    """
    broken_at = first_broken_link(records, upto_id=upto_record_id, signing_key=signing_key)
    return {"valid": broken_at is None, "broken_at": broken_at}
