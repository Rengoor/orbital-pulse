"""End-to-end tests for the integrated Vitalis UI frontend and AstroHealth backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from backend.api.main import create_app

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
        "/ui/hud/index.html",
        "/ui/tablet/monitor.html",
        "/ui/earth/index.html",
        "/ui/js/vitalis.js",
        "/ui/js/api.js",
        "/ui/js/vendor/react.production.min.js",
        "/ui/css/tokens.css",
        "/ui/css/vitalis.css",
    ):
        resp = client("GET", path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"


def test_three_views_each_have_their_own_directory():
    for view in ("hud", "tablet", "earth"):
        assert (_FRONTEND_DIR / view / "README.md").is_file(), f"missing {view}/"
    start = (_FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for link in ("hud/index.html", "tablet/monitor.html", "earth/index.html"):
        assert (_FRONTEND_DIR / link).is_file()
        assert f'href="{link}"' in start


def test_hud_is_display_only():
    """The HUD reads the backend verdict and never labels its own input as NASA data."""
    page = (_FRONTEND_DIR / "hud" / "index.html").read_text(encoding="utf-8")
    script = page[page.index("<body>"):]
    assert "API.status(" in script and "API.record(" in script
    assert "source: 'simulated'" in script
    for forbidden in ("nasa_osdr", "nasa_radlab", "nasa_donki", "NASA-" + "compliant", "localStorage"):
        assert forbidden not in script, forbidden
    # Action wording comes from Vitalis.ACTIONS, not free text in the page.
    assert "V.ACTIONS[" in script
    assert (_FRONTEND_DIR / "hud" / "README.md").is_file()


_MEDIAPIPE_SHA256 = {
    "vision_bundle.mjs": "870da5cfc43bfcf2a8b0f14e8152dae8c7e701722e1191b0e592b94b81b4127a",
    "wasm/vision_wasm_internal.js": "85c1a342be70427987f900969a5f26e17557351111364e6585e97fb03e93e108",
    "wasm/vision_wasm_internal.wasm": "bcc13df22d3d69ec8cbe8e280989356d844ae00f4523eb82072d2484f44134dc",
    "gesture_recognizer.task": "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482",
}


def test_hud_gestures_are_local_and_layout_only():
    """Camera gestures load only vendored files (pinned by hash) and only change layout."""
    import hashlib
    import re

    vendor = _FRONTEND_DIR / "js" / "vendor" / "mediapipe"
    for name, digest in _MEDIAPIPE_SHA256.items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest, name

    module = (_FRONTEND_DIR / "hud" / "gestures.mjs").read_text(encoding="utf-8")
    assert not re.search(r"https?://", module), "gestures.mjs must not load anything from the network"
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "API."):
        assert forbidden not in module, forbidden

    page = (_FRONTEND_DIR / "hud" / "index.html").read_text(encoding="utf-8")
    assert "import('./gestures.mjs')" in page
    # A change of status always restores the normal layout.
    assert "layout[1]('normal');" in page
    # Acknowledge goes to the backend's signed chain; the test hook is opt-in only.
    assert "API.ack(" in page
    assert "params.get('gesture_test') === '1'" in page


def test_hud_gesture_files_served(client):
    for path in ("/ui/hud/gestures.mjs", "/ui/js/vendor/mediapipe/vision_bundle.mjs",
                 "/ui/js/vendor/mediapipe/wasm/vision_wasm_internal.wasm"):
        resp = client("GET", path)
        assert resp.status_code == 200, path
    assert client("GET", "/ui/js/vendor/mediapipe/wasm/vision_wasm_internal.wasm").headers["content-type"] == "application/wasm"


def test_hud_status_contract(client):
    """Every field the HUD reads is present in /status and /records/{id}."""
    assert client("GET", "/status/eva_hud_test").status_code == 404  # HUD shows "No data", no action

    ts = "2026-11-14T09:12:00Z"
    readings = [
        {"id": "h1", "ts": ts, "channel": "heart_rate", "value": 150, "unit": "bpm", "source": "simulated", "quality": "ok"},
        {"id": "h2", "ts": ts, "channel": "dose_rate_usv_h", "value": 0.6, "unit": "uSv/h", "source": "simulated", "quality": "ok"},
    ]
    client("POST", "/checkin", json={"astronaut_id": "eva_hud_test", "readings": readings, "now": ts})
    status = client("GET", "/status/eva_hud_test").json()
    for key in ("tier", "action", "additional_actions", "disagreement_status", "record_id", "ts"):
        assert key in status
    record = client("GET", f"/records/{status['record_id']}").json()
    trace = record["verdict"]["decision_trace"]
    # Rule ids are "<channel>.<bound>"; the HUD highlights only the channels they name.
    assert trace["triggered_rules"] == ["heart_rate.red_high"]
    assert {e["reading_id"]: e["status"] for e in record["integrity"]["readings"]} == {"h1": "valid", "h2": "valid"}
    assert "failsafe" not in record["verdict"] or record["verdict"]["failsafe"] is False


def test_earth_base_review_log(client):
    assert client("GET", "/earth/reviews").json() == {"reviews": [], "chain": {"valid": True, "broken_at": None}}

    ts = "2026-11-14T09:12:00Z"
    reading = {"id": "r1", "ts": ts, "channel": "heart_rate", "value": 150, "unit": "bpm", "source": "simulated"}
    record_id = client("POST", "/checkin", json={"astronaut_id": "ml", "readings": [reading], "now": ts}).json()["record_id"]
    client("POST", "/earth/review", json={"record_id": record_id, "cmo_note": "seen", "outcome": "AGREE"})
    client("POST", "/earth/review", json={"record_id": record_id, "cmo_note": "", "outcome": "FOLLOW_UP"})

    log = client("GET", "/earth/reviews").json()
    assert [r["outcome"] for r in log["reviews"]] == ["AGREE", "FOLLOW_UP"]
    assert log["chain"] == {"valid": True, "broken_at": None}
    assert client("GET", "/earth/reviews", params={"record_id": "other"}).json()["reviews"] == []


def test_api_js_ships_no_demo_data():
    """api.js must not bring back the helpers that faked data.

    An earlier version labelled simulated values as NASA data with fabricated
    provenance (buildReadingsForCrew / syncCrewWithBackend). This pins their removal.
    """
    api_js = (_FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for forbidden in (
        "buildReadingsForCrew",   # labelled simulated readings as nasa_* with made-up provenance
        "syncCrewWithBackend",    # merged scripted crew with live records and seeded the store
        "checkinCrewMember",
        "nasa_osdr",
        "nasa_radlab",
    ):
        assert forbidden not in api_js, f"api.js still contains {forbidden}"


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

