from fastapi.testclient import TestClient

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
