"""End-to-end tests for the integrated Vitalis UI frontend and AstroHealth backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from backend.api.main import create_app
from frontend import api_client, mock_mode

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "test-vitalis-ui-signing-key")
    for var in ("RECORDS_PATH", "BASELINES_PATH", "LLM_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    app = create_app()

    def request(method: str, url: str, **kwargs) -> httpx.Response:
        async def go():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as c:
                return await c.request(method, url, **kwargs)

        return asyncio.run(go())

    return request


def test_vitalis_ui_static_pages_served_by_backend(client):
    root_resp = client("GET", "/")
    assert root_resp.status_code in (302, 307)
    assert root_resp.headers["location"] == "/ui/index.html"

    for path in (
        "/ui/index.html",
        "/ui/pages/mission-console.html",
        "/ui/pages/station-tablet.html",
        "/ui/pages/helmet-hud.html",
        "/ui/js/vitalis.js",
        "/ui/js/api.js",
        "/ui/js/vendor/react.production.min.js",
        "/ui/css/tokens.css",
        "/ui/css/vitalis.css",
    ):
        resp = client("GET", path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"


def test_vitalis_ui_has_no_external_cdn_or_font_urls():
    """Verify every HTML, CSS, and JS asset runs 100% locally without external CDN calls."""
    for ext in ("*.html", "*.css", "*.js"):
        for file_path in _FRONTEND_DIR.rglob(ext):
            content = file_path.read_text(encoding="utf-8")
            assert "cdn.jsdelivr.net" not in content, f"External CDN left in {file_path}"
            assert "fonts.googleapis.com" not in content, f"External Google Fonts left in {file_path}"


def test_vitalis_crew_checkins_produce_expected_tiers_and_cards(client):
    ts = "2026-11-14T09:12:00Z"
    crew_payloads = {
        "ml": (
            "RED",
            "ALERT_CMO",
            [
                {"id": "ml-hr", "ts": ts, "channel": "heart_rate", "value": 104, "unit": "bpm", "source": "nasa_osdr"},
                {"id": "ml-co2", "ts": ts, "channel": "co2_ppm", "value": 3850, "unit": "ppm", "source": "simulated"},
                {"id": "ml-sleep", "ts": ts, "channel": "sleep_hours", "value": 5.1, "unit": "h", "source": "simulated"},
                {"id": "ml-dose", "ts": ts, "channel": "dose_rate_usv_h", "value": 260.0, "unit": "uSv/h", "source": "nasa_radlab"},
            ],
        ),
        "ao": (
            "GREEN",
            "NO_ACTION",
            [
                {"id": "ao-hr", "ts": ts, "channel": "heart_rate", "value": 64, "unit": "bpm", "source": "nasa_osdr"},
                {"id": "ao-co2", "ts": ts, "channel": "co2_ppm", "value": 2100, "unit": "ppm", "source": "simulated"},
                {"id": "ao-sleep", "ts": ts, "channel": "sleep_hours", "value": 7.4, "unit": "h", "source": "simulated"},
                {"id": "ao-dose", "ts": ts, "channel": "dose_rate_usv_h", "value": 0.38, "unit": "uSv/h", "source": "nasa_radlab"},
                {"id": "ao-glu", "ts": ts, "channel": "glucose", "value": 97, "unit": "mg/dL", "source": "simulated"},
                {"id": "ao-temp", "ts": ts, "channel": "temperature", "value": 36.6, "unit": "C", "source": "simulated"},
            ],
        ),
        "rt": (
            "YELLOW",
            "REST_AND_HYDRATE",
            [
                {"id": "rt-hr", "ts": ts, "channel": "heart_rate", "value": 72, "unit": "bpm", "source": "nasa_osdr"},
                {"id": "rt-sleep", "ts": ts, "channel": "sleep_hours", "value": 5.8, "unit": "h", "source": "simulated"},
                {"id": "rt-glu", "ts": ts, "channel": "glucose", "value": 149, "unit": "mg/dL", "source": "simulated"},
            ],
        ),
        "sr": (
            "GREY",
            "CONTACT_GROUND_URGENT",
            [
                {"id": "sr-hr", "ts": ts, "channel": "heart_rate", "value": 70, "unit": "bpm", "source": "simulated", "quality": "fault"},
                {"id": "sr-co2", "ts": ts, "channel": "co2_ppm", "value": 2600, "unit": "ppm", "source": "simulated"},
            ],
        ),
    }

    # The input gate requires real-data sources to carry provenance (the UI in
    # js/api.js sends it) and judges freshness at the decision time, so the
    # fixed-timestamp readings are decided at that same time.
    for _, _, readings in crew_payloads.values():
        for reading in readings:
            if reading["source"].startswith("nasa_"):
                reading["provenance"] = {"dataset_id": "test-dataset", "field": reading["channel"], "timestamp": ts}

    for astro_id, (expected_tier, expected_action, readings) in crew_payloads.items():
        resp = client("POST", "/checkin", json={"astronaut_id": astro_id, "readings": readings, "now": ts})
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"]["tier"] == expected_tier
        assert body["verdict"]["action"] == expected_action

        card_resp = client("GET", f"/records/{body['record_id']}/card")
        assert card_resp.status_code == 200
        assert card_resp.json()["tier"] == expected_tier

        verify_resp = client("GET", f"/earth/verify/{body['record_id']}")
        assert verify_resp.status_code == 200
        assert verify_resp.json() == {"valid": True, "broken_at": None}

    dl_resp = client("GET", "/earth/downlink")
    assert dl_resp.status_code == 200
    assert len(dl_resp.json()["pending"]) == 4
    assert len(dl_resp.json()["anchors"]) == 4


def test_frontend_python_api_client_local_only_and_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    status = api_client.get_status("ml")
    assert "tier" in status
    assert api_client.list_records()[0]["id"] == mock_mode.sample_record()["id"]

    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("API_URL", "https://external.example.com:8000")
    with pytest.raises(ValueError, match="loopback"):
        api_client.base_url()

    monkeypatch.setenv("API_URL", "http://127.0.0.1:8000")
    assert api_client.base_url() == "http://127.0.0.1:8000"
