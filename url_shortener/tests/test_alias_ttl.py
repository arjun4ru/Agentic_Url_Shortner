import time

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
