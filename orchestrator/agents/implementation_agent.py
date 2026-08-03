"""Implementation stage.

Generates (greenfield) or patches (brownfield/ambiguous) the url_shortener
product source under the Workspace boundary, then statically verifies every
generated Python file compiles before declaring success. All content here is
deterministic/templated -- see docs/DESIGN.md §2/§9 for why -- but every
write still goes through PolicyGuard via the Workspace (path + secret checks).
"""

from __future__ import annotations

import py_compile

from orchestrator.agents.base import ActionResult, Agent
from orchestrator.context import RunContext
from orchestrator.workspace import PolicyViolation, Workspace


class ImplementationAgent(Agent):
    name = "implementation_agent"

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def act(self, context: RunContext) -> ActionResult:
        try:
            if context.scenario_type == "greenfield":
                written = self._build_greenfield(context)
            elif context.scenario_type == "brownfield":
                written = self._build_brownfield(context)
            else:
                written = self._build_ambiguous(context)
        except PolicyViolation as exc:
            context.record_decision(
                stage="implementation", actor=self.name, action="policy_violation", rationale=str(exc)
            )
            return ActionResult(
                success=False, summary=f"Policy guardrail blocked a write: {exc}",
                error=str(exc), failure_class="bug",
            )

        verified, verify_detail = self._verify_syntax(written)
        context.design["implementation_verified"] = verified
        context.design["implementation_verify_detail"] = verify_detail

        context.record_decision(
            stage="implementation",
            actor=self.name,
            action="generate_code",
            rationale=f"Generated/patched {len(written)} file(s) for scenario '{context.scenario_type}'",
            data={"files": written, "verified": verified},
        )

        if not verified:
            return ActionResult(success=False, summary=f"Static verification failed: {verify_detail}",
                                 failure_class="bug")

        return ActionResult(success=True, summary=f"Generated/patched {len(written)} file(s)",
                             data={"files": written})

    def _verify_syntax(self, relpaths: list[str]) -> tuple[bool, str]:
        for rel in relpaths:
            if not rel.endswith(".py"):
                continue
            full = self.workspace.path(rel)
            try:
                py_compile.compile(str(full), doraise=True)
            except py_compile.PyCompileError as exc:
                return False, f"{rel}: {exc}"
        return True, "all generated Python files compiled cleanly"

    # ---- greenfield ------------------------------------------------------

    def _build_greenfield(self, context: RunContext) -> list[str]:
        # Greenfield means "from scratch": wipe any existing product tree
        # first so re-running this scenario on top of an already-evolved
        # (brownfield/ambiguous) codebase can never leave stale files behind
        # that reference symbols the fresh code doesn't have. See
        # docs/TESTING_AND_TRADEOFFS.md.
        self.workspace.reset()
        files = {
            "app/__init__.py": "",
            "app/models.py": _GREENFIELD_MODELS,
            "app/store.py": _GREENFIELD_STORE,
            "app/shortener.py": _SHORTENER_CORE,
            "app/main.py": _GREENFIELD_MAIN,
            "app/web/index.html": _WEB_INDEX_HTML,
            "app/web/app.js": _WEB_APP_JS,
            "app/web/style.css": _WEB_STYLE_CSS,
        }
        return self._write_all(files, context, "generated fresh by the greenfield scenario")

    # ---- brownfield (alias + ttl) -----------------------------------------

    def _build_brownfield(self, context: RunContext) -> list[str]:
        files = {
            "app/models.py": _BROWNFIELD_MODELS,
            "app/store.py": _BROWNFIELD_STORE,
            "app/main.py": _BROWNFIELD_MAIN,
        }
        return self._write_all(files, context, "patched by the brownfield scenario (custom_alias + ttl_seconds)")

    # ---- ambiguous (reliability hardening) --------------------------------

    def _build_ambiguous(self, context: RunContext) -> list[str]:
        files = {
            "app/ratelimit.py": _RATE_LIMITER,
            "app/main.py": _AMBIGUOUS_MAIN,
        }
        return self._write_all(files, context, "patched by the ambiguous scenario (rate limiting/health/errors)")

    def _write_all(self, files: dict[str, str], context: RunContext, summary: str) -> list[str]:
        written = []
        for rel, content in files.items():
            self.workspace.write_file(rel, content, context=context, summary=summary)
            written.append(rel)
        return written


# ===========================================================================
# Generated product source (embedded as static templates -- see class docstring)
# ===========================================================================

