# Agentic URL Shortener

Generated/evolved end-to-end by an agentic SDLC orchestrator -- see
`../docs/DESIGN.md` for the orchestration model.

## Overview

A URL shortener: submit a long URL (optionally with a custom alias and/or an
expiration), get a short one back, follow the short link to be redirected,
and check click analytics for any short code.

## API

### `POST /api/shorten`
Body: `{"long_url", "custom_alias"?, "ttl_seconds"?}`
Returns: `{"short_code", "short_url", "long_url", "expires_at"}`

- `custom_alias` (optional): pick your own short code (3-32 chars,
  letters/digits/-/_). Rejected with `409` if already taken.
- `ttl_seconds` (optional): link stops working after this many seconds.

### `GET /{short_code}`
302-redirects to the original long URL and records a click.
`404` if the code never existed, `410 Gone` if it existed but expired.

### `GET /api/analytics/{short_code}`
Returns: `{"short_code", "long_url", "created_at", "last_accessed_at", "clicks", "recent_hits", "expires_at"}`

## Running

See `../docs/SETUP.md`. Quick version:

```
uvicorn app.main:app --reload
```

## Changelog

- **Scenario 2 (brownfield)**: added `custom_alias` and `ttl_seconds` to
  `POST /api/shorten`; added `410 Gone` handling for expired links.
  Existing (no-alias, no-TTL) behavior is unchanged -- covered by a
  regression test (`tests/test_alias_ttl.py::test_existing_behavior_without_alias_or_ttl_is_unchanged`).
- **Scenario 1 (greenfield)**: initial shorten/redirect/analytics API.

## Design notes / trade-offs

- In-memory storage (see Scenario 1 notes) -- still applies.
- Rate limiting and other reliability hardening are deferred to Scenario 3.
