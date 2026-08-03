# Design Document: Agentic SDLC Orchestrator + URL Shortener

Status: IMPLEMENTED — all three scenarios have been run end-to-end
successfully. See `docs/ENGINEERING_SUMMARY.md` for the final report and
`docs/TESTING_AND_TRADEOFFS.md` for validation details.

## 1. What we are actually building

The assignment asks for two things that are easy to conflate:

1. **The product**: a URL shortener (shorten / redirect / analytics / reliability).
2. **The real deliverable**: an **agentic orchestration layer** that drives that product's
   SDLC (requirements → design → implementation → testing → documentation → release
   readiness) with graphs, gates, approvals, retries, rollback, audit, metrics, and
   re-planning — and can be pointed at three different kinds of requirements
   (greenfield / brownfield / ambiguous) to prove it generalizes.

So this repo has **two layers**:

- `orchestrator/` — the agentic execution engine (the critical differentiator).
- `url_shortener/` — the product. It is **not hand-written**; it is *generated and
  evolved by running the orchestrator* against the three scenario requirements. This is
  what makes the demo real: running a scenario actually produces working, tested code on
  disk, not just a narrated plan.

## 2. Confirmed scoping decisions

| Decision | Choice | Why |
|---|---|---|
| Stack | Python 3.11, FastAPI, pytest, stdlib only otherwise | Already installed, minimal deps, great for both the API and a small orchestration engine |
| Storage | In-memory dict (process-lifetime), no DB/Redis | Assignment explicitly allows this; keeps prototype dependency-free |
| Agent execution | **Deterministic/rule-based** agents, not live LLM calls | Zero API keys/cost, instant, 100% reproducible for grading. `Agent` is an interface, so a real LLM could be swapped in later — documented as a limitation, not hidden |
| Approvals | Config-driven **auto-approve by default**, `--interactive` flag to actually prompt in the terminal | Lets graders run one command end-to-end, while still proving human-in-the-loop works |
| Orchestration tech | Hand-rolled DAG engine using stdlib (`asyncio`, `dataclasses`, `json`) — LangGraph considered and deliberately not used, see §9 | Full transparency + demonstrates orchestration design skill directly, which is what's being evaluated |
| Persistence of runs | JSON Lines audit log + JSON snapshot files per run, under `scenarios/<n>/run_log/` | Enough for "audit-grade traceability" without a database |
| Frontend | One minimal HTML/CSS/vanilla-JS page served by FastAPI itself (`StaticFiles`/Jinja2) | True single-language monorepo; `uvicorn` alone starts both the API and the UI; no Node/npm/build step |
| Environment isolation | Python `venv` per project; dependencies installed only inside it | Keeps this project's packages isolated from anything else on your machine |
| Repo hygiene | `.gitignore` covering `venv/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.env`, editor folders | Keeps the repo clean; run logs under `scenarios/*/run_log/` are intentionally **not** ignored since they're graded evidence |

## 3. Repository layout

```
Agentic_Url_Shortner/
├── docs/
│   ├── DESIGN.md                     (this file)
│   ├── SETUP.md                      (how to run everything)
│   ├── TESTING_AND_TRADEOFFS.md      (testing approach, limitations, trade-offs)
│   └── ENGINEERING_SUMMARY.md        (final summary: plan, artifacts, risks, assumptions)
├── orchestrator/
│   ├── graph.py            # Node/Edge/Graph: the explicit dependency graph
│   ├── context.py          # RunContext: cross-stage state + decision lineage
│   ├── gates.py            # entry/exit gate predicates for each SDLC stage
│   ├── audit.py            # structured JSONL audit logger + reader
│   ├── policy.py           # policy guardrails (security/compliance/change-control checks)
│   ├── approvals.py        # human approval checkpoints (auto or interactive)
│   ├── workspace.py        # guarded file I/O boundary for agents + snapshot/restore (rollback)
│   ├── metrics.py          # success rate, retry/rollback freq, MTTR, latency
│   ├── engine.py           # the execution engine: sequencing, parallel+sync, retries,
│   │                       # fallback, rollback, safe-stop, dynamic re-planning
│   ├── agents/
│   │   ├── base.py                 # Agent interface
│   │   ├── requirements_agent.py   # interpret + normalize + flag ambiguity
│   │   ├── design_agent.py         # task decomposition + architecture decisions
│   │   ├── implementation_agent.py # generates/patches url_shortener source files
│   │   ├── testing_agent.py        # generates/runs pytest, records results
│   │   ├── documentation_agent.py  # generates README/API docs for the change
│   │   └── release_agent.py        # release checklist + final gate
│   └── cli.py              # `run`, `show-run`, `approve` commands
├── url_shortener/                    # GENERATED/EVOLVED by the orchestrator, not hand-written
│   ├── app/  (main.py, models.py, store.py, shortener.py, analytics.py, ratelimit.py)
│   │   └── web/  (index.html, app.js, style.css)   # minimal UI, served via FastAPI StaticFiles
│   └── tests/
├── scenarios/
│   ├── 01_greenfield_build_shortener/requirement.md
│   ├── 02_brownfield_alias_and_ttl/requirement.md
│   └── 03_ambiguous_make_it_reliable/requirement.md
│   (each gets a run_log/ folder with audit.jsonl + snapshots + summary.md after running)
├── .venv/                            (created locally, not committed)
├── .gitignore
├── requirements.txt
└── README.md                         (project overview; points to docs/SETUP.md for install steps)
```

