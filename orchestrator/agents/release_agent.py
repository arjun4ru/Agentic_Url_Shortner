"""Release Readiness stage.

This is the synchronization point after Testing + Documentation: it runs the
final policy guardrail check, requires a human approval checkpoint, and (if
approved) writes the run's summary report. If rejected or guardrails fail,
the engine's failure_policy for this node (rollback_halt) takes over.
"""

from __future__ import annotations

import time
from pathlib import Path

from orchestrator.agents.base import ActionResult, Agent
from orchestrator.approvals import ApprovalManager
from orchestrator.context import RunContext
from orchestrator.policy import PolicyGuard


class ReleaseAgent(Agent):
    name = "release_agent"

    def __init__(self, approvals: ApprovalManager, policy: PolicyGuard, run_log_dir: Path) -> None:
        self.approvals = approvals
        self.policy = policy
        self.run_log_dir = run_log_dir

    def act(self, context: RunContext) -> ActionResult:
        guard_result = self.policy.pre_release_check(context)
        if not guard_result.passed:
            context.record_decision(
                stage="release_readiness", actor=self.name, action="guardrail_block",
                rationale=guard_result.reason,
            )
            return ActionResult(success=False, summary=f"Release blocked by guardrail: {guard_result.reason}",
                                 failure_class="bug")

        summary_text = self._build_summary(context)
        approval = self.approvals.request(
            context,
            checkpoint="release_approval",
            stage="release_readiness",
            summary=summary_text,
        )

        if not approval.approved:
            return ActionResult(success=False, summary="Release was not approved", failure_class="bug")

        context.status = "released"
        context.ended_at = time.time()
        self._write_summary_report(context, summary_text)

        return ActionResult(success=True, summary="Release approved and finalized")

    def _build_summary(self, context: RunContext) -> str:
        files = "\n".join(f"  - [{fc.action}] {fc.path}  ({fc.summary})" for fc in context.files_changed)
        return (
            f"Run {context.run_id} ({context.scenario_type}) is ready for release.\n\n"
            f"Files changed:\n{files}\n\n"
            f"Tests: {context.test_results.get('summary', 'n/a')}\n"
            f"Docs degraded (fallback used): {context.docs_degraded}\n"
            f"Re-plans triggered this run: {context.replan_count}\n"
        )

    def _write_summary_report(self, context: RunContext, approval_summary: str) -> None:
        target = self.run_log_dir / "summary.md"
        guard = self.policy.check_file_write(target)
        if not guard.passed:
            return  # already logged as a violation; do not write outside project root

        lineage_lines = "\n".join(
            f"- `{d.timestamp:.0f}` **{d.stage}** ({d.actor}) — {d.action}: {d.rationale}"
            for d in context.decision_lineage
        )
        approval_lines = "\n".join(
            f"- `{a.checkpoint}` @ {a.stage}: {'APPROVED' if a.approved else 'REJECTED'} by {a.actor} — {a.rationale}"
            for a in context.approvals
        )
        ambiguity_lines = "\n".join(
            f"- Q: {a['question']}\n  Resolution: {a.get('proposed_resolution', 'n/a')} "
            f"(resolved={a.get('resolved')}, by={a.get('resolution_actor', 'n/a')})"
            for a in context.ambiguities
        ) or "(none)"

        content = f"""# Run Summary: {context.run_id}

- Scenario: **{context.scenario_type}**
- Status: **{context.status}**
- Started: {context.started_at}
- Ended: {context.ended_at}
- Re-plans triggered: {context.replan_count}
- Docs degraded (fallback used): {context.docs_degraded}

## Normalized requirement

```
{context.normalized_requirement}
```

## Ambiguities identified & resolved

{ambiguity_lines}

## Design / task decomposition

```
{context.design}
```

## Files changed

{chr(10).join(f"- [{fc.action}] {fc.path} ({fc.summary})" for fc in context.files_changed) or "(none)"}

## Test results

```
{context.test_results.get('summary', 'n/a')}
```

## Approvals

{approval_lines}

## Full decision lineage

{lineage_lines}
"""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
