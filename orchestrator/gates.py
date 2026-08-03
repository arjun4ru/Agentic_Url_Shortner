"""Entry/exit gate predicates for each SDLC stage.

Gates are intentionally independent of the Agent that just ran: they inspect
only RunContext, so they act as a second, auditable check rather than just
trusting whatever ActionResult.success an agent reports.
"""

from __future__ import annotations

from typing import Optional

from orchestrator.context import ApprovalRecord, RunContext
from orchestrator.graph import GateResult


def _latest_approval(context: RunContext, checkpoint: str) -> Optional[ApprovalRecord]:
    for record in reversed(context.approvals):
        if record.checkpoint == checkpoint:
            return record
    return None


def design_entry_gate(context: RunContext) -> GateResult:
    if not context.normalized_requirement:
        return GateResult(False, "cannot start design before requirements are normalized")
    return GateResult(True)


def implementation_entry_gate(context: RunContext) -> GateResult:
    if not context.design.get("tasks"):
        return GateResult(False, "cannot start implementation before an approved task plan exists")
    return GateResult(True)


def release_entry_gate(context: RunContext) -> GateResult:
    if not context.test_results or not context.doc_artifacts:
        return GateResult(False, "cannot start release readiness before testing and documentation both completed")
    return GateResult(True)


def requirements_exit_gate(context: RunContext) -> GateResult:
    if not context.normalized_requirement:
        return GateResult(False, "requirement not yet normalized")
    unresolved = [a for a in context.ambiguities if not a.get("resolved")]
    if unresolved:
        return GateResult(False, f"{len(unresolved)} unresolved ambiguity(ies)")
    return GateResult(True)


def design_exit_gate(context: RunContext) -> GateResult:
    if not context.design.get("tasks"):
        return GateResult(False, "no task decomposition produced")
    approval = _latest_approval(context, "design_plan_approval")
    if approval is None or not approval.approved:
        return GateResult(False, "design plan not approved")
    return GateResult(True)


def implementation_exit_gate(context: RunContext) -> GateResult:
    if not context.files_changed:
        return GateResult(False, "no files were created or modified")
    if not context.design.get("implementation_verified", False):
        return GateResult(False, "generated files failed static verification (compile check)")
    return GateResult(True)


def testing_exit_gate(context: RunContext) -> GateResult:
    if not context.test_results:
        return GateResult(False, "tests were not run")
    if not context.test_results.get("passed"):
        return GateResult(False, f"tests failed: {context.test_results.get('summary', '')}")
    return GateResult(True)


def documentation_exit_gate(context: RunContext) -> GateResult:
    if not context.doc_artifacts:
        return GateResult(False, "no documentation artifacts produced")
    return GateResult(True)


def release_exit_gate(context: RunContext) -> GateResult:
    approval = _latest_approval(context, "release_approval")
    if approval is None or not approval.approved:
        return GateResult(False, "release not approved")
    return GateResult(True)
