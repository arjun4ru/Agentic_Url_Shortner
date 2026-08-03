# Agentic URL Shortener

Generated/evolved end-to-end by an agentic SDLC orchestrator -- see
`../docs/DESIGN.md` for the orchestration model and
`../docs/ENGINEERING_SUMMARY.md` for how the ambiguous "make it more
reliable" requirement behind this scenario was interpreted and approved.

## Overview

A URL shortener: submit a long URL (optionally with a custom alias and/or an
expiration), get a short one back, follow the short link to be redirected,
check click analytics, and rely on basic production-readiness guardrails
(rate limiting, input validation, health checks, structured errors).

## API

### `POST /api/shorten`
Body: `{"long_url", "custom_alias"?, "ttl_seconds"?}`
Returns: `{"short_code", "short_url", "long_url", "expires_at"}`
Rate-limited per client IP (10 requests / 60s by default) -- `429` if exceeded.
Malformed/invalid `long_url` returns `422` with a structured error body.

### `GET /{short_code}`
302-redirect + click tracking. `404` if unknown, `410 Gone` if expired.

### `GET /api/analytics/{short_code}`
Returns: `{"short_code", "long_url", "created_at", "last_accessed_at", "clicks", "recent_hits", "expires_at"}`

### `GET /api/health`
Liveness probe. Returns `{"status": "ok"}`.

### Error response shape
All errors return both a `detail` string (backward-compatible with Scenario
1/2 clients) and a structured `error: {code, message}` object:

```json
{"detail": "short code not found", "error": {"code": "http_error", "message": "short code not found"}}
```

## Running

See `../docs/SETUP.md`. Quick version:

```
uvicorn app.main:app --reload
```

## Changelog

- **Scenario 3 (ambiguous)**: the requirement "make it more reliable" was
  flagged as ambiguous (see Requirements stage decision lineage), interpreted
  as rate limiting + input validation + health check + structured errors,
  and implemented only after that interpretation was approved at a human
  checkpoint. Existing Scenario 1/2 behavior and error `detail` strings are
  preserved -- verified by `tests/test_reliability.py` and the full
  regression suite.
- **Scenario 2 (brownfield)**: added `custom_alias` and `ttl_seconds`.
- **Scenario 1 (greenfield)**: initial shorten/redirect/analytics API.

## Design notes / trade-offs

- In-memory storage (see Scenario 1 notes) -- still applies.
- Rate limiting is per-process/in-memory, not shared across multiple worker
  processes or instances -- documented limitation, not a hidden gap.