## 4. The URL Shortener product spec (what gets built)

Core APIs:

- `POST /api/shorten` `{long_url, custom_alias?, ttl_seconds?}` → `{short_code, short_url}`
- `GET /{short_code}` → 302 redirect to long URL, records a click (404 if unknown, 410 if expired)
- `GET /api/analytics/{short_code}` → `{clicks, created_at, last_accessed_at, recent_hits}`
- `GET /api/health` → liveness status

Data model (in-memory, thread-safe via a lock):

- `short_code -> {long_url, created_at, expires_at, clicks, last_accessed_at, recent_hits[]}`
- Short codes generated via base62 of an atomic counter (no collision retries needed);
  custom aliases checked for uniqueness.

Reliability features layered in across the scenarios (see §6): input/URL validation,
idempotent-safe creation, lazy TTL expiry, bounded recent-hit history (avoid unbounded
memory growth), in-memory rate limiting on `/api/shorten`, structured error responses,
`/api/health`.

### 4.1 Minimal frontend

A single page at `GET /` (served by FastAPI via `StaticFiles`/Jinja2, no separate dev
server): a form to submit a long URL (+ optional alias/TTL once Scenario 2 lands), a
result showing the short link, and a small analytics lookup box that calls
`GET /api/analytics/{code}` and renders click count / last-accessed. Plain HTML/CSS +
`fetch()` — no build step, no framework, no Node/npm dependency. `uvicorn app.main:app`
starts both the API and this UI from one process, which keeps the whole thing a true
single-language monorepo.

## 5. Orchestrator architecture

### 5.1 The dependency graph

```
Requirements → Design → Implementation → ┬→ Testing        ┐
                                          └→ Documentation  ┴→ Release Readiness
```

- Requirements, Design, Implementation, Release Readiness are sequential.
- Testing and Documentation run **in parallel** after Implementation (via `asyncio.gather`)
  and **synchronize** at the Release Readiness gate — this is the sequential+parallel
  requirement from the spec.
- Every node declares an **entry gate** (preconditions to start) and an **exit gate**
  (validation before advancing). Gates are plain predicate functions over `RunContext`,
  e.g. Implementation's exit gate = "files written AND static checks pass".

### 5.2 Cross-stage context & decision lineage

A single `RunContext` object flows through the whole run and accumulates:

- the normalized requirement, identified ambiguities and how they were resolved
- design decisions and the task list produced
- generated/modified file paths (diff-like record)
- test results, doc artifacts
- every approval request/response
- an ordered **decision lineage**: `[{stage, timestamp, actor, action, rationale}]`

This is what lets a human reviewer trace *why* the system did what it did.

### 5.3 Agents

`Agent.act(context) -> Artifact` is the interface. Each stage has one concrete
deterministic agent (rule/template-based — see §2). For example, the Implementation
agent for the brownfield scenario inspects `url_shortener/app/models.py` and
`store.py`, and generates a patch adding `custom_alias` + `ttl_seconds` fields —
this is the "codebase reasoning" requirement in action.

