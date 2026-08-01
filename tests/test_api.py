from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_demo_dashboard_endpoints() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "demo"

        overview = client.get("/api/overview")
        assert overview.status_code == 200
        assert overview.json()["counts"]["all"] >= 3

        bots = client.get("/api/bots")
        assert bots.status_code == 200
        assert len(bots.json()["items"]) >= 3
        bot_id = bots.json()["items"][0]["id"]

        detail = client.get(f"/api/bots/{bot_id}")
        assert detail.status_code == 200
        assert "raw_detail" in detail.json()["bot"]
