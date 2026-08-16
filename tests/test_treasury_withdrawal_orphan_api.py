from __future__ import annotations

import base64

from fastapi.testclient import TestClient

import app.api.treasury as treasury_api
from app.main import app


REQUEST_ID = (
    "wd-orphan-api-test-"
    "0123456789abcdef"
)

ORDER_ID = (
    "wd_0123456789abcdef01234567890"
)


def _auth(
    username: str,
    password: str,
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    return {
        "Authorization": f"Basic {token}"
    }


ARNOLD = _auth(
    "arnold",
    "arnold-test-password",
)

ROOT = _auth(
    "rootadmin",
    "rootadmin-test-password",
)


def _row():
    return {
        "request_id": REQUEST_ID,
        "owner_account_id": "arnold",
        "custody_account_id": "zolnode",
        "currency": "USDT",
        "status": "withdrawal_reconciling",
        "gate_withdraw_order_id": ORDER_ID,
        "write_performed": True,
    }


def _confirmation() -> str:
    return (
        f"ABANDON WITHDRAWAL {REQUEST_ID} "
        f"ORDER {ORDER_ID}"
    )


def _payload():
    return {
        "confirmation": _confirmation(),
        "reason": (
            "Operator verified repeated Gate "
            "no-record evidence for this "
            "withdrawal request."
        ),
    }


def test_abandon_route_requires_super_admin(
    monkeypatch,
):
    async def must_not_run(**kwargs):
        raise AssertionError(
            "Account operator must never "
            "reach orphan resolver"
        )

    monkeypatch.setattr(
        treasury_api,
        "abandon_unresolved_withdrawal",
        must_not_run,
    )

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/treasury/withdrawals/"
                f"requests/{REQUEST_ID}/abandon"
            ),
            headers=ARNOLD,
            json=_payload(),
        )

    assert response.status_code == 403


def test_super_admin_route_delegates_to_service(
    monkeypatch,
):
    calls = {}

    monkeypatch.setattr(
        treasury_api,
        "_withdrawal_request_or_http",
        lambda request_id: _row(),
    )

    def fake_rate_limit(
        *,
        user,
        source_account_id,
        action,
    ):
        calls["rate_limit"] = {
            "username": user.username,
            "source_account_id": (
                source_account_id
            ),
            "action": action,
        }

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        fake_rate_limit,
    )

    treasury_credential = object()

    monkeypatch.setattr(
        treasury_api,
        "_treasury_account_or_http",
        lambda: treasury_credential,
    )

    async def fake_abandon(
        *,
        settings,
        request_id,
        username,
        reason,
        confirmation,
        treasury_account,
        **kwargs,
    ):
        calls["service"] = {
            "request_id": request_id,
            "username": username,
            "reason": reason,
            "confirmation": confirmation,
            "treasury_account": (
                treasury_account
            ),
        }

        return {
            "status": (
                "withdrawal_abandoned"
            ),
            "idempotent_replay": False,
            "gate_read_performed": True,
            "gate_write_performed": False,
            "ownership_settlement_performed": (
                False
            ),
            "automatic_retry_allowed": False,
            "lock_released": True,
            "audit": {
                "request_id": request_id,
                "status": (
                    "withdrawal_abandoned"
                ),
            },
            "operation_lock": None,
        }

    monkeypatch.setattr(
        treasury_api,
        "abandon_unresolved_withdrawal",
        fake_abandon,
    )

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/treasury/withdrawals/"
                f"requests/{REQUEST_ID}/abandon"
            ),
            headers=ROOT,
            json=_payload(),
        )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["phase"]
        == "T2C5F_WITHDRAWAL_ORPHAN_RESOLUTION"
    )

    assert (
        body["status"]
        == "withdrawal_abandoned"
    )

    assert (
        body["gate_write_performed"]
        is False
    )

    assert (
        body[
            "ownership_settlement_performed"
        ]
        is False
    )

    assert body["lock_released"] is True

    assert calls["rate_limit"] == {
        "username": "rootadmin",
        "source_account_id": "arnold",
        "action": "lock_release",
    }

    assert (
        calls["service"]["request_id"]
        == REQUEST_ID
    )

    assert (
        calls["service"]["username"]
        == "rootadmin"
    )

    assert (
        calls["service"][
            "treasury_account"
        ]
        is treasury_credential
    )


def test_abandon_route_requires_exact_confirmation(
    monkeypatch,
):
    monkeypatch.setattr(
        treasury_api,
        "_withdrawal_request_or_http",
        lambda request_id: _row(),
    )

    class NoRateLimit:
        def __call__(self, **kwargs):
            raise AssertionError(
                "Rate limiter must not run "
                "before confirmation passes"
            )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        NoRateLimit(),
    )

    payload = _payload()
    payload["confirmation"] = "WRONG"

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/treasury/withdrawals/"
                f"requests/{REQUEST_ID}/abandon"
            ),
            headers=ROOT,
            json=payload,
        )

    assert response.status_code == 400

    detail = response.json()["detail"]

    assert (
        detail["required_confirmation"]
        == _confirmation()
    )

    assert (
        detail["gate_write_performed"]
        is False
    )

    assert (
        detail["local_write_performed"]
        is False
    )


def test_abandon_route_maps_service_refusal_to_409(
    monkeypatch,
):
    from app.treasury_withdrawal_orphan_resolution import (
        TreasuryWithdrawalOrphanResolutionError,
    )

    monkeypatch.setattr(
        treasury_api,
        "_withdrawal_request_or_http",
        lambda request_id: _row(),
    )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        lambda **kwargs: None,
    )

    monkeypatch.setattr(
        treasury_api,
        "_treasury_account_or_http",
        lambda: object(),
    )

    async def refuse(**kwargs):
        raise (
            TreasuryWithdrawalOrphanResolutionError(
                "Gate now has a withdrawal record; "
                "orphan resolution refused"
            )
        )

    monkeypatch.setattr(
        treasury_api,
        "abandon_unresolved_withdrawal",
        refuse,
    )

    with TestClient(app) as client:
        response = client.post(
            (
                "/api/treasury/withdrawals/"
                f"requests/{REQUEST_ID}/abandon"
            ),
            headers=ROOT,
            json=_payload(),
        )

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert (
        detail["gate_write_performed"]
        is False
    )

    assert (
        detail[
            "ownership_settlement_performed"
        ]
        is False
    )

    assert (
        detail["automatic_retry_allowed"]
        is False
    )


def test_abandon_route_has_static_safety_barriers():
    import inspect

    source = inspect.getsource(
        treasury_api
        .abandon_treasury_withdrawal_request
    )

    assert (
        "Depends(require_super_admin)"
        in source
    )

    assert (
        "withdrawal_abandon_confirmation_text"
        in source
    )

    assert (
        "treasury_withdrawals_live_armed"
        in source
    )

    assert (
        'action="lock_release"'
        in source
    )

    assert (
        "abandon_unresolved_withdrawal("
        in source
    )

    assert "create_withdrawal(" not in source

    assert (
        "TreasuryOwnershipLedgerEntry"
        not in source
    )