_GREENFIELD_MODELS = '''"""Pydantic request/response schemas for the URL shortener API."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ShortenRequest(BaseModel):
    long_url: str = Field(..., description="The URL to shorten. Must start with http:// or https://")

    @field_validator("long_url")
    @classmethod
    def validate_long_url(cls, value: str) -> str:
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("long_url must start with http:// or https://")
        if len(value) > 2048:
            raise ValueError("long_url is too long (max 2048 characters)")
        return value


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str


class AnalyticsResponse(BaseModel):
    short_code: str
    long_url: str
    created_at: str
    last_accessed_at: Optional[str] = None
    clicks: int
    recent_hits: List[str]
'''

_GREENFIELD_STORE = '''"""Thread-safe in-memory store standing in for a database.

Deliberate scope decision (see docs/DESIGN.md): the assignment explicitly
allows an in-memory store for this prototype instead of a real database, so
link data lives only for the lifetime of the process.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LinkRecord:
    long_url: str
    created_at: float
    clicks: int = 0
    last_accessed_at: Optional[float] = None
    recent_hits: List[float] = field(default_factory=list)


class InMemoryStore:
    _MAX_RECENT_HITS = 20

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._links: Dict[str, LinkRecord] = {}
        self._counter = 0

    def next_counter(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def exists(self, code: str) -> bool:
        with self._lock:
            return code in self._links

    def create(self, code: str, long_url: str) -> LinkRecord:
        with self._lock:
            record = LinkRecord(long_url=long_url, created_at=time.time())
            self._links[code] = record
            return record

    def get(self, code: str) -> Optional[LinkRecord]:
        with self._lock:
            return self._links.get(code)

    def record_hit(self, code: str) -> Optional[LinkRecord]:
        with self._lock:
            record = self._links.get(code)
            if record is None:
                return None
            record.clicks += 1
            record.last_accessed_at = time.time()
            record.recent_hits.append(record.last_accessed_at)
            if len(record.recent_hits) > self._MAX_RECENT_HITS:
                record.recent_hits = record.recent_hits[-self._MAX_RECENT_HITS:]
            return record
'''

_SHORTENER_CORE = '''"""Base62 short-code generation.

Codes are derived from an atomic, monotonically increasing counter rather
than random generation + collision retries: this guarantees uniqueness by
construction and keeps generation O(1) with no retry loop.
"""

import string

_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
_BASE = len(_ALPHABET)
_OFFSET = 100_000  # avoids confusingly short codes ("0", "1", ...) for the first links


def encode_base62(number: int) -> str:
    if number == 0:
        return _ALPHABET[0]
    digits = []
    n = number
    while n > 0:
        n, remainder = divmod(n, _BASE)
        digits.append(_ALPHABET[remainder])
    return "".join(reversed(digits))


def generate_short_code(counter_value: int) -> str:
    return encode_base62(counter_value + _OFFSET)
'''

_GREENFIELD_MAIN = '''"""Agentic URL Shortener - FastAPI application.

Generated by the orchestrator's ImplementationAgent (Scenario 1: greenfield).
See docs/DESIGN.md for the orchestration model that produced this file.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.models import AnalyticsResponse, ShortenRequest, ShortenResponse
from app.shortener import generate_short_code
from app.store import InMemoryStore

app = FastAPI(title="Agentic URL Shortener", version="0.1.0")
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
    code = generate_short_code(store.next_counter())
    record = store.create(code, payload.long_url)
    base_url = str(request.base_url).rstrip("/")
    return ShortenResponse(short_code=code, short_url=f"{base_url}/{code}", long_url=record.long_url)


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
    )


@app.get("/{short_code}")
def redirect_short_code(short_code: str):
    record = store.get(short_code)
    if record is None:
        raise HTTPException(status_code=404, detail="short code not found")
    store.record_hit(short_code)
    return RedirectResponse(url=record.long_url, status_code=302)
'''

_BROWNFIELD_MODELS = '''"""Pydantic request/response schemas for the URL shortener API."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

_ALIAS_PATTERN = r"^[A-Za-z0-9_-]{3,32}$"


class ShortenRequest(BaseModel):
    long_url: str = Field(..., description="The URL to shorten. Must start with http:// or https://")
    custom_alias: Optional[str] = Field(
        None, pattern=_ALIAS_PATTERN,
        description="Optional custom short code (3-32 chars: letters, digits, - or _)",
    )
    ttl_seconds: Optional[int] = Field(
        None, gt=0, le=31536000,
        description="Optional time-to-live in seconds after which the link expires",
    )

    @field_validator("long_url")
    @classmethod
    def validate_long_url(cls, value: str) -> str:
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("long_url must start with http:// or https://")
        if len(value) > 2048:
            raise ValueError("long_url is too long (max 2048 characters)")
        return value


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    expires_at: Optional[str] = None


class AnalyticsResponse(BaseModel):
    short_code: str
    long_url: str
    created_at: str
    last_accessed_at: Optional[str] = None
    clicks: int
    recent_hits: List[str]
    expires_at: Optional[str] = None
'''

