"""Audit-grade observability: every orchestration event as a JSON line.

Durable (survives process restart), greppable, and replayable -- this is
what "show-run" and the metrics module read from. Deliberately just a flat
append-only file rather than a database: sufficient for audit-grade
traceability of a single run without adding an external dependency.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional


@dataclass
class AuditEvent:
    timestamp: float
    run_id: str
    event_type: str
    stage: str
    fields: dict[str, Any]


class AuditLogger:
    def __init__(self, run_id: str, log_path: Path) -> None:
        self.run_id = run_id
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, stage: str, **fields: Any) -> None:
        event = {
            "timestamp": time.time(),
            "run_id": self.run_id,
            "event_type": event_type,
            "stage": stage,
            **fields,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def read_events(self) -> list[dict[str, Any]]:
        return read_events(self.log_path)


def read_events(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    events = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def iter_events(log_path: Path) -> Iterator[dict[str, Any]]:
    for event in read_events(log_path):
        yield event


def latest_run_id(events: list[dict[str, Any]]) -> Optional[str]:
    """The audit log is append-only across every run of a scenario, so the
    last event's run_id identifies the most recent run."""
    return events[-1]["run_id"] if events else None


def events_for_run(events: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    """Scope a flat, multi-run audit log down to a single run.

    Both the timeline and the reliability metrics must only ever be computed
    over one run's events -- otherwise (e.g.) end-to-end latency silently
    becomes "time since some earlier, unrelated run happened to start" once
    the log accumulates more than one run, which produces nonsensical
    numbers without ever raising an error.
    """
    return [e for e in events if e.get("run_id") == run_id]


def format_timeline(events: list[dict[str, Any]]) -> str:
    lines = []
    start = events[0]["timestamp"] if events else 0
    for e in events:
        t = e["timestamp"] - start
        extra = {k: v for k, v in e.items() if k not in ("timestamp", "run_id", "event_type", "stage")}
        extra_str = f" {extra}" if extra else ""
        lines.append(f"[+{t:6.2f}s] {e['stage']:<18} {e['event_type']:<16}{extra_str}")
    return "\n".join(lines)
