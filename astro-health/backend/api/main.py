"""Thin FastAPI app. Routes live in routes/.

Owner: person A
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.api.routes.checkin import router as checkin_router
from backend.api.routes.earth import router as earth_router
from backend.api.routes.records import router as records_router
from backend.api.routes.status import router as status_router
from backend.api.state import AppState

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="AstroHealth Backend")

    # Loaded once, at startup: rules, baselines, policy whitelist, record store.
    # (Schema validators are compiled when backend.orchestrator is imported.)
    app.state.ctx = AppState.load()

    app.include_router(checkin_router, prefix="/checkin")
    app.include_router(status_router, prefix="/status")
    app.include_router(records_router, prefix="/records")
    app.include_router(earth_router, prefix="/earth")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.exception_handler(Exception)
    async def unexpected_fault(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": type(exc).__name__},
        )

    return app


app = create_app()
