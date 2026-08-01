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
        overview_json = overview.json()
        assert overview_json["counts"]["all"] >= 3
        assert {account["id"] for account in overview_json["accounts"]} >= {"zolnode", "arnold"}

        zolnode = client.get("/api/overview?account_id=zolnode")
        assert zolnode.status_code == 200
        assert zolnode.json()["account_id"] == "zolnode"
        assert zolnode.json()["counts"]["all"] == 2

        bots = client.get("/api/bots")
        assert bots.status_code == 200
        assert len(bots.json()["items"]) >= 3
        assert all("account_id" in bot for bot in bots.json()["items"])

        arnold = client.get("/api/bots?account_id=arnold")
        assert arnold.status_code == 200
        assert {bot["account_id"] for bot in arnold.json()["items"]} == {"arnold"}

        bot_id = bots.json()["items"][0]["id"]

        detail = client.get(f"/api/bots/{bot_id}")
        assert detail.status_code == 200
        assert "raw_detail" in detail.json()["bot"]
