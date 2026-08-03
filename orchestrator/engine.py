"""The execution engine.

Drives the graph batch-by-batch (sequential stages, parallel stages
synchronized at the next dependent), with bounded retries per node, and
resolves exhausted retries via each node's failure_policy: fallback,
rollback+halt, or replan (jump execution back to an earlier node and
cascade forward again -- the non-linear, dynamic re-planning behavior).

A `stop_requested` flag on RunContext is checked between batches for a
graceful safe-stop.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Dict, Optional

from orchestrator.agents.base import ActionResult, Agent
from orchestrator.audit import AuditLogger
from orchestrator.context import RunContext
from orchestrator.graph import Graph
from orchestrator.workspace import Workspace

_IMPLEMENTATION_SNAPSHOT_NAME = "before_implementation_attempt"


class EngineHalted(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Engine:
    def __init__(
        self,
        graph: Graph,
        agents: Dict[str, Agent],
        workspace: Workspace,
        audit: AuditLogger,
        run_log_dir: Path,
    ) -> None:
        self.graph = graph
        self.agents = agents
        self.workspace = workspace
        self.audit = audit
        self.run_log_dir = run_log_dir
        self.snapshots_dir = run_log_dir / "snapshots"

    def run(self, context: RunContext) -> RunContext:
        return asyncio.run(self._run_async(context))

    async def _run_async(self, context: RunContext) -> RunContext:
        self.audit.log("run_start", "orchestrator", scenario_type=context.scenario_type)
        batches = self.graph.topological_batches()
        batch_index = 0

        try:
            while batch_index < len(batches):
                if context.stop_requested:
                    self.audit.log("safe_stop", "orchestrator", at_batch=batch_index)
                    context.status = "halted"
                    break

                batch = batches[batch_index]

                if "implementation" in batch:
                    snap = self.workspace.snapshot(self.snapshots_dir, _IMPLEMENTATION_SNAPSHOT_NAME)
                    self.audit.log("snapshot", "implementation", path=str(snap) if snap else None)

                results = await asyncio.gather(*(self._execute_node(name, context) for name in batch))
                replan_target = next((r for r in results if r is not None), None)

                if replan_target:
                    context.replan_count += 1
                    target_index = self.graph.batch_index_of(replan_target, batches)
                    self.audit.log("replan", "orchestrator", target=replan_target,
                                    replan_count=context.replan_count)
                    batch_index = target_index
                    continue

                batch_index += 1
        except EngineHalted as exc:
            context.status = "halted"
            self.audit.log("run_halted", "orchestrator", reason=exc.reason)

        if context.status == "running":
            context.status = "released" if batch_index >= len(batches) else "failed"
        if context.ended_at is None:
            context.ended_at = time.time()
        self.audit.log("run_end", "orchestrator", status=context.status)
        return context

    async def _execute_node(self, name: str, context: RunContext) -> Optional[str]:
        """Runs one node with bounded retries.

        Returns a replan target node name if a replan was requested, else None.
        Raises EngineHalted if the node's failure policy dictates a hard stop.
        """
        node = self.graph.get(name)

        entry = node.entry_gate(context)
        self.audit.log("entry_gate", name, passed=entry.passed, reason=entry.reason)
        if not entry.passed:
            raise EngineHalted(f"{name}: entry gate failed: {entry.reason}")

        max_attempts = node.max_retries + 1
        last_result: Optional[ActionResult] = None
        last_gate_reason = ""

        for attempt in range(1, max_attempts + 1):
            context.stage_attempts[name] = attempt
            self.audit.log("stage_start", name, attempt=attempt)

            agent = self.agents[name]
            try:
                result = await asyncio.to_thread(agent.act, context)
            except Exception as exc:  # noqa: BLE001 - agent crash is a failure outcome, not a bug in the engine
                result = ActionResult(success=False, summary=f"agent raised an exception: {exc}", error=str(exc))

            last_result = result

            if result.success:
                gate = node.exit_gate(context)
                last_gate_reason = gate.reason
                if gate.passed:
                    self.audit.log("stage_success", name, attempt=attempt, summary=result.summary)
                    return None
                self.audit.log("exit_gate_failed", name, attempt=attempt, reason=gate.reason)
            else:
                self.audit.log("stage_failure", name, attempt=attempt, reason=result.summary,
                                failure_class=result.failure_class)

            if attempt < max_attempts:
                self.audit.log("retry", name, next_attempt=attempt + 1)

        return await self._handle_exhausted(name, node, context, last_result, last_gate_reason)

    async def _handle_exhausted(self, name, node, context: RunContext, last_result, last_gate_reason) -> Optional[str]:
        policy = node.failure_policy
        self.audit.log("retries_exhausted", name, policy=policy, max_retries=node.max_retries)

        if policy == "fallback":
            agent = self.agents[name]
            try:
                fb_result = await asyncio.to_thread(agent.fallback, context)
                self.audit.log("fallback_used", name, summary=fb_result.summary)
                return None
            except NotImplementedError:
                self.audit.log("fallback_unavailable", name)
                raise EngineHalted(f"{name}: no fallback available after exhausting retries")

        if policy == "replan":
            failure_class = last_result.failure_class if last_result else None
            if failure_class == "design_issue" and node.replan_target:
                return node.replan_target
            # Not classified as design-level: replanning wouldn't help, fall back
            # to the safe default of rolling back and halting.
            self._rollback(name)
            reason = last_gate_reason or (last_result.summary if last_result else "unknown failure")
            raise EngineHalted(f"{name}: failed after retries (non-design-level, no replan target); "
                                f"rolled back and halted -- {reason}")

        # rollback_halt (default)
        self._rollback(name)
        reason = last_gate_reason or (last_result.summary if last_result else "unknown failure")
        raise EngineHalted(f"{name}: failed after {node.max_retries + 1} attempt(s); rolled back and halted -- {reason}")

    def _rollback(self, stage_name: str) -> None:
        snapshot = self.snapshots_dir / _IMPLEMENTATION_SNAPSHOT_NAME
        if not snapshot.exists():
            self.audit.log("rollback_skipped", stage_name, reason="no snapshot exists yet")
            return
        try:
            self.workspace.restore(snapshot)
            self.audit.log("rollback", stage_name, restored_from=str(snapshot))
        except Exception as exc:  # noqa: BLE001 - a failed rollback must never crash the CLI itself
            self.audit.log("rollback_failed", stage_name, restored_from=str(snapshot), error=str(exc))
