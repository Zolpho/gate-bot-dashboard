from __future__ import annotations

import inspect
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

import app.api.treasury as treasury_api
from app.api.treasury import (
    TreasuryWithdrawalCancellationRequest,
    TreasuryWithdrawalReservationRequest,
)
from app.db import init_db, session_scope
from app.models import (
    TreasuryWithdrawalOperationLock,
)
from app.security import DashboardUser
from app.treasury_transfer_audit import (
    get_transfer_request,
)
from app.treasury_withdrawal_audit import (
    get_withdrawal_request,
    list_withdrawal_request_events,
    record_withdrawal_simulation,
    transition_withdrawal_request,
)
from app.treasury_withdrawal_jit import (
    withdrawal_jit_preparation_confirmation_text,
    withdrawal_jit_transfer_request_id,
)
from app.treasury_withdrawal_locks import (
    acquire_withdrawal_lock,
    get_withdrawal_lock_for_request,
)
from app.treasury_withdrawal_workflow import (
    withdrawal_cancel_confirmation_text,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_database():
    init_db()


@pytest.fixture(autouse=True)
def _clear_locks():
    with session_scope() as db:
        db.execute(
            delete(
                TreasuryWithdrawalOperationLock
            )
        )

    yield

    with session_scope() as db:
        db.execute(
            delete(
                TreasuryWithdrawalOperationLock
            )
        )


def _user() -> DashboardUser:
    return DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )


def _make_preflight(
    row: dict,
    *,
    jit_required: bool = True,
    jit_amount: str = "4.05",
    valid: bool = True,
) -> dict:
    return {
        "status": (
            "ready"
            if valid
            else "invalid"
        ),
        "preflight_valid": valid,
        "executable": False,
        "gate_write_performed": False,
        "destination": {
            "destination_id": (
                row["destination_id"]
            ),
            "owner_account_id": (
                row["owner_account_id"]
            ),
            "currency": row["currency"],
            "chain": row["chain"],
            "address": row["address"],
            "memo": row["memo"],
            "status": (
                "approved"
                if valid
                else "revoked"
            ),
        },
        "funding": {
            "jit_required": jit_required,
            "minimum_jit_transfer": (
                jit_amount
            ),
            "conservative_funding_required": (
                "5.05"
            ),
        },
        "errors": (
            []
            if valid
            else ["destination_approved"]
        ),
    }


def _create_confirmed_request() -> dict:
    request_id = (
        "wd-jitprep-"
        + uuid4().hex
    )

    destination_id = (
        "wd_"
        + uuid4().hex
    )

    address = (
        "0x"
        + uuid4().hex
        + uuid4().hex[:8]
    )

    destination = {
        "destination_id": destination_id,
        "owner_account_id": "arnold",
        "currency": "USDT",
        "chain": "ARBEVM",
        "address": address,
        "memo": "",
        "status": "approved",
    }

    payload = {
        "operation": (
            "external_withdrawal_simulation"
        ),
        "owner_account_id": "arnold",
        "custody_account_id": "zolnode",
        "destination_id": destination_id,
        "currency": "USDT",
        "amount": "5",
    }

    initial_preflight = {
        "preflight_valid": True,
        "destination": destination,
        "funding": {
            "jit_required": True,
            "minimum_jit_transfer": "4.05",
            "conservative_funding_required": (
                "5.05"
            ),
        },
    }

    row, created = (
        record_withdrawal_simulation(
            request_id=request_id,
            owner_account_id="arnold",
            custody_account_id="zolnode",
            username="arnold",
            destination_id=destination_id,
            currency="USDT",
            chain="ARBEVM",
            address=address,
            memo="",
            amount=Decimal("5"),
            estimated_fee=Decimal("0.05"),
            conservative_funding_required=(
                Decimal("5.05")
            ),
            minimum_jit_transfer=(
                Decimal("4.05")
            ),
            jit_required=True,
            payload=payload,
            preflight=initial_preflight,
            destination_snapshot=destination,
        )
    )

    assert created is True

    acquire_withdrawal_lock(
        owner_account_id="arnold",
        custody_account_id="zolnode",
        currency="USDT",
        owner_request_id=request_id,
        username="arnold",
    )

    transition_withdrawal_request(
        request_id,
        expected_statuses={"simulated"},
        new_status="reserved",
        username="arnold",
        action="reserved",
        details={
            "gate_write_performed": False,
        },
        simulation=False,
        completed=False,
    )

    transition_withdrawal_request(
        request_id,
        expected_statuses={"reserved"},
        new_status="confirmed_ready",
        username="arnold",
        action="confirmed_ready",
        details={
            "gate_write_performed": False,
        },
        simulation=False,
        completed=False,
    )

    result = get_withdrawal_request(
        request_id
    )

    assert result is not None

    return result


def _install_preflight(
    monkeypatch,
    row: dict,
    *,
    jit_required: bool = True,
    jit_amount: str = "4.05",
    valid: bool = True,
):
    calls = {"count": 0}

    async def fake_preflight(
        *,
        row,
        user,
    ):
        calls["count"] += 1

        return _make_preflight(
            row,
            jit_required=jit_required,
            jit_amount=jit_amount,
            valid=valid,
        )

    monkeypatch.setattr(
        treasury_api,
        "_fresh_request_preflight",
        fake_preflight,
    )

    return calls


