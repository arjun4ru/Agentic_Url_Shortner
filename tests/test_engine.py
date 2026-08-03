"""Unit tests for the orchestration engine's governance mechanics.

These use small synthetic graphs and scripted fake agents rather than the
real SDLC agents/gates, specifically so that retry, rollback, fallback,
replan, and safe-stop behavior can each be triggered deterministically and
verified in isolation. The three real scenarios (see scenarios/) separately
prove the same engine works end-to-end against the real product -- see
docs/TESTING_AND_TRADEOFFS.md for why the split is done this way.
"""

from __future__ import annotations

from orchestrator.agents.base import ActionResult, Agent
from orchestrator.audit import AuditLogger
from orchestrator.context import RunContext
from orchestrator.engine import Engine
from orchestrator.graph import Graph, Node
from orchestrator.policy import PolicyGuard
from orchestrator.workspace import Workspace


class ScriptedAgent(Agent):
    """An Agent whose act() replays a scripted list of outcomes in order,
    repeating the final one for any calls beyond the list's length."""

    def __init__(self, name, outcomes, fallback_result=None, on_call=None):
        self.name = name
        self.outcomes = outcomes
        self.fallback_result = fallback_result
        self.on_call = on_call
        self.call_count = 0

    def act(self, context: RunContext) -> ActionResult:
        self.call_count += 1
        if self.on_call:
            self.on_call(context)
        idx = min(self.call_count - 1, len(self.outcomes) - 1)
        return self.outcomes[idx]

    def fallback(self, context: RunContext) -> ActionResult:
        if self.fallback_result is None:
            raise NotImplementedError("no fallback configured for this test agent")
        return self.fallback_result


def make_env(tmp_path):
    policy = PolicyGuard(tmp_path)
    workspace = Workspace(tmp_path, "product", policy)
    run_log_dir = tmp_path / "run_log"
    audit = AuditLogger(run_id="test-run", log_path=run_log_dir / "audit.jsonl")
    return workspace, audit, run_log_dir


def make_context() -> RunContext:
    return RunContext.new(scenario_type="greenfield", requirement_text="irrelevant for engine tests",
                           scenario_dir="n/a")


def test_happy_path_all_stages_succeed_on_first_try(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)
    graph = Graph()
    graph.add_node(Node(name="a"))
    graph.add_node(Node(name="b", depends_on=("a",)))
    agents = {
        "a": ScriptedAgent("a", [ActionResult(True, "ok")]),
        "b": ScriptedAgent("b", [ActionResult(True, "ok")]),
    }

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(make_context())

    assert result.status == "released"
    events = audit.read_events()
    assert any(e["event_type"] == "stage_success" and e["stage"] == "a" for e in events)
    assert any(e["event_type"] == "stage_success" and e["stage"] == "b" for e in events)
    assert not any(e["event_type"] == "retry" for e in events)


def test_bounded_retry_then_success(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)
    graph = Graph()
    graph.add_node(Node(name="a", max_retries=2))
    agents = {
        "a": ScriptedAgent("a", [
            ActionResult(False, "transient failure", failure_class="bug"),
            ActionResult(True, "ok on retry"),
        ]),
    }
    context = make_context()

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(context)

    assert result.status == "released"
    assert context.stage_attempts["a"] == 2
    events = audit.read_events()
    assert any(e["event_type"] == "retry" for e in events)


def test_rollback_and_halt_when_retries_exhausted(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)

    def write_marker(_context):
        workspace.write_file("app/marker.txt", "written-during-failed-attempt")

    workspace.write_file("app/marker.txt", "pristine-before-run")

    graph = Graph()
    graph.add_node(Node(name="implementation", max_retries=1, failure_policy="rollback_halt"))
    agents = {
        "implementation": ScriptedAgent(
            "implementation",
            [ActionResult(False, "always fails", failure_class="bug")],
            on_call=write_marker,
        ),
    }

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(make_context())

    assert result.status == "halted"
    events = audit.read_events()
    assert any(e["event_type"] == "rollback" for e in events)
    # The snapshot taken before this stage's attempt should have been restored.
    assert workspace.read_file("app/marker.txt") == "pristine-before-run"