_BROWNFIELD_STORE = '''"""Thread-safe in-memory store standing in for a database.

Deliberate scope decision (see docs/DESIGN.md): the assignment explicitly
allows an in-memory store for this prototype instead of a real database, so
link data lives only for the lifetime of the process.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LinkRecord:
    long_url: str
    created_at: float
    expires_at: Optional[float] = None
    clicks: int = 0
    last_accessed_at: Optional[float] = None
    recent_hits: List[float] = field(default_factory=list)

    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < time.time()


class InMemoryStore:
    _MAX_RECENT_HITS = 20

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._links: Dict[str, LinkRecord] = {}
        self._counter = 0

    def next_counter(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def exists(self, code: str) -> bool:
        """True if `code` is taken by a live (non-expired) link."""
        with self._lock:
            record = self._links.get(code)
            return record is not None and not record.is_expired()

    def create(self, code: str, long_url: str, ttl_seconds: Optional[int] = None) -> LinkRecord:
        with self._lock:
            now = time.time()
            record = LinkRecord(
                long_url=long_url,
                created_at=now,
                expires_at=(now + ttl_seconds) if ttl_seconds else None,
            )
            self._links[code] = record
            return record

    def get(self, code: str) -> Optional[LinkRecord]:
        """Returns the record only if it exists and is not expired."""
        with self._lock:
            record = self._links.get(code)
            if record is None or record.is_expired():
                return None
            return record

    def get_even_if_expired(self, code: str) -> Optional[LinkRecord]:
        """Used to distinguish 404 (never existed) from 410 (expired)."""
        with self._lock:
            return self._links.get(code)

    def record_hit(self, code: str) -> Optional[LinkRecord]:
        with self._lock:
            record = self._links.get(code)
            if record is None or record.is_expired():
                return None
            record.clicks += 1
            record.last_accessed_at = time.time()
            record.recent_hits.append(record.last_accessed_at)
            if len(record.recent_hits) > self._MAX_RECENT_HITS:
                record.recent_hits = record.recent_hits[-self._MAX_RECENT_HITS:]
            return record
'''

_BROWNFIELD_MAIN = '''"""Agentic URL Shortener - FastAPI application.

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
'''

_RATE_LIMITER = '''"""In-memory per-client rate limiting (token bucket).

Deliberately in-process/in-memory rather than Redis-backed: sufficient for a
single-process prototype and consistent with the no-external-dependency
scoping decision in docs/DESIGN.md. Documented limitation: does not
coordinate across multiple processes/instances -- a real production
deployment behind multiple workers would need a shared store (e.g. Redis).
"""

import threading
import time
from dataclasses import dataclass
from typing import Dict


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = _Bucket(tokens=self.max_requests - 1, last_refill=now)
                return True

            elapsed = now - bucket.last_refill
            refill = (elapsed / self.window_seconds) * self.max_requests
            bucket.tokens = min(self.max_requests, bucket.tokens + refill)
            bucket.last_refill = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True
            return False
'''

_AMBIGUOUS_MAIN = '''"""Agentic URL Shortener - FastAPI application.

Generated/evolved by the orchestrator's ImplementationAgent across three
scenarios: greenfield (base app) -> brownfield (alias + TTL) -> ambiguous
(reliability hardening: rate limiting, health check, structured errors).
See docs/DESIGN.md for the orchestration model and docs/ENGINEERING_SUMMARY.md
for the requirement interpretation behind this file.
"""

from pathlib import Path

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
'''