@pytest.mark.asyncio
async def test_prepare_jit_records_local_plan_only(
    monkeypatch,
):
    row = _create_confirmed_request()

    calls = _install_preflight(
        monkeypatch,
        row,
    )

    result = await (
        treasury_api
        .prepare_treasury_withdrawal_jit(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_jit_preparation_confirmation_text(
                        row["request_id"]
                    )
                ),
            ),
            user=_user(),
        )
    )

    assert calls["count"] == 1
    assert result["status"] == "jit_prepared"
    assert (
        result["gate_write_performed"]
        is False
    )
    assert (
        result["transfer_audit_created"]
        is False
    )

    plan = result["jit_plan"]

    assert plan["jit_required"] is True
    assert (
        plan["jit_amount_preview"]
        == "4.05"
    )
    assert (
        plan["amount_is_execution_authority"]
        is False
    )

    child_id = (
        plan["jit_transfer_request_id"]
    )

    assert child_id == (
        withdrawal_jit_transfer_request_id(
            row["request_id"]
        )
    )

    # T2C.4B must NOT reserve/create the child transfer.
    assert get_transfer_request(
        child_id
    ) is None

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )

    events = list_withdrawal_request_events(
        row["request_id"]
    )

    assert events[-1]["action"] == (
        "jit_prepared"
    )


@pytest.mark.asyncio
async def test_prepare_jit_is_idempotent_without_new_preflight(
    monkeypatch,
):
    row = _create_confirmed_request()

    calls = _install_preflight(
        monkeypatch,
        row,
    )

    body = TreasuryWithdrawalReservationRequest(
        confirmation=(
            withdrawal_jit_preparation_confirmation_text(
                row["request_id"]
            )
        ),
    )

    first = await (
        treasury_api
        .prepare_treasury_withdrawal_jit(
            row["request_id"],
            body,
            user=_user(),
        )
    )

    second = await (
        treasury_api
        .prepare_treasury_withdrawal_jit(
            row["request_id"],
            body,
            user=_user(),
        )
    )

    assert calls["count"] == 1
    assert first["jit_preparation_created"] is True
    assert second["idempotent_replay"] is True
    assert (
        second["jit_preparation_created"]
        is False
    )

    events = list_withdrawal_request_events(
        row["request_id"]
    )

    assert [
        event["action"]
        for event in events
    ].count("jit_prepared") == 1


@pytest.mark.asyncio
async def test_prepare_no_jit_required_has_no_child_transfer(
    monkeypatch,
):
    row = _create_confirmed_request()

    _install_preflight(
        monkeypatch,
        row,
        jit_required=False,
        jit_amount="0",
    )

    result = await (
        treasury_api
        .prepare_treasury_withdrawal_jit(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_jit_preparation_confirmation_text(
                        row["request_id"]
                    )
                ),
            ),
            user=_user(),
        )
    )

    plan = result["jit_plan"]

    assert plan["jit_required"] is False
    assert plan["jit_amount_preview"] == "0"

    assert (
        plan["jit_transfer_request_id"]
        is None
    )


@pytest.mark.asyncio
async def test_invalid_jit_amount_blocks_and_releases_lock(
    monkeypatch,
):
    row = _create_confirmed_request()

    _install_preflight(
        monkeypatch,
        row,
        jit_required=True,
        jit_amount="4.000000001",
    )

    with pytest.raises(
        HTTPException
    ) as captured:
        await (
            treasury_api
            .prepare_treasury_withdrawal_jit(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_jit_preparation_confirmation_text(
                            row["request_id"]
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert captured.value.status_code == 409

    stored = get_withdrawal_request(
        row["request_id"]
    )

    assert stored is not None
    assert stored["status"] == "blocked"

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )

    events = list_withdrawal_request_events(
        row["request_id"]
    )

    assert events[-1]["action"] == (
        "jit_preparation_blocked"
    )


@pytest.mark.asyncio
async def test_jit_prepared_can_still_cancel_without_money_move(
    monkeypatch,
):
    row = _create_confirmed_request()

    _install_preflight(
        monkeypatch,
        row,
    )

    await (
        treasury_api
        .prepare_treasury_withdrawal_jit(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_jit_preparation_confirmation_text(
                        row["request_id"]
                    )
                ),
            ),
            user=_user(),
        )
    )

    result = (
        treasury_api
        .cancel_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalCancellationRequest(
                confirmation=(
                    withdrawal_cancel_confirmation_text(
                        row["request_id"]
                    )
                ),
                reason=(
                    "T2C4B cancellation is safe because "
                    "JIT preparation moved no funds."
                ),
            ),
            user=_user(),
        )
    )

    assert result["status"] == "cancelled"
    assert result["lock_released"] is True
    assert (
        result["gate_write_performed"]
        is False
    )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )


def test_jit_preparation_has_no_money_moving_call():
    source = inspect.getsource(
        treasury_api
        .prepare_treasury_withdrawal_jit
    )

    forbidden = (
        "execute_reserved_live_transfer(",
        "reserve_live_transfer(",
        "create_sub_account_transfer(",
        "create_withdrawal(",
    )

    for token in forbidden:
        assert token not in source
