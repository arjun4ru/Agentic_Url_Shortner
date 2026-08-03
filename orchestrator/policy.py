"""Policy guardrails: security / compliance / change-control checks.

Deliberately simple rule checks rather than a full policy engine (see
docs/DESIGN.md limitations) -- but they are real, enforced checks, not
decoration: writes that fail them are rejected by the Workspace before
touching disk, and release is blocked if any guardrail failed during the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS access key id
    re.compile(r"(?i)api[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)password\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----"),
]


@dataclass
class GuardResult:
    passed: bool
    reason: str = "ok"


class PolicyGuard:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.violations: list[str] = []

    def check_file_write(self, target_path: Path) -> GuardResult:
        resolved = target_path.resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError:
            result = GuardResult(False, f"blocked write outside project root: {resolved}")
            self.violations.append(result.reason)
            return result
        return GuardResult(True)

    def scan_for_secrets(self, content: str, *, filename: str = "") -> GuardResult:
        for pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                result = GuardResult(False, f"possible hardcoded secret detected in {filename or '<content>'}")
                self.violations.append(result.reason)
                return result
        return GuardResult(True)

    def require_ambiguity_resolution(self, context) -> GuardResult:  # type: ignore[no-untyped-def]
        unresolved = [a for a in context.ambiguities if not a.get("resolved")]
        if unresolved:
            result = GuardResult(False, f"{len(unresolved)} unresolved ambiguity(ies) require human approval")
            self.violations.append(result.reason)
            return result
        return GuardResult(True)

    def pre_release_check(self, context) -> GuardResult:  # type: ignore[no-untyped-def]
        if self.violations:
            return GuardResult(False, f"{len(self.violations)} guardrail violation(s) recorded during this run")
        if context.test_results.get("passed") is not True:
            return GuardResult(False, "tests did not pass")
        if not context.doc_artifacts:
            return GuardResult(False, "no documentation artifacts produced")
        return GuardResult(True)
