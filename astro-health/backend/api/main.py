"""Thin FastAPI app. Routes live in routes/.

Owner: person A
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes.checkin import router as checkin_router
from backend.api.routes.earth import router as earth_router
from backend.api.routes.nasa import router as nasa_router
from backend.api.routes.records import router as records_router
from backend.api.routes.status import router as status_router
from backend.api.state import AppState
from backend.records.signing import is_demo_key, key_id

logger = logging.getLogger(__name__)
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="AstroHealth Backend")

    # Local-only CORS: permit local UI servers (127.0.0.1 / localhost) and file:// origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$|^null$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Loaded once, at startup: rules, baselines, policy whitelist, record store.
    # (Schema validators are compiled when backend.orchestrator is imported.)
    app.state.ctx = AppState.load()
    if is_demo_key():
        logger.warning(
            "Signing with the built-in DEMO key (%s). Records are tamper-evident only against "
            "someone who does not know it. Set SIGNING_KEY for anything but a demonstration.",
            key_id(),
        )

    app.include_router(checkin_router, prefix="/checkin")
    app.include_router(status_router, prefix="/status")
    app.include_router(records_router, prefix="/records")
    app.include_router(earth_router, prefix="/earth")
    app.include_router(nasa_router, prefix="/nasa")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "signing_key": {"key_id": key_id(), "demo_key": is_demo_key()}}

    @app.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/index.html")

    if (_FRONTEND_DIR / "index.html").exists():
        app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="vitalis_ui")

    @app.exception_handler(Exception)
    async def unexpected_fault(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": type(exc).__name__},
        )

    return app


app = create_app() if os.environ.get("SIGNING_KEY") and os.environ.get("SIGNING_KEY") != "demo-only-change-me" else None
