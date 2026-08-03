# Agentic SDLC Orchestrator + URL Shortener

An agentic orchestration engine that drives a URL shortener's full SDLC
(requirements -> design -> implementation -> testing/documentation ->
release readiness) with an explicit dependency graph, entry/exit gates,
human approval checkpoints, bounded retries, fallback, rollback, dynamic
re-planning, policy guardrails, audit-grade observability, and reliability
metrics -- then proves it against three real requirement types: greenfield,
brownfield, and ambiguous.

Read `docs/DESIGN.md` first for the full architecture and the reasoning
behind every scoping decision (stack, in-memory storage, deterministic
agents vs. real LLM calls, why not LangGraph, the minimal frontend, etc.).

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m orchestrator.cli run scenarios\01_greenfield_build_shortener
python -m orchestrator.cli run scenarios\02_brownfield_alias_and_ttl
python -m orchestrator.cli run scenarios\03_ambiguous_make_it_reliable

cd url_shortener
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000/` for the UI or `http://127.0.0.1:8000/docs`
for the API reference. Full instructions (including running the tests, and
starting over from a clean slate): `docs/SETUP.md`.

## Where things live

| What | Where |
|---|---|
| Orchestration engine (the differentiator) | `orchestrator/` |
| The product, generated/evolved by the orchestrator | `url_shortener/` |
| The three required scenarios + their audit trails once run | `scenarios/` |
| Orchestrator engine unit tests (retry/rollback/replan/fallback/safe-stop) | `tests/` |
| Architecture, design decisions, and rationale | `docs/DESIGN.md` |
| Install/build/run instructions | `docs/SETUP.md` |
| Testing approach, limitations, trade-offs | `docs/TESTING_AND_TRADEOFFS.md` |
| Final engineering summary (plan, artifacts, risks, assumptions) | `docs/ENGINEERING_SUMMARY.md` |

## At a glance

- **Stack**: Python 3.11, FastAPI, pytest, stdlib for the orchestrator itself
  -- no database, no Node/npm, no external orchestration framework, no API
  keys required.
- **Agents are deterministic/rule-based**, not live LLM calls, by design --
  see `docs/DESIGN.md` §2/§9 for the full trade-off discussion.
- Every scenario run writes a full audit trail (`scenarios/<n>/run_log/`)
  you can replay with `python -m orchestrator.cli show-run <scenario_dir>`.
