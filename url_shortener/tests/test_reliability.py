from fastapi.testclient import TestClient

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
