"""Testing stage.

Writes scenario-appropriate pytest files into url_shortener/tests, then
actually executes pytest as a subprocess against the whole tests/ directory
(not just the new file) -- so brownfield/ambiguous runs double as regression
tests for everything earlier scenarios built. Real validation, not narration.
"""

from __future__ import annotations

import subprocess
import sys

from orchestrator.agents.base import ActionResult, Agent
from orchestrator.context import RunContext
from orchestrator.workspace import Workspace


class TestingAgent(Agent):
    name = "testing_agent"

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def act(self, context: RunContext) -> ActionResult:
        if context.scenario_type == "greenfield":
            files = {
                "tests/__init__.py": "",
                "tests/conftest.py": _CONFTEST,
                "tests/test_api.py": _TEST_API_GREENFIELD,
                "tests/test_shortener.py": _TEST_SHORTENER,
            }
        elif context.scenario_type == "brownfield":
            files = {"tests/test_alias_ttl.py": _TEST_ALIAS_TTL}
        else:
            files = {"tests/test_reliability.py": _TEST_RELIABILITY}

        written = []
        for rel, content in files.items():
            self.workspace.write_file(rel, content, context=context, summary="test file for this scenario")
            written.append(rel)

        passed, summary, raw_output = self._run_pytest()

        context.test_results = {
            "passed": passed,
            "summary": summary,
            "files_written_this_stage": written,
            "raw_output_tail": raw_output[-4000:],
        }

        context.record_decision(
            stage="testing",
            actor=self.name,
            action="run_pytest",
            rationale=summary,
            data={"passed": passed, "new_test_files": written},
        )

        if not passed:
            return ActionResult(success=False, summary=summary, failure_class="bug")
        return ActionResult(success=True, summary=summary, data={"files": written})

    def _run_pytest(self) -> tuple[bool, str, str]:
        tests_dir = self.workspace.path("tests")
        if not tests_dir.exists():
            return False, "no tests directory found", ""

        result = subprocess.run(
            # -p no:cacheprovider: skip writing .pytest_cache entirely. We never
            # use --lf/--ff, so the cache buys nothing, and it's a recurring
            # source of Windows file-lock errors (OneDrive/AV) when the engine
            # later needs to snapshot/rollback/reset this directory.
            [sys.executable, "-m", "pytest", str(tests_dir), "-q", "-p", "no:cacheprovider"],
            cwd=str(self.workspace.product_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        passed = result.returncode == 0
        last_line = next((line for line in reversed(output.strip().splitlines()) if line.strip()), "")
        summary = f"pytest exit code {result.returncode}: {last_line}"
        return passed, summary, output


_CONFTEST = '''import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
'''

_TEST_API_GREENFIELD = '''from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_shorten_and_redirect():
    resp = client.post("/api/shorten", json={"long_url": "https://example.com/some/long/path"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["long_url"] == "https://example.com/some/long/path"
    code = body["short_code"]

    redirect_resp = client.get(f"/{code}", follow_redirects=False)
    assert redirect_resp.status_code == 302
    assert redirect_resp.headers["location"] == "https://example.com/some/long/path"


def test_shorten_rejects_invalid_url():
    resp = client.post("/api/shorten", json={"long_url": "not-a-url"})
    assert resp.status_code == 422


def test_analytics_tracks_clicks():
    resp = client.post("/api/shorten", json={"long_url": "https://example.com/analytics-test"})
    code = resp.json()["short_code"]

    client.get(f"/{code}", follow_redirects=False)
    client.get(f"/{code}", follow_redirects=False)

    analytics_resp = client.get(f"/api/analytics/{code}")
    assert analytics_resp.status_code == 200
    assert analytics_resp.json()["clicks"] == 2


def test_unknown_code_returns_404():
    resp = client.get("/does-not-exist-code")
    assert resp.status_code == 404

    analytics_resp = client.get("/api/analytics/does-not-exist-code")
    assert analytics_resp.status_code == 404
'''

_TEST_SHORTENER = '''from app.shortener import encode_base62, generate_short_code


def test_encode_base62_zero():
    assert encode_base62(0) == "0"


def test_encode_base62_is_deterministic():
    assert encode_base62(12345) == encode_base62(12345)


def test_generate_short_code_is_unique_for_sequential_counters():
    codes = {generate_short_code(i) for i in range(1000)}
    assert len(codes) == 1000
'''

_TEST_ALIAS_TTL = '''import time

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_custom_alias_is_honored():
    resp = client.post(
        "/api/shorten",
        json={"long_url": "https://example.com/alias-test", "custom_alias": "my-custom-alias"},
    )
    assert resp.status_code == 200
    assert resp.json()["short_code"] == "my-custom-alias"


def test_duplicate_alias_is_rejected():
    client.post("/api/shorten", json={"long_url": "https://example.com/a", "custom_alias": "taken-alias"})
    resp = client.post("/api/shorten", json={"long_url": "https://example.com/b", "custom_alias": "taken-alias"})
    assert resp.status_code == 409


def test_ttl_expiry_returns_410():
    resp = client.post(
        "/api/shorten", json={"long_url": "https://example.com/ttl-test", "ttl_seconds": 1}
    )
    assert resp.json()["expires_at"] is not None
    code = resp.json()["short_code"]

    time.sleep(1.2)

    redirect_resp = client.get(f"/{code}", follow_redirects=False)
    assert redirect_resp.status_code == 410


def test_existing_behavior_without_alias_or_ttl_is_unchanged():
    resp = client.post("/api/shorten", json={"long_url": "https://example.com/regression-check"})
    assert resp.status_code == 200
    assert resp.json()["expires_at"] is None
'''

_TEST_RELIABILITY = '''from fastapi.testclient import TestClient

from app.main import app, limiter

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_rate_limit_blocks_excessive_requests():
    limiter._buckets.clear()
    responses = [
        client.post("/api/shorten", json={"long_url": "https://example.com/rate-limit-check"})
        for _ in range(15)
    ]
    statuses = [r.status_code for r in responses]
    assert 429 in statuses


def test_invalid_url_still_returns_422():
    resp = client.post("/api/shorten", json={"long_url": "ftp://example.com"})
    assert resp.status_code == 422


def test_error_body_has_structured_envelope():
    resp = client.get("/does-not-exist-anywhere")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "short code not found"
    assert body["error"]["code"] == "http_error"
'''
