"""Human approval checkpoints for high-impact actions.

Two modes:
  * "auto"        -- reads a decision from a config dict (default: approve).
                     Lets the whole pipeline run end-to-end with one command,
                     which is what makes the three demo scenarios reproducible.
  * "interactive" -- actually pauses and prompts in the terminal, proving the
                     human-in-the-loop mechanism is real and not just decoration.

Every decision (auto or human) is recorded into RunContext.approvals and the
audit log, with an explicit actor field, so it's always clear from the trail
whether a human or the default policy approved a given checkpoint.
"""

from __future__ import annotations

from typing import Optional

from orchestrator.audit import AuditLogger
from orchestrator.context import ApprovalRecord, RunContext


class ApprovalManager:
    def __init__(self, mode: str = "auto", audit: Optional[AuditLogger] = None) -> None:
        if mode not in ("auto", "interactive"):
            raise ValueError(f"unknown approval mode: {mode}")
        self.mode = mode
        self.audit = audit

    def request(self, context: RunContext, *, checkpoint: str, stage: str, summary: str) -> ApprovalRecord:
        if self.mode == "interactive":
            record = self._request_interactive(checkpoint=checkpoint, stage=stage, summary=summary)
        else:
            record = ApprovalRecord(
                checkpoint=checkpoint,
                stage=stage,
                approved=True,
                actor="auto-approver(config-default)",
                rationale="auto-approve mode: default policy is to approve to allow reproducible end-to-end runs",
            )

        context.record_approval(record)
        context.record_decision(
            stage=stage,
            actor=record.actor,
            action="approve" if record.approved else "reject",
            rationale=record.rationale,
            data={"checkpoint": checkpoint},
        )
        if self.audit:
            self.audit.log(
                "approval",
                stage,
                checkpoint=checkpoint,
                approved=record.approved,
                actor=record.actor,
            )
        return record

    def _request_interactive(self, *, checkpoint: str, stage: str, summary: str) -> ApprovalRecord:
        print("\n" + "=" * 70)
        print(f"HUMAN APPROVAL REQUIRED  [{checkpoint}]  (stage: {stage})")
        print("-" * 70)
        print(summary)
        print("=" * 70)
        answer = input("Approve? [y/N]: ").strip().lower()
        approved = answer in ("y", "yes")
        rationale = input("Rationale (optional): ").strip() or (
            "approved via interactive checkpoint" if approved else "rejected via interactive checkpoint"
        )
        return ApprovalRecord(
            checkpoint=checkpoint,
            stage=stage,
            approved=approved,
            actor="human(interactive)",
            rationale=rationale,
        )
