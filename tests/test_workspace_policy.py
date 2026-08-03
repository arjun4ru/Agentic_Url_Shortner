import pytest

from orchestrator.context import RunContext
from orchestrator.policy import PolicyGuard
from orchestrator.workspace import PolicyViolation, Workspace


def make_workspace(tmp_path):
    policy = PolicyGuard(tmp_path)
    workspace = Workspace(tmp_path, "product", policy)
    return workspace, policy


def test_write_and_read_file_roundtrip(tmp_path):
    workspace, _ = make_workspace(tmp_path)
    workspace.write_file("app/hello.txt", "hello world")
    assert workspace.read_file("app/hello.txt") == "hello world"


def test_write_records_file_change_in_context(tmp_path):
    workspace, _ = make_workspace(tmp_path)
    context = RunContext.new(scenario_type="greenfield", requirement_text="x", scenario_dir="x")

    workspace.write_file("app/a.py", "print(1)", context=context, summary="unit test write")
    assert len(context.files_changed) == 1
    assert context.files_changed[0].action == "created"

    workspace.write_file("app/a.py", "print(2)", context=context, summary="unit test overwrite")
    assert context.files_changed[1].action == "modified"


def test_policy_blocks_path_traversal_outside_project_root(tmp_path):
    workspace, _ = make_workspace(tmp_path)
    with pytest.raises(PolicyViolation):
        workspace.write_file("../../escape.py", "print(1)")


def test_policy_blocks_hardcoded_secret(tmp_path):
    workspace, _ = make_workspace(tmp_path)
    with pytest.raises(PolicyViolation):
        workspace.write_file("app/bad.py", 'password = "supersecret123"')


def test_policy_allows_normal_content(tmp_path):
    workspace, policy = make_workspace(tmp_path)
    workspace.write_file("app/good.py", "def add(a, b):\n    return a + b\n")
    assert policy.violations == []


def test_snapshot_and_restore_round_trip(tmp_path):
    workspace, _ = make_workspace(tmp_path)
    workspace.write_file("app/a.py", "version = 1")

    snapshot_path = workspace.snapshot(tmp_path / "snapshots", "before_change")

    workspace.write_file("app/a.py", "version = 2")
    assert workspace.read_file("app/a.py") == "version = 2"

    workspace.restore(snapshot_path)
    assert workspace.read_file("app/a.py") == "version = 1"