def test_fallback_used_when_retries_exhausted(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)
    graph = Graph()
    graph.add_node(Node(name="documentation", max_retries=1, failure_policy="fallback"))
    agents = {
        "documentation": ScriptedAgent(
            "documentation",
            [ActionResult(False, "doc generation broke", failure_class="bug")],
            fallback_result=ActionResult(True, "fallback stub written"),
        ),
    }

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(make_context())

    assert result.status == "released"
    events = audit.read_events()
    assert any(e["event_type"] == "fallback_used" for e in events)


def test_replan_jumps_back_to_target_node_and_recovers(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)
    graph = Graph()
    graph.add_node(Node(name="design"))
    graph.add_node(Node(name="implementation", depends_on=("design",)))
    graph.add_node(Node(name="testing", depends_on=("implementation",), max_retries=0,
                         failure_policy="replan", replan_target="design"))

    design_calls = []
    agents = {
        "design": ScriptedAgent("design", [ActionResult(True, "ok")], on_call=lambda c: design_calls.append(1)),
        "implementation": ScriptedAgent("implementation", [ActionResult(True, "ok")]),
        "testing": ScriptedAgent("testing", [
            ActionResult(False, "acceptance criterion mismatch", failure_class="design_issue"),
            ActionResult(True, "passes after redesign"),
        ]),
    }
    context = make_context()

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(context)

    assert result.status == "released"
    assert context.replan_count == 1
    assert len(design_calls) == 2  # once initially, once again after the replan
    events = audit.read_events()
    assert any(e["event_type"] == "replan" and e["target"] == "design" for e in events)


def test_non_design_level_failure_does_not_replan_and_halts_safely(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)
    graph = Graph()
    graph.add_node(Node(name="design"))
    graph.add_node(Node(name="testing", depends_on=("design",), max_retries=0,
                         failure_policy="replan", replan_target="design"))

    agents = {
        "design": ScriptedAgent("design", [ActionResult(True, "ok")]),
        "testing": ScriptedAgent("testing", [ActionResult(False, "flaky bug", failure_class="bug")]),
    }

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(make_context())

    assert result.status == "halted"
    events = audit.read_events()
    assert not any(e["event_type"] == "replan" for e in events)


def test_safe_stop_halts_gracefully_between_batches(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)
    graph = Graph()
    graph.add_node(Node(name="a"))
    graph.add_node(Node(name="b", depends_on=("a",)))

    def request_stop(context):
        context.stop_requested = True

    agents = {
        "a": ScriptedAgent("a", [ActionResult(True, "ok")], on_call=request_stop),
        "b": ScriptedAgent("b", [ActionResult(True, "ok")]),
    }

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(make_context())

    assert result.status == "halted"
    assert agents["b"].call_count == 0
    events = audit.read_events()
    assert any(e["event_type"] == "safe_stop" for e in events)


def test_parallel_batch_runs_both_nodes_before_synchronizing(tmp_path):
    workspace, audit, run_log_dir = make_env(tmp_path)
    graph = Graph()
    graph.add_node(Node(name="implementation"))
    graph.add_node(Node(name="testing", depends_on=("implementation",)))
    graph.add_node(Node(name="documentation", depends_on=("implementation",)))
    graph.add_node(Node(name="release", depends_on=("testing", "documentation")))

    agents = {
        "implementation": ScriptedAgent("implementation", [ActionResult(True, "ok")]),
        "testing": ScriptedAgent("testing", [ActionResult(True, "ok")]),
        "documentation": ScriptedAgent("documentation", [ActionResult(True, "ok")]),
        "release": ScriptedAgent("release", [ActionResult(True, "ok")]),
    }

    assert graph.topological_batches() == [["implementation"], ["documentation", "testing"], ["release"]]

    result = Engine(graph, agents, workspace, audit, run_log_dir).run(make_context())

    assert result.status == "released"
    assert agents["testing"].call_count == 1
    assert agents["documentation"].call_count == 1