_WEB_INDEX_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Agentic URL Shortener</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <main class="card">
    <h1>Agentic URL Shortener</h1>
    <p class="subtitle">Generated end-to-end by an agentic SDLC orchestrator.</p>

    <form id="shorten-form">
      <label for="long_url">Long URL</label>
      <input type="url" id="long_url" name="long_url" placeholder="https://example.com/very/long/path" required />

      <label for="custom_alias">Custom alias (optional)</label>
      <input type="text" id="custom_alias" name="custom_alias" placeholder="my-alias" />

      <label for="ttl_seconds">Expires after, seconds (optional)</label>
      <input type="number" id="ttl_seconds" name="ttl_seconds" placeholder="3600" min="1" />

      <button type="submit">Shorten</button>
    </form>

    <div id="result" class="result hidden">
      <p>Short URL: <a id="short-link" href="#" target="_blank" rel="noopener"></a></p>
      <button id="copy-btn" type="button">Copy</button>
    </div>
    <div id="error" class="error hidden"></div>

    <hr />

    <h2>Check analytics</h2>
    <form id="analytics-form">
      <label for="code">Short code</label>
      <input type="text" id="code" name="code" placeholder="e.g. 2p1" required />
      <button type="submit">Look up</button>
    </form>
    <pre id="analytics-result" class="hidden"></pre>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
'''

_WEB_APP_JS = '''const shortenForm = document.getElementById("shorten-form");
const resultBox = document.getElementById("result");
const errorBox = document.getElementById("error");
const shortLink = document.getElementById("short-link");

function extractErrorMessage(data) {
  if (!data) return "Request failed";
  if (data.error && data.error.message) return data.error.message;
  if (data.detail) return data.detail;
  return "Request failed";
}

shortenForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBox.classList.add("hidden");
  resultBox.classList.add("hidden");

  const long_url = document.getElementById("long_url").value;
  const custom_alias = document.getElementById("custom_alias").value || undefined;
  const ttlRaw = document.getElementById("ttl_seconds").value;
  const ttl_seconds = ttlRaw ? Number(ttlRaw) : undefined;

  try {
    const res = await fetch("/api/shorten", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ long_url, custom_alias, ttl_seconds }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(extractErrorMessage(data));
    shortLink.href = data.short_url;
    shortLink.textContent = data.short_url;
    resultBox.classList.remove("hidden");
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove("hidden");
  }
});

const copyBtn = document.getElementById("copy-btn");
if (copyBtn) {
  copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(shortLink.href);
  });
}

const analyticsForm = document.getElementById("analytics-form");
const analyticsResult = document.getElementById("analytics-result");

analyticsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = document.getElementById("code").value;
  try {
    const res = await fetch(`/api/analytics/${code}`);
    const data = await res.json();
    if (!res.ok) throw new Error(extractErrorMessage(data));
    analyticsResult.textContent = JSON.stringify(data, null, 2);
    analyticsResult.classList.remove("hidden");
  } catch (err) {
    analyticsResult.textContent = err.message;
    analyticsResult.classList.remove("hidden");
  }
});
'''

_WEB_STYLE_CSS = '''* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e293b, #0f172a);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #e2e8f0;
}

.card {
  background: #1e293bcc;
  border: 1px solid #334155;
  border-radius: 16px;
  padding: 2.5rem;
  width: 100%;
  max-width: 480px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

h1 {
  margin: 0 0 0.25rem;
  font-size: 1.6rem;
}

.subtitle {
  margin: 0 0 1.5rem;
  color: #94a3b8;
  font-size: 0.85rem;
}

form {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

label {
  font-size: 0.8rem;
  color: #94a3b8;
  margin-top: 0.5rem;
}

input {
  padding: 0.6rem 0.75rem;
  border-radius: 8px;
  border: 1px solid #334155;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 0.95rem;
}

input:focus {
  outline: 2px solid #6366f1;
}

button {
  margin-top: 1rem;
  padding: 0.65rem;
  border: none;
  border-radius: 8px;
  background: #6366f1;
  color: white;
  font-weight: 600;
  cursor: pointer;
  font-size: 0.95rem;
}

button:hover {
  background: #4f46e5;
}

.result, .error {
  margin-top: 1rem;
  padding: 0.75rem;
  border-radius: 8px;
  word-break: break-all;
}

.result {
  background: #064e3b55;
  border: 1px solid #10b981;
}

.result a {
  color: #6ee7b7;
}

.error {
  background: #7f1d1d55;
  border: 1px solid #ef4444;
  color: #fca5a5;
}

.hidden {
  display: none;
}

hr {
  border: none;
  border-top: 1px solid #334155;
  margin: 1.5rem 0;
}

h2 {
  font-size: 1.1rem;
  margin: 0 0 0.75rem;
}

pre {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 0.75rem;
  font-size: 0.8rem;
  overflow-x: auto;
  white-space: pre-wrap;
}
'''
