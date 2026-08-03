"""Cross-stage run state and decision lineage.

A single RunContext instance flows through every stage of one orchestrator
run. It is the "shared memory" that lets later stages see what earlier
stages decided (and why), and it is what gets serialized to disk so a run
can be inspected after the fact.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


def _now() -> float:
    return time.time()


@dataclass
class DecisionRecord:
    """One entry in the decision lineage: who decided what, and why."""

    stage: str
    actor: str  # e.g. "requirements_agent", "human(interactive)", "auto-approver"
    action: str  # e.g. "normalize_requirement", "flag_ambiguity", "approve", "reject"
    rationale: str
    timestamp: float = field(default_factory=_now)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalRecord:
    checkpoint: str
    stage: str
    approved: bool
    actor: str
    rationale: str
    timestamp: float = field(default_factory=_now)


@dataclass
class FileChange:
    path: str
    action: str  # "created" | "modified"
    summary: str


@dataclass
class RunContext:
    run_id: str
    scenario_type: str  # "greenfield" | "brownfield" | "ambiguous"
    requirement_text: str
    scenario_dir: str

    # populated by requirements_agent
    normalized_requirement: dict[str, Any] = field(default_factory=dict)
    ambiguities: list[dict[str, Any]] = field(default_factory=list)

    # populated by design_agent
    design: dict[str, Any] = field(default_factory=dict)

    # populated by implementation_agent
    files_changed: list[FileChange] = field(default_factory=list)

    # populated by testing_agent
    test_results: dict[str, Any] = field(default_factory=dict)

    # populated by documentation_agent
    doc_artifacts: list[str] = field(default_factory=list)
    docs_degraded: bool = False

    # governance trail
    approvals: list[ApprovalRecord] = field(default_factory=list)
    decision_lineage: list[DecisionRecord] = field(default_factory=list)

    # engine bookkeeping
    stage_attempts: dict[str, int] = field(default_factory=dict)
    replan_count: int = 0
    stop_requested: bool = False
    status: str = "running"  # running | released | halted | failed

    started_at: float = field(default_factory=_now)
    ended_at: Optional[float] = None

    @classmethod
    def new(cls, *, scenario_type: str, requirement_text: str, scenario_dir: str) -> "RunContext":
        run_id = f"run-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        return cls(
            run_id=run_id,
            scenario_type=scenario_type,
            requirement_text=requirement_text,
            scenario_dir=scenario_dir,
        )

    def record_decision(self, *, stage: str, actor: str, action: str, rationale: str, data: Optional[dict] = None) -> None:
        self.decision_lineage.append(
            DecisionRecord(stage=stage, actor=actor, action=action, rationale=rationale, data=data or {})
        )

    def record_approval(self, record: ApprovalRecord) -> None:
        self.approvals.append(record)

    def record_file_change(self, path: str, action: str, summary: str) -> None:
        self.files_changed.append(FileChange(path=path, action=action, summary=summary))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
