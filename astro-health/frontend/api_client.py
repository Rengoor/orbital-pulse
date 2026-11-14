"""All HTTP calls to the backend in one place; falls back to fixtures when MOCK_MODE=1.

Strictly local-only: only loopback URLs (127.0.0.1, localhost, ::1) are allowed.

Owner: person C
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

from frontend import mock_mode

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_API_URL = "http://127.0.0.1:8000"


def _require_loopback(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"Frontend API URL must use a local loopback host (127.0.0.1, localhost, ::1); got {url!r}"
        )
    return url.rstrip("/")


def is_mock_mode() -> bool:
    return os.environ.get("MOCK_MODE", "0") == "1"


def base_url() -> str:
    return _require_loopback(os.environ.get("API_URL", DEFAULT_API_URL))


def _client() -> httpx.Client:
    return httpx.Client(base_url=base_url(), timeout=5.0, trust_env=False)


def get_status(astronaut_id: str) -> dict:
    if is_mock_mode():
        v = mock_mode.sample_verdict()
        return {
            "tier": v.get("tier", "GREEN"),
            "action": v.get("action", "NO_ACTION"),
            "reasons": v.get("reasons", []),
            "record_id": mock_mode.sample_record().get("id", "rec1"),
        }
    with _client() as client:
        resp = client.get(f"/status/{astronaut_id}")
        resp.raise_for_status()
        return resp.json()


def list_records(astronaut_id: str | None = None, limit: int = 50) -> list[dict]:
    if is_mock_mode():
        return [mock_mode.sample_record()]
    params: dict[str, Any] = {"limit": limit}
    if astronaut_id:
        params["astronaut_id"] = astronaut_id
    with _client() as client:
        resp = client.get("/records", params=params)
        resp.raise_for_status()
        return resp.json()


def get_card(record_id: str) -> dict:
    if is_mock_mode():
        return mock_mode.sample_card()
    with _client() as client:
        resp = client.get(f"/records/{record_id}/card")
        resp.raise_for_status()
        return resp.json()


def post_checkin(astronaut_id: str, readings: list[dict]) -> dict:
    if is_mock_mode():
        return {"record_id": "rec1", "verdict": mock_mode.sample_verdict()}
    with _client() as client:
        resp = client.post("/checkin", json={"astronaut_id": astronaut_id, "readings": readings})
        resp.raise_for_status()
        return resp.json()
