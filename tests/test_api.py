from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.main import app


def auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_public_dashboard_and_account_scoped_actions() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "demo"
        assert health.json()["action_auth"]["enabled_user_count"] == 3

        preflight = client.options(
            "/api/auth/me",
            headers={
                "Origin": "https://zolpho.github.io",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://zolpho.github.io"

        overview = client.get("/api/overview")
        assert overview.status_code == 200
        overview_json = overview.json()
        assert overview_json["counts"]["all"] >= 3
        assert {account["id"] for account in overview_json["accounts"]} >= {"zolnode", "arnold"}
        assert all("gate_uid" not in account for account in overview_json["accounts"])

        bots = client.get("/api/bots")
        assert bots.status_code == 200
        items = bots.json()["items"]
        zolnode_bot = next(bot for bot in items if bot["account_id"] == "zolnode")
        arnold_bot = next(bot for bot in items if bot["account_id"] == "arnold")

        detail = client.get(f"/api/bots/{zolnode_bot['id']}")
        assert detail.status_code == 200
        assert "raw_detail" not in detail.json()["bot"]
        assert detail.json()["raw_data_requires_auth"] is True

        assert client.get(f"/api/bots/{zolnode_bot['id']}/raw").status_code == 401

        zolnode_headers = auth("zolnode", "zolnode-test-password")
        me = client.get("/api/auth/me", headers=zolnode_headers)
        assert me.status_code == 200
        assert me.json()["user"]["account_ids"] == ["zolnode"]

        own_raw = client.get(f"/api/bots/{zolnode_bot['id']}/raw", headers=zolnode_headers)
        assert own_raw.status_code == 200
        assert "raw_detail" in own_raw.json()["bot"]

        other_raw = client.get(f"/api/bots/{arnold_bot['id']}/raw", headers=zolnode_headers)
        assert other_raw.status_code == 403

        own_rule = client.post(
            "/api/alerts/rules",
            headers=zolnode_headers,
            json={
                "name": "Zolnode test rule",
                "metric": "pnl",
                "operator": "<",
                "threshold": -10,
                "bot_id": zolnode_bot["id"],
                "enabled": True,
                "cooldown_seconds": 60,
            },
        )
        assert own_rule.status_code == 200
        assert own_rule.json()["account_id"] == "zolnode"

        forbidden_rule = client.post(
            "/api/alerts/rules",
            headers=zolnode_headers,
            json={
                "name": "Arnold test rule",
                "metric": "pnl",
                "operator": "<",
                "threshold": -10,
                "bot_id": arnold_bot["id"],
                "enabled": True,
                "cooldown_seconds": 60,
            },
        )
        assert forbidden_rule.status_code == 403

        global_rule = client.post(
            "/api/alerts/rules",
            headers=zolnode_headers,
            json={
                "name": "Global test rule",
                "metric": "pnl",
                "operator": "<",
                "threshold": -10,
                "bot_id": None,
                "enabled": True,
                "cooldown_seconds": 60,
            },
        )
        assert global_rule.status_code == 403

        super_headers = auth("rootadmin", "rootadmin-test-password")
        global_rule = client.post(
            "/api/alerts/rules",
            headers=super_headers,
            json={
                "name": "Global test rule",
                "metric": "pnl",
                "operator": "<",
                "threshold": -10,
                "bot_id": None,
                "enabled": True,
                "cooldown_seconds": 60,
            },
        )
        assert global_rule.status_code == 200


def test_user_can_change_only_own_password() -> None:
    from app.config import get_settings

    settings = get_settings()
    users_path = settings.dashboard_users_file
    original = users_path.read_bytes()
    try:
        with TestClient(app) as client:
            old_headers = auth("zolnode", "zolnode-test-password")

            wrong_current = client.post(
                "/api/auth/change-password",
                headers=old_headers,
                json={
                    "current_password": "not-the-current-password",
                    "new_password": "zolnode-new-password",
                    "confirm_password": "zolnode-new-password",
                },
            )
            assert wrong_current.status_code == 400
            assert wrong_current.json()["detail"] == "Current password is incorrect"

            changed = client.post(
                "/api/auth/change-password",
                headers=old_headers,
                json={
                    "current_password": "zolnode-test-password",
                    "new_password": "zolnode-new-password",
                    "confirm_password": "zolnode-new-password",
                },
            )
            assert changed.status_code == 200
            assert changed.json()["user"]["username"] == "zolnode"

            assert client.get("/api/auth/me", headers=old_headers).status_code == 401
            new_headers = auth("zolnode", "zolnode-new-password")
            assert client.get("/api/auth/me", headers=new_headers).status_code == 200

            # Arnold's credentials and assignment are untouched.
            arnold_headers = auth("arnold", "arnold-test-password")
            assert client.get("/api/auth/me", headers=arnold_headers).status_code == 200
    finally:
        users_path.write_bytes(original)
