"""Command-line entrypoint for the orchestrator.

    python -m orchestrator.cli run scenarios/01_greenfield_build_shortener
    python -m orchestrator.cli run scenarios/02_brownfield_alias_and_ttl --interactive
    python -m orchestrator.cli show-run scenarios/01_greenfield_build_shortener
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Tuple

from orchestrator import gates
from orchestrator.agents.design_agent import DesignAgent
from orchestrator.agents.documentation_agent import DocumentationAgent
from orchestrator.agents.implementation_agent import ImplementationAgent
from orchestrator.agents.release_agent import ReleaseAgent
from orchestrator.agents.requirements_agent import RequirementsAgent
from orchestrator.agents.testing_agent import TestingAgent
from orchestrator.approvals import ApprovalManager
from orchestrator.audit import AuditLogger, events_for_run, format_timeline, latest_run_id, read_events
from orchestrator.context import RunContext
from orchestrator.engine import Engine
from orchestrator.graph import build_default_sdlc_graph
from orchestrator.metrics import compute_metrics, format_metrics
from orchestrator.policy import PolicyGuard
from orchestrator.workspace import Workspace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCT_DIR_NAME = "url_shortener"
VALID_SCENARIO_TYPES = ("greenfield", "brownfield", "ambiguous")


def _parse_requirement_file(path: Path) -> Tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    scenario_type = None
    kept_lines = []
    for line in text.splitlines():
        if line.strip().lower().startswith("type:"):
            scenario_type = line.split(":", 1)[1].strip().lower()
            continue
        kept_lines.append(line)

    if scenario_type not in VALID_SCENARIO_TYPES:
        raise ValueError(
            f"{path} must contain a line like 'Type: greenfield' "
            f"(one of {VALID_SCENARIO_TYPES}); got {scenario_type!r}"
        )
    return scenario_type, "\n".join(kept_lines).strip()


def build_engine(scenario_dir: Path, *, interactive: bool) -> Tuple[Engine, AuditLogger, Path]:
    run_log_dir = scenario_dir / "run_log"

    policy = PolicyGuard(PROJECT_ROOT)
    workspace = Workspace(PROJECT_ROOT, PRODUCT_DIR_NAME, policy)

    audit = AuditLogger(run_id="pending", log_path=run_log_dir / "audit.jsonl")
    approvals = ApprovalManager(mode="interactive" if interactive else "auto", audit=audit)

    graph = build_default_sdlc_graph(
        requirements_exit=gates.requirements_exit_gate,
        design_exit=gates.design_exit_gate,
        implementation_exit=gates.implementation_exit_gate,
        testing_exit=gates.testing_exit_gate,
        documentation_exit=gates.documentation_exit_gate,
        release_exit=gates.release_exit_gate,
        design_entry=gates.design_entry_gate,
        implementation_entry=gates.implementation_entry_gate,
        release_entry=gates.release_entry_gate,
    )

    agents = {
        "requirements": RequirementsAgent(approvals),
        "design": DesignAgent(approvals, workspace),
        "implementation": ImplementationAgent(workspace),
        "testing": TestingAgent(workspace),
        "documentation": DocumentationAgent(workspace),
        "release_readiness": ReleaseAgent(approvals, policy, run_log_dir),
    }

    engine = Engine(graph, agents, workspace, audit, run_log_dir)
    return engine, audit, run_log_dir


def cmd_run(args: argparse.Namespace) -> int:
    scenario_dir = Path(args.scenario_dir).resolve()
    requirement_path = scenario_dir / "requirement.md"
    if not requirement_path.exists():
        print(f"error: {requirement_path} not found", file=sys.stderr)
        return 1

    try:
        scenario_type, requirement_text = _parse_requirement_file(requirement_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    engine, audit, run_log_dir = build_engine(scenario_dir, interactive=args.interactive)

    context = RunContext.new(
        scenario_type=scenario_type,
        requirement_text=requirement_text,
        scenario_dir=str(scenario_dir),
    )
    audit.run_id = context.run_id

    print(f"Starting run {context.run_id}  (scenario: {scenario_dir.name}, type={scenario_type})")
    print(f"Approval mode: {'interactive' if args.interactive else 'auto-approve'}\n")

    result = engine.run(context)

    context_path = run_log_dir / "context.json"
    result.save(context_path)

    # The audit log is append-only across every run of this scenario -- scope
    # metrics to just this run's events, otherwise e.g. end-to-end latency
    # would silently include the time since an earlier, unrelated run.
    events = events_for_run(audit.read_events(), context.run_id)
    metrics = compute_metrics(events)

    print("\n" + "=" * 72)
    print(f"RUN {result.run_id}  ->  status: {result.status.upper()}")
    print("=" * 72)
    print(format_metrics(metrics))
    print("-" * 72)
    print(f"Audit log:      {audit.log_path}")
    print(f"Run context:    {context_path}")
    if result.status == "released":
        print(f"Summary report: {run_log_dir / 'summary.md'}")
    print("=" * 72)

    return 0 if result.status == "released" else 2


def cmd_show_run(args: argparse.Namespace) -> int:
    scenario_dir = Path(args.scenario_dir).resolve()
    audit_path = scenario_dir / "run_log" / "audit.jsonl"
    all_events = read_events(audit_path)
    if not all_events:
        print(f"no audit events found at {audit_path}")
        return 1
    run_id = latest_run_id(all_events)
    events = events_for_run(all_events, run_id)
    print(f"showing most recent run: {run_id}\n")
    print(format_timeline(events))
    print("\n" + "-" * 72)
    print(format_metrics(compute_metrics(events)))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrator", description="Agentic SDLC orchestrator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run a scenario end-to-end through the orchestrator")
    run_parser.add_argument("scenario_dir", help="path to a scenario directory containing requirement.md")
    run_parser.add_argument(
        "--interactive", action="store_true",
        help="prompt for real human approval at checkpoints instead of auto-approving",
    )
    run_parser.set_defaults(func=cmd_run)

    show_parser = sub.add_parser("show-run", help="print the audit timeline + metrics for a scenario's run")
    show_parser.add_argument("scenario_dir", help="path to a scenario directory containing run_log/audit.jsonl")
    show_parser.set_defaults(func=cmd_show_run)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - last-resort safety net for the CLI entrypoint
        print(f"\nerror: run aborted unexpectedly: {exc}", file=sys.stderr)
        print("This is unexpected -- please check run_log/audit.jsonl for the last recorded "
              "event and re-run.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
