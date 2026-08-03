import pytest

from orchestrator.graph import Graph, GraphError, Node


def test_topological_batches_linear_chain():
    g = Graph()
    g.add_node(Node(name="a"))
    g.add_node(Node(name="b", depends_on=("a",)))
    g.add_node(Node(name="c", depends_on=("b",)))
    assert g.topological_batches() == [["a"], ["b"], ["c"]]


def test_topological_batches_parallel_fork_join():
    g = Graph()
    g.add_node(Node(name="a"))
    g.add_node(Node(name="b", depends_on=("a",)))
    g.add_node(Node(name="c", depends_on=("a",)))
    g.add_node(Node(name="d", depends_on=("b", "c")))

    batches = g.topological_batches()

    assert batches[0] == ["a"]
    assert set(batches[1]) == {"b", "c"}
    assert batches[2] == ["d"]


def test_duplicate_node_raises():
    g = Graph()
    g.add_node(Node(name="a"))
    with pytest.raises(GraphError):
        g.add_node(Node(name="a"))


def test_unknown_dependency_raises():
    g = Graph()
    with pytest.raises(GraphError):
        g.add_node(Node(name="b", depends_on=("missing",)))


def test_cycle_detection():
    # Can't add a genuine cycle through add_node (deps must pre-exist), so
    # build the internal state directly to exercise topological_batches'
    # cycle guard.
    g = Graph()
    g.add_node(Node(name="a"))
    g.add_node(Node(name="b", depends_on=("a",)))
    # Manually rewire "a" to (invalidly) depend on "b" to fabricate a cycle.
    g.get("a").depends_on = ("b",)
    with pytest.raises(GraphError):
        g.topological_batches()
