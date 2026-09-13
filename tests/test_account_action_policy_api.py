from __future__ import annotations

import base64
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import session_scope
from app.main import app
from app.models import GateAccount


def _auth(
    username: str,
    password: str,
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode("ascii")

    return {
        "Authorization": f"Basic {token}"
    }


ROOT = _auth(
    "rootadmin",
    "rootadmin-test-password",
)

OPERATOR = _auth(
    "zolnode",
    "zolnode-test-password",
)


def _new_account_id(
    prefix: str,
) -> str:
    return (
        prefix
        + "-"
        + uuid4().hex[:12]
    )


def _create_account(
    account_id: str,
) -> None:
    with session_scope() as db:
        if db.get(
            GateAccount,
            account_id,
        ) is not None:
            return

        db.add(
            GateAccount(
                id=account_id,
                name=account_id,
                account_type="subaccount",
                enabled=True,
                configured=True,
            )
        )


def _item_by_id(
    payload: dict,
    account_id: str,
) -> dict:
    return next(
        item
        for item in payload["items"]
        if item["account_id"] == account_id
    )


def test_policy_admin_routes_require_super_admin() -> None:
    with TestClient(app) as client:
        account_id = _new_account_id(
            "policy-auth"
        )

        _create_account(
            account_id
        )

        assert (
            client.get(
                "/api/auth/account-policies"
            ).status_code
            == 401
        )

        assert (
            client.get(
                "/api/auth/account-policies",
                headers=OPERATOR,
            ).status_code
            == 403
        )

        history_path = (
            "/api/auth/account-policies/"
            f"{account_id}/events"
        )

        assert (
            client.get(
                history_path,
                headers=OPERATOR,
            ).status_code
            == 403
        )

        update_path = (
            "/api/auth/account-policies/"
            + account_id
        )

        denied = client.patch(
            update_path,
            headers=OPERATOR,
            json={
                "trading_enabled": False,
            },
        )

        assert denied.status_code == 403


def test_rootadmin_can_list_update_and_audit_policy() -> None:
    with TestClient(app) as client:
        account_id = _new_account_id(
            "policy-admin"
        )

        _create_account(
            account_id
        )

        listed = client.get(
            "/api/auth/account-policies",
            headers=ROOT,
        )

        assert listed.status_code == 200

        body = listed.json()

        assert body["capabilities"] == [
            "transfers",
            "withdrawals",
            "trading",
        ]

        assert (
            body["gate_write_performed"]
            is False
        )

        initial = _item_by_id(
            body,
            account_id,
        )

        # This account was created after startup migration,
        # so the policy service must expose the missing row
        # as fail-closed.
        assert initial["exists"] is False
        assert (
            initial["transfers_enabled"]
            is False
        )
        assert (
            initial["withdrawals_enabled"]
            is False
        )
        assert (
            initial["trading_enabled"]
            is False
        )

        update_path = (
            "/api/auth/account-policies/"
            + account_id
        )

        updated = client.patch(
            update_path,
            headers=ROOT,
            json={
                "transfers_enabled": True,
                "withdrawals_enabled": False,
                "trading_enabled": True,
                "reason": (
                    "Initial rootadmin policy"
                ),
            },
        )

        assert updated.status_code == 200

        result = updated.json()

        assert result["status"] == "updated"
        assert result["created"] is True
        assert result["changed"] is True
        assert (
            result["gate_write_performed"]
            is False
        )

        policy = result["policy"]

        assert policy["account_id"] == account_id
        assert policy["exists"] is True
        assert (
            policy["transfers_enabled"]
            is True
        )
        assert (
            policy["withdrawals_enabled"]
            is False
        )
        assert (
            policy["trading_enabled"]
            is True
        )
        assert (
            policy["updated_by"]
            == "rootadmin"
        )

        assert {
            event["capability"]
            for event in result["events"]
        } == {
            "transfers",
            "withdrawals",
            "trading",
        }

        assert all(
            event["old_enabled"] is None
            for event in result["events"]
        )

        assert all(
            event["username"] == "rootadmin"
            for event in result["events"]
        )

        assert all(
            event["reason"]
            == "Initial rootadmin policy"
            for event in result["events"]
        )

        assert all(
            event["metadata"]
            == {
                "source": (
                    "rootadmin_policy_api"
                ),
                "auth_source": "file",
            }
            for event in result["events"]
        )

        history = client.get(
            (
                "/api/auth/account-policies/"
                f"{account_id}/events"
            ),
            headers=ROOT,
        )

        assert history.status_code == 200

        history_body = history.json()

        assert (
            history_body["account_id"]
            == account_id
        )

        assert (
            history_body["gate_write_performed"]
            is False
        )

        assert len(
            history_body["items"]
        ) == 3

        repeated = client.patch(
            update_path,
            headers=ROOT,
            json={
                "transfers_enabled": True,
                "withdrawals_enabled": False,
                "trading_enabled": True,
                "reason": "No-op repeat",
            },
        )

        assert repeated.status_code == 200

        repeated_body = repeated.json()

        assert (
            repeated_body["status"]
            == "unchanged"
        )
        assert (
            repeated_body["changed"]
            is False
        )
        assert (
            repeated_body["events"]
            == []
        )

        history_after = client.get(
            (
                "/api/auth/account-policies/"
                f"{account_id}/events"
            ),
            headers=ROOT,
        ).json()

        assert len(
            history_after["items"]
        ) == 3


def test_policy_api_rejects_invalid_or_unknown_updates() -> None:
    with TestClient(app) as client:
        account_id = _new_account_id(
            "policy-validation"
        )

        _create_account(
            account_id
        )

        missing_capability = client.patch(
            (
                "/api/auth/account-policies/"
                + account_id
            ),
            headers=ROOT,
            json={
                "reason": "Nothing selected",
            },
        )

        assert (
            missing_capability.status_code
            == 422
        )

        coerced_boolean = client.patch(
            (
                "/api/auth/account-policies/"
                + account_id
            ),
            headers=ROOT,
            json={
                "trading_enabled": "true",
            },
        )

        assert (
            coerced_boolean.status_code
            == 422
        )

        unknown = client.patch(
            (
                "/api/auth/account-policies/"
                "not-a-real-account"
            ),
            headers=ROOT,
            json={
                "trading_enabled": False,
            },
        )

        assert unknown.status_code == 404

        history_unknown = client.get(
            (
                "/api/auth/account-policies/"
                "not-a-real-account/events"
            ),
            headers=ROOT,
        )

        assert (
            history_unknown.status_code
            == 404
        )


def test_policy_history_limit_is_validated() -> None:
    with TestClient(app) as client:
        account_id = _new_account_id(
            "policy-limit"
        )

        _create_account(
            account_id
        )

        too_small = client.get(
            (
                "/api/auth/account-policies/"
                f"{account_id}/events"
                "?limit=0"
            ),
            headers=ROOT,
        )

        assert too_small.status_code == 422

        too_large = client.get(
            (
                "/api/auth/account-policies/"
                f"{account_id}/events"
                "?limit=1001"
            ),
            headers=ROOT,
        )

        assert too_large.status_code == 422
