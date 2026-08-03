"""Agentic URL Shortener - FastAPI application.

Generated/evolved by the orchestrator's ImplementationAgent.
Scenario 1 (greenfield) created the base app; Scenario 2 (brownfield) added
custom_alias + ttl_seconds support. See docs/DESIGN.md.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.models import AnalyticsResponse, ShortenRequest, ShortenResponse
from app.shortener import generate_short_code
from app.store import InMemoryStore

app = FastAPI(title="Agentic URL Shortener", version="0.2.0")
store = InMemoryStore()

WEB_DIR = Path(__file__).parent / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Agentic URL Shortener API. See /docs for the API reference."}


@app.post("/api/shorten", response_model=ShortenResponse)
def shorten(payload: ShortenRequest, request: Request):
    if payload.custom_alias:
        if store.exists(payload.custom_alias):
            raise HTTPException(status_code=409, detail=f"alias '{payload.custom_alias}' is already taken")
        code = payload.custom_alias
    else:
        code = generate_short_code(store.next_counter())

    record = store.create(code, payload.long_url, ttl_seconds=payload.ttl_seconds)
    base_url = str(request.base_url).rstrip("/")
    expires_at = str(record.expires_at) if record.expires_at else None
    return ShortenResponse(
        short_code=code, short_url=f"{base_url}/{code}", long_url=record.long_url, expires_at=expires_at,
    )


@app.get("/api/analytics/{short_code}", response_model=AnalyticsResponse)
def analytics(short_code: str):
    record = store.get(short_code)
    if record is None:
        raise HTTPException(status_code=404, detail="short code not found")
    return AnalyticsResponse(
        short_code=short_code,
        long_url=record.long_url,
        created_at=str(record.created_at),
        last_accessed_at=str(record.last_accessed_at) if record.last_accessed_at else None,
        clicks=record.clicks,
        recent_hits=[str(h) for h in record.recent_hits],
        expires_at=str(record.expires_at) if record.expires_at else None,
    )


@app.get("/{short_code}")
def redirect_short_code(short_code: str):
    existing = store.get_even_if_expired(short_code)
    if existing is None:
        raise HTTPException(status_code=404, detail="short code not found")
    if existing.is_expired():
        raise HTTPException(status_code=410, detail="this link has expired")
    store.record_hit(short_code)
    return RedirectResponse(url=existing.long_url, status_code=302)
