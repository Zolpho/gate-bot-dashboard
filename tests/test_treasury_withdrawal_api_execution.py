from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import app.api.treasury as treasury_api
from app.api.treasury import (
    TreasuryWithdrawalReservationRequest,
)
from app.config import Settings
from app.security import DashboardUser
from app.treasury_withdrawal_execution import (
    withdrawal_execution_confirmation_text,
)


def _user() -> DashboardUser:
    return DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )


def _row(
    *,
    status: str = "jit_ready",
) -> dict:
    return {
        "request_id": "wd-5c-test-request-001",
        "owner_account_id": "arnold",
        "custody_account_id": "zolnode",
        "username": "arnold",
        "destination_id": "wd_test_destination",
        "currency": "USDT",
        "chain": "ARBEVM",
        "address": (
            "0x111111111111111111111111"
            "1111111111111111"
        ),
        "memo": "",
        "amount": "1",
        "estimated_fee": "0.05",
        "conservative_funding_required": "1.05",
        "minimum_jit_transfer": "0",
        "jit_required": False,
        "status": status,
        "request": {
            "operation": (
                "external_withdrawal_simulation"
            ),
            "owner_account_id": "arnold",
            "destination_id": (
                "wd_test_destination"
            ),
            "currency": "USDT",
            "amount": "1",
        },
    }


def _preflight(
    *,
    valid: bool = True,
    fee: str = "0.05",
    required: str = "1.05",
    jit_required: bool = False,
) -> dict:
    return {
        "preflight_valid": valid,
        "errors": (
            []
            if valid
            else ["test invalid preflight"]
        ),
        "fee": {
            "estimated_fee": fee,
        },
        "funding": {
            "conservative_funding_required": (
                required
            ),
            "minimum_jit_transfer": (
                "0.05"
                if jit_required
                else "0"
            ),
            "jit_required": jit_required,
        },
        "destination": {
            "destination_id": (
                "wd_test_destination"
            ),
            "owner_account_id": "arnold",
            "currency": "USDT",
            "chain": "ARBEVM",
            "address": (
                "0x111111111111111111111111"
                "1111111111111111"
            ),
            "memo": "",
            "status": "approved",
        },
    }


def _install(
    monkeypatch,
    *,
    armed: bool = True,
    row: dict | None = None,
    preflight: dict | None = None,
    mismatches: list[str] | None = None,
    jit_required: bool = False,
):
    current_row = row or _row()
    current_preflight = (
        preflight or _preflight()
    )

    settings = Settings(
        _env_file=None,
        treasury_main_account="zolnode",
        treasury_withdrawals_live_armed=armed,
        treasury_withdrawals_live_accounts=(
            "arnold"
        ),
        treasury_rate_limit_enabled=False,
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        settings,
    )

    monkeypatch.setattr(
        treasury_api,
        "_withdrawal_request_or_http",
        lambda request_id: current_row,
    )

    monkeypatch.setattr(
        treasury_api,
        "get_withdrawal_lock_for_request",
        lambda request_id: {
            "lock_key": (
                "treasury-withdrawal:zolnode:USDT"
            ),
            "owner_account_id": "arnold",
            "custody_account_id": "zolnode",
            "currency": "USDT",
            "owner_request_id": (
                current_row["request_id"]
            ),
            "username": "arnold",
            "state": "held",
        },
    )

    calls = {
        "preflight": 0,
        "rate_limit": [],
        "submit": 0,
        "reconcile": 0,
    }

    async def fake_preflight(
        *,
        row,
        user,
    ):
        calls["preflight"] += 1
        return current_preflight

    monkeypatch.setattr(
        treasury_api,
        "_fresh_request_preflight",
        fake_preflight,
    )

    monkeypatch.setattr(
        treasury_api,
        "destination_snapshot_mismatches",
        lambda row, preflight: (
            mismatches or []
        ),
    )

    monkeypatch.setattr(
        treasury_api,
        "build_withdrawal_jit_plan",
        lambda *,
        request,
        preflight: {
            "jit_required": jit_required,
            "jit_amount_preview": (
                "0.05"
                if jit_required
                else "0"
            ),
            "source_account_id": "arnold",
            "custody_account_id": "zolnode",
            "currency": "USDT",
        },
    )

    def fake_rate_limit(
        *,
        user,
        source_account_id,
        action,
    ):
        calls["rate_limit"].append(
            (
                source_account_id,
                action,
            )
        )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        fake_rate_limit,
    )

    treasury_account = object()

    monkeypatch.setattr(
        treasury_api,
        "_treasury_account_or_http",
        lambda: treasury_account,
    )

    async def fake_submit(**kwargs):
        calls["submit"] += 1

        assert (
            kwargs["treasury_account"]
            is treasury_account
        )

        return {
            "status": "withdrawal_submitted",
            "gate_write_performed": True,
            "gate_write_accepted": True,
            "requires_reconciliation": True,
            "automatic_retry_allowed": False,
        }

    monkeypatch.setattr(
        treasury_api,
        "submit_withdrawal_once",
        fake_submit,
    )

    async def fake_reconcile(**kwargs):
        calls["reconcile"] += 1

        assert (
            kwargs["treasury_account"]
            is treasury_account
        )

        return {
            "status": "withdrawal_reconciling",
            "gate_read_performed": True,
            "gate_write_performed": False,
            "requires_reconciliation": True,
        }

    monkeypatch.setattr(
        treasury_api,
        "reconcile_withdrawal_service",
        fake_reconcile,
    )

    return current_row, calls


