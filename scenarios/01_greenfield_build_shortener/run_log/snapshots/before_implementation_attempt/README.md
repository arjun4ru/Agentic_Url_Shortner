# Agentic URL Shortener

Generated end-to-end by an agentic SDLC orchestrator -- see `../docs/DESIGN.md`
for the orchestration model that produced this codebase.

## Overview

A minimal URL shortener: submit a long URL, get a short one back, follow the
short link to be redirected, and check click analytics for any short code.

## API

### `POST /api/shorten`
Body: `{"long_url": "https://example.com/..."}`
Returns: `{"short_code", "short_url", "long_url"}`

### `GET /{short_code}`
302-redirects to the original long URL and records a click. 404 if unknown.

### `GET /api/analytics/{short_code}`
Returns: `{"short_code", "long_url", "created_at", "last_accessed_at", "clicks", "recent_hits"}`

## Running

See `../docs/SETUP.md` for full install/run instructions. Quick version:

```
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000/` for the minimal web UI, or `http://127.0.0.1:8000/docs`
for the interactive API reference.

## Design notes / trade-offs

- **In-memory storage**: link data lives only for the process lifetime. This
  is an explicit, documented scope decision (see `../docs/DESIGN.md`), not an
  oversight -- the assignment allows it for this prototype.
- **Base62 counter-based codes**: guarantees uniqueness by construction, no
  collision-retry loop needed.
- Custom aliases, link expiration, and rate limiting are intentionally out of
  scope for this initial build -- see Scenario 2 and Scenario 3 in
  `../scenarios/`.
