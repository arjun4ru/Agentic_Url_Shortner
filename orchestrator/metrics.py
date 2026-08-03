"""Reliability metrics computed from the audit log.

Deliberately derived purely from audit events (not tracked separately in
parallel) so the audit log is the single source of truth -- metrics can
always be recomputed/replayed from it.
"""

from __future__ import annotations

from typing import Any


def compute_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {}

    start_ts = events[0]["timestamp"]
    end_ts = events[-1]["timestamp"]

    stage_starts = [e for e in events if e["event_type"] == "stage_start"]
    stage_successes = [e for e in events if e["event_type"] == "stage_success"]
    fallback_used = [e for e in events if e["event_type"] == "fallback_used"]
    retries = [e for e in events if e["event_type"] == "retry"]
    rollbacks = [e for e in events if e["event_type"] == "rollback"]
    replans = [e for e in events if e["event_type"] == "replan"]
    halts = [e for e in events if e["event_type"] == "run_halted"]

    attempted_stages = {e["stage"] for e in stage_starts}
    succeeded_stages = {e["stage"] for e in stage_successes} | {e["stage"] for e in fallback_used}

    stage_level_success_rate = (len(succeeded_stages) / len(attempted_stages)) if attempted_stages else 0.0
    attempt_level_success_rate = (len(stage_successes) / len(stage_starts)) if stage_starts else 0.0

    # MTTR: pair each failure event for a stage with the next success/fallback
    # event for that same stage, and average the time deltas.
    pending_failures: dict[str, list[float]] = {}
    recoveries: list[float] = []
    for e in events:
        if e["event_type"] in ("stage_failure", "exit_gate_failed"):
            pending_failures.setdefault(e["stage"], []).append(e["timestamp"])
        elif e["event_type"] in ("stage_success", "fallback_used"):
            queue = pending_failures.get(e["stage"])
            if queue:
                failure_ts = queue.pop(0)
                recoveries.append(e["timestamp"] - failure_ts)

    mttr = (sum(recoveries) / len(recoveries)) if recoveries else 0.0

    return {
        "end_to_end_latency_seconds": round(end_ts - start_ts, 3),
        "stages_attempted": len(attempted_stages),
        "stages_succeeded": len(succeeded_stages),
        "stage_level_success_rate": round(stage_level_success_rate, 3),
        "attempt_level_success_rate": round(attempt_level_success_rate, 3),
        "retry_count": len(retries),
        "rollback_count": len(rollbacks),
        "replan_count": len(replans),
        "fallback_count": len(fallback_used),
        "run_halted": len(halts) > 0,
        "mttr_seconds": round(mttr, 3),
        "recovery_events": len(recoveries),
    }


def format_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "(no events to compute metrics from)"
    return "\n".join(f"{k:<28} {v}" for k, v in metrics.items())