### 5.4 Human approval checkpoints

Governance-critical points always require approval (auto-approved by default via config,
or actually prompted with `--interactive`):

1. **After Design, before Implementation** — approve the task plan / architecture decisions.
2. **At Release Readiness** — approve the release.
3. **Ad hoc, when Requirements flags ambiguity** — a human must approve the system's
   interpreted/assumed scope before Design proceeds (this is exercised by Scenario 3).

### 5.5 Retries, fallback, rollback, safe-stop

- Each stage retries on exit-gate failure up to `max_retries` (default 2), with the
  failure reason logged each time.
- If retries are exhausted:
  - **Documentation** failures → **fallback** to a minimal stub doc generator (accepted
    risk, logged, does not block release).
  - **Implementation/Testing** failures → **rollback** to the last good snapshot of
    `url_shortener/` for this run and **halt** (safe-stop) with a written failure report.
- **Dynamic re-planning**: if a Testing failure is classified as design-level (a rule,
  e.g. an acceptance-criterion mismatch rather than a code bug), the engine re-enters
  the **Design** node instead of just retrying Implementation, then cascades
  Implementation → Testing → Documentation again — this is the non-linear execution
  requirement.
- A `stop_requested` check between stages allows a graceful abort that preserves state
  for later inspection/resume.

### 5.6 Policy guardrails

A small `PolicyGuard` runs before Implementation writes files and before Release:
blocks writes outside the project tree, blocks obvious hardcoded secrets (regex scan),
requires the ambiguity-approval checkpoint for scope changes, and blocks Release if any
guardrail failed. Simple rule checks, not a full policy engine — documented as a
scoping limitation.

### 5.7 Observability, audit, metrics

- Every event (stage start/end, gate result, retry, rollback, replan, approval) is
  written as a structured JSON line to `run_log/audit.jsonl` — durable, greppable,
  replayable.
- `orchestrator show-run <id>` prints the timeline from that log.
- `metrics.py` computes, per run and in aggregate: success rate, retry frequency,
  rollback frequency, MTTR (time between failure detection and next successful
  attempt), and end-to-end latency — printed in the Final Engineering Summary.

## 6. The three scenarios

| # | Type | Requirement | What it exercises |
|---|---|---|---|
| 1 | Greenfield | "Build a URL shortener with shorten, redirect, and click analytics" | Full pipeline from nothing; generates `url_shortener/` from scratch |
| 2 | Brownfield | "Add custom short codes (aliases) and link expiration (TTL) to the existing shortener" | Codebase reasoning on existing modules, scoped patch, regression-safe testing |
| 3 | Ambiguous | "Make the URL shortener more reliable / production-ready" | Requirement agent must flag ambiguity, propose a concrete interpretation (rate limiting + validation + health check), get human approval on scope, then implement |

Running each scenario through the CLI actually writes/modifies the code under
`url_shortener/`, runs pytest, generates docs, and produces a full audit trail + summary
under that scenario's `run_log/`.

## 7. Testing approach (high level — detailed in `TESTING_AND_TRADEOFFS.md`)

- `orchestrator/` unit tests: graph traversal, gate logic, retry/rollback/replan
  behavior, metrics computation — using fakes/stubs, no real file I/O.
- `url_shortener/` unit + integration tests: generated alongside the code by the
  Testing agent, run via pytest + FastAPI's `TestClient`.
- End-to-end: running all three scenarios in sequence from a clean state is the
  acceptance test for the whole system.

## 8. Key risks / trade-offs (expanded in ENGINEERING_SUMMARY.md later)

- Deterministic agents prove the *orchestration mechanics* convincingly but don't show
  open-ended LLM reasoning — mitigated by a pluggable `Agent` interface and by making
  the Requirements agent's ambiguity-handling logic itself inspectable/rich.
- In-memory storage means no durability across process restarts for the shortener
  itself — acceptable per the assignment's allowance and called out explicitly.
- Rule-based policy guardrails are illustrative, not exhaustive — a production system
  would need a real policy engine (e.g. OPA) and secret scanning tool.

## 9. Is a hand-rolled engine really "how agentic systems are built"? Why not a framework?

Honest answer: there's no single canonical way — production agentic systems range from
fully custom state machines to heavyweight frameworks, and the right choice depends on
what you're optimizing for.

