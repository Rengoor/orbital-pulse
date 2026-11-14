"""Loads sample records and cards from data/fixtures/.

Owner: person C
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def sample_reading() -> dict:
    return _load_fixture("sample_reading.json")


def sample_proposal() -> dict:
    return _load_fixture("sample_proposal.json")


def sample_verdict() -> dict:
    return _load_fixture("sample_verdict.json")


def sample_record() -> dict:
    return _load_fixture("sample_record.json")


def sample_card() -> dict:
    return _load_fixture("sample_card.json")


def sample_review() -> dict:
    return _load_fixture("sample_review.json")
