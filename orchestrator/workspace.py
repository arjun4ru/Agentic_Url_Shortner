"""File I/O boundary for agents: reads/writes the url_shortener/ product tree.

Centralizing writes here means every write goes through the PolicyGuard
(no path traversal, no obvious hardcoded secrets), every write is recorded
into RunContext.files_changed, and snapshot()/restore() give the engine a
real rollback mechanism (a plain directory copy, not a Git operation, to
stay dependency-free).
"""

from __future__ import annotations

import os
import shutil
import stat
import time
from pathlib import Path
from typing import Optional

from orchestrator.context import RunContext
from orchestrator.policy import PolicyGuard


class PolicyViolation(RuntimeError):
    pass


def _resilient_rmtree(path: Path, *, retries: int = 5, delay_seconds: float = 0.3) -> None:
    """shutil.rmtree that survives the transient Windows PermissionErrors caused
    by OneDrive/AV/editor file locks and read-only pycache/pytest-cache files.

    On each failed delete, clears the read-only attribute (if set) and retries
    a few times with a short backoff before giving up. This is deliberately
    defensive: a locked cache directory should never crash the whole CLI with
    an unhandled traceback (see docs/TESTING_AND_TRADEOFFS.md).
    """

    def _on_error(func, target_path, exc_info):
        try:
            os.chmod(target_path, stat.S_IWRITE)
            func(target_path)
        except Exception:
            pass  # last resort: swallow here, outer retry loop decides if this is fatal

    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_on_error)
            return
        except FileNotFoundError:
            return
        except (PermissionError, OSError) as exc:
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError(f"could not remove {path} after {retries} attempts (likely locked by another "
                        f"process, e.g. OneDrive sync or an editor): {last_error}") from last_error


class Workspace:
    def __init__(self, project_root: Path, product_dir_name: str, policy: PolicyGuard) -> None:
        self.project_root = project_root.resolve()
        self.product_root = (self.project_root / product_dir_name).resolve()
        self.policy = policy

    def path(self, relpath: str) -> Path:
        return self.product_root / relpath

    def exists(self, relpath: str) -> bool:
        return self.path(relpath).exists()

    def read_file(self, relpath: str) -> Optional[str]:
        p = self.path(relpath)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    def write_file(self, relpath: str, content: str, *, context: Optional[RunContext] = None,
                    summary: str = "") -> None:
        target = self.path(relpath)

        guard_result = self.policy.check_file_write(target)
        if not guard_result.passed:
            raise PolicyViolation(guard_result.reason)

        secret_scan = self.policy.scan_for_secrets(content, filename=relpath)
        if not secret_scan.passed:
            raise PolicyViolation(secret_scan.reason)

        already_existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        if context is not None:
            context.record_file_change(
                path=str(target.relative_to(self.project_root)),
                action="modified" if already_existed else "created",
                summary=summary or ("modified" if already_existed else "created"),
            )

    def list_files(self, pattern: str = "**/*.py") -> list[Path]:
        if not self.product_root.exists():
            return []
        return sorted(self.product_root.glob(pattern))

    def snapshot(self, snapshots_dir: Path, name: str) -> Optional[Path]:
        if not self.product_root.exists():
            return None
        dest = snapshots_dir / name
        if dest.exists():
            _resilient_rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Exclude cache directories: they're transient build artifacts, not
        # product state, and are a common source of Windows file-lock errors
        # (see docs/TESTING_AND_TRADEOFFS.md).
        ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        shutil.copytree(self.product_root, dest, ignore=ignore)
        return dest

    def restore(self, snapshot_path: Path) -> None:
        if self.product_root.exists():
            _resilient_rmtree(self.product_root)
        if snapshot_path.exists():
            shutil.copytree(snapshot_path, self.product_root)
        else:
            self.product_root.mkdir(parents=True, exist_ok=True)

    def reset(self) -> None:
        """Wipe the entire product tree. Used by the greenfield scenario to
        guarantee a true "from scratch" build regardless of what a prior
        scenario run may have left on disk (see docs/TESTING_AND_TRADEOFFS.md
        for the failure mode this prevents: re-running greenfield on top of
        an already-evolved brownfield/ambiguous tree leaving stale files
        behind that reference symbols the fresh code no longer has)."""
        if self.product_root.exists():
            _resilient_rmtree(self.product_root)