**What frameworks like LangGraph/AutoGen/CrewAI are actually good for:** orchestrating
*LLM reasoning* across multiple turns/agents — routing between LLM calls, managing
conversation/tool-call state, streaming. LangGraph specifically also gives you graph
routing, checkpointing, and `interrupt()` for human-in-the-loop, which do overlap with
this assignment's asks.

**What they don't give you for free:** bounded retry-with-fallback policies, rollback to
a prior artifact snapshot, audit-grade JSONL traceability, reliability metrics like
MTTR/success-rate/retry-frequency, or policy guardrails. Every one of those is a hand-built
layer on top regardless of which framework (if any) sits underneath — they're the actual
"critical differentiator" content in the PDF, and none of it comes from `pip install`.

**Why we're not using one here**, concretely:
1. This assignment evaluates *orchestration design*, not framework fluency —
   "Architecture/system design quality" and "Clarity and defensibility of decisions" are
   explicit grading criteria, and a hand-rolled engine lets every mechanic be explained
   from first principles rather than "the framework handles that."
2. Our agents are deterministic (§2), so we don't need an LLM-reasoning orchestration
   layer — we need a **workflow/state-machine engine**, which is a much smaller, simpler
   problem (closer to what Temporal/Step Functions solve than what LangGraph solves).
3. Zero extra dependencies, per your "very simple flow" instruction.

**Where this diverges from a real production system:** at scale, teams typically *do*
combine a durable workflow engine (Temporal, Step Functions, or yes, LangGraph if the
nodes are LLM calls) for the execution mechanics with an actual LLM-calling layer for
open-ended reasoning. Our engine is a right-sized educational/prototype version of that
pattern — same concepts (graph, gates, checkpoints, retries), smaller blast radius. This
is called out explicitly rather than glossed over, since defensibility of the decision
matters more here than the specific technology chosen.

## 10. Environment & repo hygiene

- A dedicated virtual environment is created at `.venv/` before installing anything:
  `python -m venv .venv`, then activate it, then `pip install -r requirements.txt`. No
  package is ever installed into the global/system Python.
- `.gitignore` excludes `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.env`,
  `*.egg-info/`, and editor folders (`.vscode/`, `.idea/`). It explicitly does **not**
  exclude `scenarios/*/run_log/` — those files are graded evidence of the orchestrator
  actually running.
- `requirements.txt` pins exact versions (`fastapi==...`, `uvicorn==...`, `pytest==...`,
  `httpx==...`) so the install is reproducible.

## 11. Build order (task decomposition for implementation phase)

1. Repo scaffold: create `.venv`, `.gitignore`, `requirements.txt`, package dirs, root `README.md` stub
2. Install pinned dependencies into `.venv`
3. `orchestrator/graph.py`, `context.py` — pure data structures
4. `orchestrator/audit.py`, `policy.py`, `approvals.py`
5. `orchestrator/agents/*` (incl. embedded product-code + minimal frontend generators)
6. `orchestrator/engine.py` (wires 3–5: sequencing, parallel+sync, retries, rollback, replanning)
7. `orchestrator/metrics.py`, `orchestrator/cli.py`
8. `scenarios/*/requirement.md` input files
9. Run Scenario 1 → generates `url_shortener/` baseline (API + minimal web UI)
10. Run Scenario 2 → evolves it (alias + TTL)
11. Run Scenario 3 → evolves it (reliability hardening)
12. `docs/SETUP.md` (install/build/run steps), `docs/TESTING_AND_TRADEOFFS.md`, `docs/ENGINEERING_SUMMARY.md`
13. Full verification pass (`pytest`, manual `uvicorn` smoke test incl. the UI, review all three run logs)

Steps 1–2 must happen first; 3–7 have a hard dependency chain; 8 can happen anytime
before 9; 9→10→11 must be sequential since each scenario builds on the previous code
state; 12–13 come last.

---

**Status**: implemented and verified end-to-end. All three scenarios run
successfully (`status: released`, zero retries/rollbacks/replans on the
happy path); engine governance mechanics (retry/rollback/fallback/replan/
safe-stop) are separately proven via 23 unit tests in `tests/`. See
`docs/ENGINEERING_SUMMARY.md` for the full report.
