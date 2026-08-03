# Final Engineering Summary

## Plan and rationale

The assignment asks for two things: a URL shortener product, and (the real
differentiator) an agentic orchestration layer that drives that product's
full SDLC with governance -- dependency graphs, gates, approvals, retries,
rollback, audit, metrics, and re-planning.

The plan (full detail in `docs/DESIGN.md`) was to build both as one system:
a hand-rolled orchestration engine (`orchestrator/`, stdlib only) that
executes a fixed 6-stage graph (Requirements -> Design -> Implementation ->
{Testing, Documentation} -> Release Readiness), driven by deterministic
rule/template-based agents, and to prove it works by pointing it at three
different kinds of requirements against a real FastAPI product
(`url_shortener/`) rather than a toy example.

Key decisions and why (see `docs/DESIGN.md` §2 and §9 for the full
back-and-forth, including why LangGraph was considered and not used, and
whether a framework is "the right way" to build this):

- **Hand-rolled engine over a framework** -- this assignment evaluates
  orchestration *design*, and a framework would hide the exact mechanics
  being graded (retry/rollback/audit/MTTR are hand-built regardless of what
  sits underneath).
- **Deterministic agents over live LLM calls** -- zero API keys/cost,
  instant, 100% reproducible, with a pluggable `Agent` interface so a real
  LLM could be substituted later.
- **In-memory storage, no DB/Redis** -- explicitly allowed by the
  assignment; keeps the prototype dependency-free.
- **Python + FastAPI + stdlib**, isolated in a `venv`, single-language
  monorepo including a minimal server-rendered UI (no Node/React toolchain).

## Artifacts produced

- `orchestrator/` -- the orchestration engine: `graph.py`, `context.py`,
  `gates.py`, `audit.py`, `policy.py`, `approvals.py`, `workspace.py`,
  `engine.py`, `metrics.py`, `cli.py`, and six agents under `agents/`.
- `url_shortener/` -- the product, generated/evolved by three orchestrator
  runs (not hand-written): FastAPI app, in-memory store, base62 shortener,
  rate limiter, a minimal HTML/JS/CSS UI, and a pytest suite (15 tests).
- `scenarios/01_greenfield_build_shortener/`,
  `scenarios/02_brownfield_alias_and_ttl/`,
  `scenarios/03_ambiguous_make_it_reliable/` -- each with a `requirement.md`
  input and (after running) a `run_log/` containing `audit.jsonl`,
  `context.json`, and `summary.md`.
- `tests/` -- 23 hand-written unit tests proving the engine's governance
  mechanics (retry, rollback, fallback, replan, safe-stop, parallel sync)
  in isolation.
- `docs/DESIGN.md`, `docs/SETUP.md`, `docs/TESTING_AND_TRADEOFFS.md`, this
  file, and the root `README.md`.

## How the three required scenarios play out

| Scenario | Requirement | Notable orchestration behavior observed |
|---|---|---|
| Greenfield | "Build a URL shortener with shorten, redirect, and analytics" | Full 6-stage pipeline from an empty `url_shortener/`; Testing and Documentation run in the same parallel batch (confirmed via `show-run` timeline, both start at the same offset). |
| Brownfield | "Add custom aliases and link expiration" | Design agent scans the existing `app/` files before deciding the task plan (real codebase reasoning); Testing re-runs the full suite (greenfield + new tests) proving no regression. |
| Ambiguous | "Make it more reliable" | Requirements agent detects the vague terms, proposes a concrete interpretation (rate limiting, validation, health check, structured errors), and requires an explicit approval on that interpretation before Design starts -- visible in `context.json`'s `ambiguities` and `decision_lineage`. |

All three runs completed with `status: released`, `stage_level_success_rate:
1.0`, zero retries/rollbacks/replans/fallbacks in the actual runs (the
mechanics for those are validated separately and rigorously via `tests/` --
see `docs/TESTING_AND_TRADEOFFS.md` for why that split was chosen).

## Risks, trade-offs, and validation

See `docs/TESTING_AND_TRADEOFFS.md` for the full table. Summary of the most
consequential ones:

- **Deterministic agents vs. real LLM reasoning** -- validated the
  orchestration mechanics thoroughly; does not validate open-ended
  requirement interpretation the way a real LLM would. Mitigated by a
  provider-agnostic `Agent` interface.
- **In-memory-only persistence** -- explicit, allowed scope decision;
  documented, not hidden.
- **Static verification is compile-only** (`py_compile`), not full static
  analysis/linting -- sufficient to catch generation bugs (a syntax error
  would fail this check, is retried, and rolls back on exhaustion) but not
  semantic ones. A semantic regression risk was identified proactively
  during design rather than caught at runtime: the ambiguous scenario's new
  structured error handler could have silently broken the `detail` field
  existing Scenario 1/2 clients (and tests) depend on. `app/main.py`'s error
  envelope was designed up front to keep `detail` present alongside the new
  `error` object specifically to avoid that regression -- confirmed by
  `test_alias_ttl.py` and `test_api.py` still passing unmodified after
  Scenario 3 runs (see the 15/15 passing regression suite in every run's
  `summary.md`).
- **Engine's snapshot point is hardcoded to the `implementation` stage
  name** rather than generalized -- correct for this fixed graph, would need
  generalizing for a different graph shape.

Validation performed: 23 orchestrator unit tests (all governance mechanics),
15 product tests (regenerated and re-run by every scenario), three full
end-to-end scenario runs from a clean state, and a manual smoke test of the
running server (health check, shorten, redirect, analytics, 404 error
envelope, and the web UI/static assets all verified via `curl`).

## Assumptions

- "Runnable end-to-end" means runnable locally with nothing but Python and
  `pip install -r requirements.txt` -- no external services, accounts, or
  API keys.
- The three scenarios are meant to run **in order** against a shared,
  evolving codebase (brownfield/ambiguous explicitly build on the
  greenfield output), rather than three independent, isolated demos.
- "Human approval checkpoints" needed to be real and inspectable (an actual
  `ApprovalRecord` with an actor and rationale in the audit trail), but did
  not need to block a fully automated demo run by default -- hence
  auto-approve-by-default with a genuine `--interactive` mode available.

## Limitations

See `docs/TESTING_AND_TRADEOFFS.md` "Known limitations" for the complete,
itemized list (deterministic agents, in-memory storage, per-process rate
limiting, illustrative policy guardrails, hardcoded snapshot point, shared
test-process state, Windows-oriented setup instructions).
