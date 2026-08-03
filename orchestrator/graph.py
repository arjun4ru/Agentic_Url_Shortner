"""Explicit dependency graph for the SDLC pipeline.

This is a small, generic DAG implementation (nodes + edges + topological
batching) rather than a hardcoded 6-step sequence, so that:

  * entry/exit gates are attached data on each node, not scattered ifs
  * "which stages can run in parallel" falls naturally out of the graph
    structure (any stages with no dependency between them, at the same
    depth, land in the same batch)
  * dynamic re-planning (jumping back to an earlier node) is just "resume
    batched execution starting from a different node index" -- no special
    casing needed in the engine
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from orchestrator.context import RunContext


@dataclass
class GateResult:
    passed: bool
    reason: str = ""


# A gate inspects the run so far and decides whether a stage may start/advance.
GateFn = Callable[[RunContext], GateResult]


def always_pass(_: RunContext) -> GateResult:
    return GateResult(passed=True, reason="no preconditions")


@dataclass
class Node:
    name: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    entry_gate: GateFn = always_pass
    exit_gate: GateFn = always_pass
    max_retries: int = 2
    # what to do once retries are exhausted: "rollback_halt" | "fallback" | "replan"
    failure_policy: str = "rollback_halt"
    # only used when failure_policy == "replan": which node to jump back to
    replan_target: Optional[str] = None


class GraphError(ValueError):
    pass


class Graph:
    """A minimal directed acyclic graph with topological batching."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def add_node(self, node: Node) -> None:
        if node.name in self._nodes:
            raise GraphError(f"duplicate node: {node.name}")
        for dep in node.depends_on:
            if dep not in self._nodes:
                raise GraphError(
                    f"node {node.name!r} depends on unknown node {dep!r} "
                    "(add dependencies before dependents)"
                )
        self._nodes[node.name] = node

    def get(self, name: str) -> Node:
        try:
            return self._nodes[name]
        except KeyError:
            raise GraphError(f"unknown node: {name}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    @property
    def node_names(self) -> list[str]:
        return list(self._nodes.keys())

    def topological_batches(self) -> list[list[str]]:
        """Kahn's algorithm layered by depth -> list of parallelizable batches."""
        in_degree = {name: len(n.depends_on) for name, n in self._nodes.items()}
        dependents: dict[str, list[str]] = {name: [] for name in self._nodes}
        for name, n in self._nodes.items():
            for dep in n.depends_on:
                dependents[dep].append(name)

        batches: list[list[str]] = []
        remaining = dict(in_degree)
        frontier = sorted([n for n, d in remaining.items() if d == 0])

        visited = 0
        while frontier:
            batches.append(frontier)
            next_frontier: list[str] = []
            for name in frontier:
                visited += 1
                for dependent in dependents[name]:
                    remaining[dependent] -= 1
                    if remaining[dependent] == 0:
                        next_frontier.append(dependent)
            frontier = sorted(next_frontier)

        if visited != len(self._nodes):
            raise GraphError("graph has a cycle; cannot topologically sort")

        return batches

    def batch_index_of(self, name: str, batches: list[list[str]]) -> int:
        for i, batch in enumerate(batches):
            if name in batch:
                return i
        raise GraphError(f"node {name!r} not found in any batch")


def build_default_sdlc_graph(
    *,
    requirements_exit: GateFn,
    design_exit: GateFn,
    implementation_exit: GateFn,
    testing_exit: GateFn,
    documentation_exit: GateFn,
    release_exit: GateFn,
    design_entry: GateFn = always_pass,
    implementation_entry: GateFn = always_pass,
    release_entry: GateFn = always_pass,
) -> Graph:
    """The fixed 6-stage SDLC graph used for every scenario.

    Requirements -> Design -> Implementation -> {Testing, Documentation} -> ReleaseReadiness

    Testing and Documentation share the same dependency (Implementation) and
    have no edge between each other, so topological_batches() naturally puts
    them in the same batch (parallel execution), and ReleaseReadiness -- which
    depends on both -- becomes the synchronization point.
    """
    graph = Graph()
    graph.add_node(Node(name="requirements", depends_on=(), exit_gate=requirements_exit,
                         failure_policy="rollback_halt"))
    graph.add_node(Node(name="design", depends_on=("requirements",), entry_gate=design_entry,
                         exit_gate=design_exit, failure_policy="rollback_halt"))
    graph.add_node(Node(name="implementation", depends_on=("design",), entry_gate=implementation_entry,
                         exit_gate=implementation_exit, failure_policy="rollback_halt"))
    graph.add_node(Node(name="testing", depends_on=("implementation",), exit_gate=testing_exit,
                         failure_policy="replan", replan_target="design"))
    graph.add_node(Node(name="documentation", depends_on=("implementation",), exit_gate=documentation_exit,
                         failure_policy="fallback"))
    graph.add_node(Node(name="release_readiness", depends_on=("testing", "documentation"), entry_gate=release_entry,
                         exit_gate=release_exit, failure_policy="rollback_halt"))
    return graph
