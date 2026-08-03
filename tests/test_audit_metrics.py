from orchestrator.audit import AuditLogger, read_events
from orchestrator.metrics import compute_metrics


def test_audit_logger_writes_jsonl_and_reads_back(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit = AuditLogger(run_id="run-1", log_path=log_path)

    audit.log("stage_start", "requirements", attempt=1)
    audit.log("stage_success", "requirements", attempt=1)

    events = read_events(log_path)
    assert len(events) == 2
    assert events[0]["event_type"] == "stage_start"
    assert events[1]["run_id"] == "run-1"


def test_read_events_on_missing_file_returns_empty_list(tmp_path):
    assert read_events(tmp_path / "does_not_exist.jsonl") == []


def test_compute_metrics_counts_retries_success_rate_and_mttr():
    events = [
        {"timestamp": 0.0, "run_id": "r", "event_type": "run_start", "stage": "orchestrator"},
        {"timestamp": 1.0, "run_id": "r", "event_type": "stage_start", "stage": "a"},
        {"timestamp": 1.1, "run_id": "r", "event_type": "stage_failure", "stage": "a"},
        {"timestamp": 1.2, "run_id": "r", "event_type": "retry", "stage": "a"},
        {"timestamp": 1.3, "run_id": "r", "event_type": "stage_start", "stage": "a"},
        {"timestamp": 1.4, "run_id": "r", "event_type": "stage_success", "stage": "a"},
        {"timestamp": 2.0, "run_id": "r", "event_type": "run_end", "stage": "orchestrator"},
    ]

    metrics = compute_metrics(events)

    assert metrics["retry_count"] == 1
    assert metrics["stages_attempted"] == 1
    assert metrics["stages_succeeded"] == 1
    assert metrics["stage_level_success_rate"] == 1.0
    assert metrics["attempt_level_success_rate"] == 0.5  # 1 success out of 2 stage_start events
    assert round(metrics["mttr_seconds"], 2) == 0.3  # 1.4 - 1.1
    assert metrics["end_to_end_latency_seconds"] == 2.0


def test_compute_metrics_on_empty_events_returns_empty_dict():
    assert compute_metrics([]) == {}
