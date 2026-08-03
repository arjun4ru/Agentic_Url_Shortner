"""Design / Task Decomposition stage.

For brownfield and ambiguous requirements this stage performs actual
codebase reasoning: it reads the existing url_shortener/app files (created by
a prior scenario run) to determine what's already there before deciding what
needs to change, rather than blindly assuming a fixed target state.

It then produces an explicit task list with dependencies (a small DAG in its
own right) and requires human approval of the plan before Implementation may
begin.
"""

from __future__ import annotations

from orchestrator.agents.base import ActionResult, Agent
from orchestrator.approvals import ApprovalManager
from orchestrator.context import RunContext
from orchestrator.workspace import Workspace


class DesignAgent(Agent):
    name = "design_agent"

    def __init__(self, approvals: ApprovalManager, workspace: Workspace) -> None:
        self.approvals = approvals
        self.workspace = workspace

    def act(self, context: RunContext) -> ActionResult:
        if context.scenario_type == "greenfield":
            design = self._design_greenfield()
        elif context.scenario_type == "brownfield":
            design = self._design_brownfield()
        else:
            design = self._design_ambiguous()

        context.design = design
        context.record_decision(
            stage="design",
            actor=self.name,
            action="task_decomposition",
            rationale=design["architecture_notes"][0] if design["architecture_notes"] else "",
            data={"impacted_modules": design["impacted_modules"], "task_count": len(design["tasks"])},
        )

        task_list_str = "\n".join(
            f"  - [{t['id']}] {t['title']}"
            + (f"  (depends on: {', '.join(t['depends_on'])})" if t["depends_on"] else "")
            for t in design["tasks"]
        )
        summary = (
            f"Impacted modules: {', '.join(design['impacted_modules'])}\n\n"
            f"Architecture notes:\n- " + "\n- ".join(design["architecture_notes"]) + "\n\n"
            f"Task plan:\n{task_list_str}"
        )

        approval = self.approvals.request(
            context,
            checkpoint="design_plan_approval",
            stage="design",
            summary=summary,
        )

        if not approval.approved:
            return ActionResult(
                success=False,
                summary="Design plan was not approved",
                data={"design": design},
                failure_class="design_issue",
            )

        return ActionResult(success=True, summary="Design plan approved", data={"design": design})

    # -- codebase reasoning helpers -----------------------------------

    def _existing_files(self) -> dict[str, bool]:
        candidates = [
            "app/models.py", "app/store.py", "app/shortener.py", "app/main.py",
            "app/ratelimit.py", "app/web/index.html",
        ]
        return {c: self.workspace.exists(c) for c in candidates}

    # -- per-scenario design -------------------------------------------

    def _design_greenfield(self) -> dict:
        tasks = [
            {"id": "define_models", "title": "Define request/response schemas (app/models.py)", "depends_on": []},
            {"id": "implement_store", "title": "Implement thread-safe in-memory store (app/store.py)", "depends_on": []},
            {"id": "implement_shortener_core", "title": "Implement base62 short-code generation (app/shortener.py)", "depends_on": []},
            {"id": "implement_api_routes", "title": "Implement FastAPI routes (app/main.py)", "depends_on": ["define_models", "implement_store", "implement_shortener_core"]},
            {"id": "implement_web_ui", "title": "Implement minimal HTML/JS/CSS UI (app/web/)", "depends_on": ["implement_api_routes"]},
        ]
        return {
            "impacted_modules": ["app/models.py", "app/store.py", "app/shortener.py", "app/main.py", "app/web/*"],
            "architecture_notes": [
                "Greenfield build: single FastAPI app, in-memory store guarded by a lock, "
                "base62 counter-based codes (no collision retries needed), UI served as static "
                "files by the same FastAPI process.",
            ],
            "tasks": tasks,
        }

    def _design_brownfield(self) -> dict:
        existing = self._existing_files()
        missing = [f for f, present in existing.items() if not present]
        notes = [
            "Brownfield enhancement on top of the greenfield codebase: "
            f"scanned app/ and found existing files: {[f for f, p in existing.items() if p]}.",
        ]
        if missing:
            notes.append(
                f"Warning: expected prior files not found ({missing}) -- Scenario 1 (greenfield) "
                "should be run first; proceeding will create them fresh instead of patching."
            )

        tasks = [
            {"id": "patch_models", "title": "Add custom_alias + ttl_seconds fields to ShortenRequest (app/models.py)", "depends_on": []},
            {"id": "patch_store", "title": "Add alias-uniqueness + TTL/expiry handling to the store (app/store.py)", "depends_on": ["patch_models"]},
            {"id": "patch_routes", "title": "Wire custom_alias/ttl_seconds through POST /api/shorten and 410-on-expiry (app/main.py)", "depends_on": ["patch_models", "patch_store"]},
        ]
        return {
            "impacted_modules": ["app/models.py", "app/store.py", "app/main.py"],
            "architecture_notes": notes,
            "tasks": tasks,
        }

    def _design_ambiguous(self) -> dict:
        existing = self._existing_files()
        notes = [
            "Ambiguous requirement resolved (see Requirements stage approval) into concrete reliability "
            f"work. Scanned app/ -- existing files: {[f for f, p in existing.items() if p]}.",
            "Rate limiting implemented in-memory (per-process token bucket keyed by client IP) rather "
            "than via Redis, consistent with the no-external-dependency scoping decision.",
        ]
        tasks = [
            {"id": "implement_rate_limiter", "title": "Implement in-memory token-bucket rate limiter (app/ratelimit.py)", "depends_on": []},
            {"id": "patch_main_reliability", "title": "Wire rate limiter + /api/health + structured error handlers into app/main.py", "depends_on": ["implement_rate_limiter"]},
        ]
        return {
            "impacted_modules": ["app/ratelimit.py", "app/main.py"],
            "architecture_notes": notes,
            "tasks": tasks,
        }
