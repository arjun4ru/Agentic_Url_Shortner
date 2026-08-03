"""Agent interface.

Every stage in the SDLC graph is executed by exactly one Agent. In this
prototype every Agent is deterministic/rule-based (see docs/DESIGN.md §2 and
§9 for why) -- but the interface itself doesn't know or care how an agent
produces its result, so a real LLM-backed agent could implement this same
interface later without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from orchestrator.context import RunContext


@dataclass
class ActionResult:
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    # used by the engine to decide replan vs plain retry on failure:
    # "bug" | "design_issue" | "environment" | None
    failure_class: Optional[str] = None


class Agent:
    """Base class. Subclasses implement act()."""

    name: str = "agent"

    def act(self, context: RunContext) -> ActionResult:  # pragma: no cover - interface
        raise NotImplementedError

    def fallback(self, context: RunContext) -> ActionResult:
        """Optional degraded-mode action used when failure_policy == 'fallback'
        and normal act() has exhausted its retries. Default: no fallback available."""
        raise NotImplementedError(f"{self.name} has no fallback behavior")