@pytest.mark.asyncio
async def test_execute_disarmed_never_calls_submission(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        armed=False,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .execute_treasury_external_withdrawal(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_execution_confirmation_text(
                            row
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 403
    assert calls["preflight"] == 1
    assert calls["submit"] == 0
    assert calls["rate_limit"] == []


@pytest.mark.asyncio
async def test_execute_invalid_preflight_blocks_before_write(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        preflight=_preflight(
            valid=False,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .execute_treasury_external_withdrawal(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_execution_confirmation_text(
                            row
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409
    assert calls["submit"] == 0


@pytest.mark.asyncio
async def test_execute_destination_mismatch_blocks(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        mismatches=["address"],
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .execute_treasury_external_withdrawal(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_execution_confirmation_text(
                            row
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409
    assert (
        exc_info.value.detail["reason"]
        == "destination_snapshot_mismatch"
    )
    assert calls["submit"] == 0


@pytest.mark.asyncio
async def test_execute_changed_fee_requires_fresh_request(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        preflight=_preflight(
            fee="0.06",
            required="1.06",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .execute_treasury_external_withdrawal(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_execution_confirmation_text(
                            row
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409
    assert (
        exc_info.value.detail["reason"]
        == "withdrawal_funding_snapshot_changed"
    )
    assert calls["submit"] == 0


@pytest.mark.asyncio
async def test_execute_fresh_jit_required_blocks(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        jit_required=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .execute_treasury_external_withdrawal(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_execution_confirmation_text(
                            row
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409
    assert (
        exc_info.value.detail["reason"]
        == "fresh_jit_required"
    )
    assert calls["submit"] == 0


@pytest.mark.asyncio
async def test_execute_requires_exact_confirmation(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .execute_treasury_external_withdrawal(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation="WRONG",
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 400
    assert calls["submit"] == 0


@pytest.mark.asyncio
async def test_execute_calls_5b_service_once_after_barriers(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
    )

    result = await (
        treasury_api
        .execute_treasury_external_withdrawal(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_execution_confirmation_text(
                        row
                    )
                ),
            ),
            user=_user(),
        )
    )

    assert result["status"] == (
        "withdrawal_submitted"
    )

    assert result["gate_write_performed"] is True
    assert calls["preflight"] == 1
    assert calls["submit"] == 1

    assert calls["rate_limit"] == [
        ("arnold", "execute"),
    ]


@pytest.mark.asyncio
async def test_execute_post_submission_never_calls_service(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        row=_row(
            status="withdrawal_reconciling"
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .execute_treasury_external_withdrawal(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation="irrelevant",
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409
    assert (
        exc_info.value.detail[
            "automatic_retry_allowed"
        ]
        is False
    )

    assert calls["preflight"] == 0
    assert calls["submit"] == 0


@pytest.mark.asyncio
async def test_reconcile_works_while_live_arm_is_off(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        armed=False,
        row=_row(
            status="withdrawal_reconciling"
        ),
    )

    result = await (
        treasury_api
        .reconcile_treasury_external_withdrawal(
            row["request_id"],
            user=_user(),
        )
    )

    assert result["status"] == (
        "withdrawal_reconciling"
    )

    assert (
        result["withdrawals_enabled"]
        is False
    )

    assert result["reconciliation_only"] is True
    assert calls["preflight"] == 0
    assert calls["submit"] == 0
    assert calls["reconcile"] == 1

    assert calls["rate_limit"] == [
        ("arnold", "reconcile"),
    ]


@pytest.mark.asyncio
async def test_reconcile_rejects_pre_submission_state(
    monkeypatch,
):
    row, calls = _install(
        monkeypatch,
        armed=False,
        row=_row(
            status="jit_ready"
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .reconcile_treasury_external_withdrawal(
                row["request_id"],
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409
    assert calls["reconcile"] == 0


def test_external_execute_route_safety_order():
    source = inspect.getsource(
        treasury_api
        .execute_treasury_external_withdrawal
    )

    # Authorization must happen before entering the
    # only branch that is allowed to approach a new
    # external withdrawal submission.
    authorization = source.index(
        "require_account_access("
    )

    live_path = source.index(
        'if row["status"] != "jit_ready":'
    )

    assert authorization < live_path

    # Restrict ordering checks to the fresh jit_ready
    # execution path. Earlier replay/terminal branches
    # legitimately contain some of the same helper names.
    live_source = source[live_path:]

    tokens = [
        "get_withdrawal_lock_for_request(",
        "_fresh_request_preflight(",
        "destination_snapshot_mismatches(",
        "build_withdrawal_jit_plan(",
        "withdrawal_execution_confirmation_text(",
        "treasury_withdrawals_live_armed",
        "treasury_withdrawals_live_account_allowed(",
        "_enforce_treasury_rate_limit(",
        "_treasury_account_or_http()",
        "submit_withdrawal_once(",
    ]

    cursor = 0
    positions = []

    for token in tokens:
        position = live_source.find(
            token,
            cursor,
        )

        assert position >= 0, token

        positions.append(position)
        cursor = position + len(token)

    assert positions == sorted(positions)

    # API delegates the financial write to the audited
    # 5B service. GateClient must never be called here.
    assert "create_withdrawal(" not in source


def test_external_reconcile_route_has_no_submission_call():
    source = inspect.getsource(
        treasury_api
        .reconcile_treasury_external_withdrawal
    )

    assert "submit_withdrawal_once(" not in source
    assert "create_withdrawal(" not in source

    assert (
        "reconcile_withdrawal_service("
        in source
    )

    # Reconciliation must not depend on the live arm.
    assert (
        "if not settings"
        ".treasury_withdrawals_live_armed"
        not in source.replace("\n", "")
    )
