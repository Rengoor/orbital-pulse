"""Thin FastAPI app. Routes live in routes/.

Owner: person A
"""

from fastapi import FastAPI

from backend.api.routes.checkin import router as checkin_router

app = FastAPI(title="AstroHealth Backend")

app.include_router(checkin_router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}
