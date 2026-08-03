"""Agentic URL Shortener - FastAPI application.

Generated/evolved by the orchestrator's ImplementationAgent across three
scenarios: greenfield (base app) -> brownfield (alias + TTL) -> ambiguous
(reliability hardening: rate limiting, health check, structured errors).
See docs/DESIGN.md for the orchestration model and docs/ENGINEERING_SUMMARY.md
for the requirement interpretation behind this file.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.models import AnalyticsResponse, ShortenRequest, ShortenResponse
from app.ratelimit import RateLimiter
from app.shortener import generate_short_code
from app.store import InMemoryStore

app = FastAPI(title="Agentic URL Shortener", version="0.3.0")
store = InMemoryStore()
limiter = RateLimiter(max_requests=10, window_seconds=60.0)

WEB_DIR = Path(__file__).parent / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _human_time(ts: Optional[float]) -> Optional[str]:
    """Render an internal epoch timestamp (float seconds, used for TTL/ordering
    math in app/store.py) as a readable, unambiguous string for API consumers.
    Always UTC (never local time) so it means the same thing to every client
    regardless of where the server or the person reading it is located."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _error_body(code: str, message: str) -> dict:
    # Keeps the original "detail" key for backward compatibility with
    # Scenario 1/2 API consumers, while adding a structured "error" envelope
    # -- a non-breaking API evolution rather than a breaking change.
    return {"detail": message, "error": {"code": code, "message": message}}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content=_error_body("validation_error", str(exc)))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=_error_body("http_error", str(exc.detail)))


@app.get("/")
def index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Agentic URL Shortener API. See /docs for the API reference."}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/shorten", response_model=ShortenResponse)
def shorten(payload: ShortenRequest, request: Request):
    client_key = request.client.host if request.client else "unknown"
    if not limiter.allow(client_key):
        raise HTTPException(status_code=429, detail="rate limit exceeded, please slow down")

    if payload.custom_alias:
        if store.exists(payload.custom_alias):
            raise HTTPException(status_code=409, detail=f"alias '{payload.custom_alias}' is already taken")
        code = payload.custom_alias
    else:
        code = generate_short_code(store.next_counter())

    record = store.create(code, payload.long_url, ttl_seconds=payload.ttl_seconds)
    base_url = str(request.base_url).rstrip("/")
    return ShortenResponse(
        short_code=code, short_url=f"{base_url}/{code}", long_url=record.long_url,
        expires_at=_human_time(record.expires_at),
    )


@app.get("/api/analytics/{short_code}", response_model=AnalyticsResponse)
def analytics(short_code: str):
    record = store.get(short_code)
    if record is None:
        raise HTTPException(status_code=404, detail="short code not found")
    return AnalyticsResponse(
        short_code=short_code,
        long_url=record.long_url,
        created_at=_human_time(record.created_at),
        last_accessed_at=_human_time(record.last_accessed_at),
        clicks=record.clicks,
        recent_hits=[_human_time(h) for h in record.recent_hits],
        expires_at=_human_time(record.expires_at),
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
