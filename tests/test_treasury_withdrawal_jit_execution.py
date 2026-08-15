from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

import app.api.treasury as treasury_api
from app.accounts import GateAccountConfig
from app.api.treasury import (
    TreasuryWithdrawalCancellationRequest,
    TreasuryWithdrawalReservationRequest,
)
from app.db import init_db, session_scope
from app.models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryTransferOperationLock,
    TreasuryWithdrawalOperationLock,
)
from app.security import DashboardUser
from app.treasury_ownership import (
    internal_transfer_credit_event_id,
)
from app.treasury_transfer_audit import (
    get_transfer_request,
    mark_transfer_request,
    reserve_live_transfer,
)
from app.treasury_withdrawal_audit import (
    get_withdrawal_request,
    record_withdrawal_simulation,
    transition_withdrawal_request,
)
from app.treasury_withdrawal_jit import (
    build_withdrawal_jit_plan,
    withdrawal_jit_execution_confirmation_text,
    withdrawal_jit_transfer_request_id,
)
from app.treasury_withdrawal_locks import (
    acquire_withdrawal_lock,
    get_withdrawal_lock_for_request,
    release_withdrawal_lock,
)
from app.treasury_withdrawal_workflow import (
    withdrawal_cancel_confirmation_text,
    withdrawal_hold_on_main_confirmation_text,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_database():
    init_db()


@pytest.fixture(autouse=True)
def _clear_operation_locks():
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TreasuryTransferOperationLock
                )
            )

            db.execute(
                delete(
                    TreasuryWithdrawalOperationLock
                )
            )

    clear()

    try:
        yield
    finally:
        clear()


def _user() -> DashboardUser:
    return DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )


def _source_account() -> GateAccountConfig:
    return GateAccountConfig(
        id="arnold",
        name="arnold",
        api_key="monitor-arnold-test",
        api_secret="monitor-arnold-secret",
        enabled=True,
        account_type="subaccount",
        gate_uid="58601346",
    )


def _treasury_account() -> GateAccountConfig:
    return GateAccountConfig(
        id="zolnode",
        name="zolnode",
        api_key="treasury-test",
        api_secret="treasury-test-secret",
        enabled=True,
        account_type="main",
        gate_uid="13079163",
    )


def _preflight(
    row: dict,
    *,
    jit_required: bool = True,
    jit_amount: str = "4.05",
) -> dict:
    return {
        "status": "ready",
        "preflight_valid": True,
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
            "status": "approved",
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
        "errors": [],
    }


def _create_jit_prepared_request() -> dict:
    request_id = (
        "wd-jitexec-"
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
        expected_statuses={
            "simulated",
        },
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
        expected_statuses={
            "reserved",
        },
        new_status="confirmed_ready",
        username="arnold",
        action="confirmed_ready",
        details={
            "gate_write_performed": False,
        },
        simulation=False,
        completed=False,
    )

    prepared_plan = {
        "jit_required": True,
        "jit_amount_preview": "4.05",
        "jit_transfer_request_id": (
            withdrawal_jit_transfer_request_id(
                request_id
            )
        ),
        "source_account_id": "arnold",
        "custody_account_id": "zolnode",
        "currency": "USDT",
        "derived_from_fresh_preflight": True,
        "amount_is_execution_authority": False,
        "gate_write_performed": False,
        "transfer_audit_created": False,
    }

    transition_withdrawal_request(
        request_id,
        expected_statuses={
            "confirmed_ready",
        },
        new_status="jit_prepared",
        username="arnold",
        action="jit_prepared",
        details={
            "jit_plan": prepared_plan,
            "gate_write_performed": False,
        },
        simulation=False,
        completed=False,
    )

    result = get_withdrawal_request(
        request_id
    )

    assert result is not None
    assert result["status"] == "jit_prepared"

    return result


def _install_fresh_preflight(
    monkeypatch,
    *,
    jit_required: bool = True,
    jit_amount: str = "4.05",
):
    calls = {
        "count": 0,
    }

    async def fake(
        *,
        row,
        user,
    ):
        calls["count"] += 1

        return _preflight(
            row,
            jit_required=jit_required,
            jit_amount=jit_amount,
        )

    monkeypatch.setattr(
        treasury_api,
        "_fresh_request_preflight",
        fake,
    )

    return calls


def _arm_jit(monkeypatch):
    monkeypatch.setattr(
        treasury_api.settings,
        "treasury_transfers_live_armed",
        True,
    )

    monkeypatch.setattr(
        treasury_api.settings,
        "treasury_transfers_live_accounts",
        "arnold",
    )

    monkeypatch.setattr(
        treasury_api,
        "get_gate_account",
        lambda account_id: (
            _source_account()
            if account_id == "arnold"
            else None
        ),
    )

    monkeypatch.setattr(
        treasury_api,
        "_treasury_account_or_http",
        lambda: _treasury_account(),
    )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        lambda **kwargs: None,
    )


def _confirmation(
    row: dict,
    preflight: dict,
) -> str:
    plan = build_withdrawal_jit_plan(
        request=row,
        preflight=preflight,
    )

    return (
        withdrawal_jit_execution_confirmation_text(
            request=row,
            plan=plan,
        )
    )


def _create_child(
    *,
    request_id: str,
    amount: Decimal,
    audit_payload: dict,
    status: str,
    write_performed: bool,
) -> dict:
    row, created = reserve_live_transfer(
        request_id=request_id,
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="arnold",
        currency="USDT",
        amount=amount,
        payload=audit_payload,
    )

    assert created is True

    return mark_transfer_request(
        request_id,
        status=status,
        write_performed=write_performed,
        completed=(
            status
            in {
                "success",
                "failed",
                "rejected",
                "blocked",
            }
        ),
    )


@pytest.mark.asyncio
async def test_changed_jit_amount_requires_new_confirmation_without_write(
    monkeypatch,
):
    row = _create_jit_prepared_request()

    _install_fresh_preflight(
        monkeypatch,
        jit_required=True,
        jit_amount="3.05",
    )

    calls = {
        "execute": 0,
    }

    async def forbidden_executor(**kwargs):
        calls["execute"] += 1

        raise AssertionError(
            "Executor must not run after stale "
            "confirmation"
        )

    monkeypatch.setattr(
        treasury_api,
        "execute_reserved_live_transfer",
        forbidden_executor,
    )

    old_confirmation = _confirmation(
        row,
        _preflight(
            row,
            jit_required=True,
            jit_amount="4.05",
        ),
    )

    with pytest.raises(
        HTTPException
    ) as captured:
        await (
            treasury_api
            .execute_treasury_withdrawal_jit(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=old_confirmation,
                ),
                user=_user(),
            )
        )

    assert captured.value.status_code == 400
    assert calls["execute"] == 0

    detail = captured.value.detail

    assert (
        detail["jit_plan"]["jit_amount_preview"]
        == "3.05"
    )

    assert (
        "3.05"
        in detail["required_confirmation"]
    )

    stored = get_withdrawal_request(
        row["request_id"]
    )

    assert stored is not None
    assert stored["status"] == "jit_prepared"

    assert (
        get_transfer_request(
            withdrawal_jit_transfer_request_id(
                row["request_id"]
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_no_jit_required_moves_locally_to_jit_ready(
    monkeypatch,
):
    row = _create_jit_prepared_request()

    _install_fresh_preflight(
        monkeypatch,
        jit_required=False,
        jit_amount="0",
    )

    confirmation = _confirmation(
        row,
        _preflight(
            row,
            jit_required=False,
            jit_amount="0",
        ),
    )

    result = await (
        treasury_api
        .execute_treasury_withdrawal_jit(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=confirmation,
            ),
            user=_user(),
        )
    )

    assert result["status"] == "jit_ready"
    assert result["jit_required"] is False
    assert (
        result["gate_write_performed"]
        is False
    )
    assert result["child_transfer"] is None

    # Custody remains reserved for the later external
    # withdrawal.
    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )


@pytest.mark.asyncio
async def test_jit_success_moves_parent_ready_and_credits_ownership(
    monkeypatch,
):
    row = _create_jit_prepared_request()

    fresh = _preflight(
        row,
        jit_required=True,
        jit_amount="4.05",
    )

    _install_fresh_preflight(
        monkeypatch,
        jit_required=True,
        jit_amount="4.05",
    )

    _arm_jit(monkeypatch)

    async def fake_executor(
        *,
        request_id,
        amount,
        audit_payload,
        **kwargs,
    ):
        child = _create_child(
            request_id=request_id,
            amount=amount,
            audit_payload=audit_payload,
            status="success",
            write_performed=True,
        )

        return {
            "status": "success",
            "gate_write_performed": True,
            "audit": child,
        }

    monkeypatch.setattr(
        treasury_api,
        "execute_reserved_live_transfer",
        fake_executor,
    )

    result = await (
        treasury_api
        .execute_treasury_withdrawal_jit(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    _confirmation(
                        row,
                        fresh,
                    )
                ),
            ),
            user=_user(),
        )
    )

    assert result["status"] == "jit_ready"
    assert result["gate_write_performed"] is True

    child_id = (
        withdrawal_jit_transfer_request_id(
            row["request_id"]
        )
    )

    child = get_transfer_request(
        child_id
    )

    assert child is not None
    assert child["status"] == "success"

    assert (
        child["request"]["operation"]
        == "subaccount_to_main"
    )

    assert (
        child["request"]["purpose"]
        == "withdrawal_jit"
    )

    assert (
        child["request"][
            "withdrawal_request_id"
        ]
        == row["request_id"]
    )

    event_id = (
        internal_transfer_credit_event_id(
            child_id
        )
    )

    with session_scope() as db:
        ownership = db.scalar(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .event_id
                == event_id
            )
        )

        assert ownership is not None

        assert (
            ownership.owner_account_id
            == "arnold"
        )

        assert (
            ownership.custody_account_id
            == "zolnode"
        )

        assert ownership.currency == "USDT"

        assert (
            Decimal(
                ownership.delta_amount
            )
            == Decimal("4.05")
        )

    # Funds are now physically on main and reserved for
    # this withdrawal, so the custody lock stays held.
    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )


@pytest.mark.asyncio
async def test_pending_and_uncertain_jit_keep_parent_reconciling(
    monkeypatch,
):
    for child_status in (
        "pending",
        "uncertain",
    ):
        row = _create_jit_prepared_request()

        fresh = _preflight(
            row,
            jit_required=True,
            jit_amount="4.05",
        )

        _install_fresh_preflight(
            monkeypatch,
            jit_required=True,
            jit_amount="4.05",
        )

        _arm_jit(monkeypatch)

        async def fake_executor(
            *,
            request_id,
            amount,
            audit_payload,
            **kwargs,
        ):
            child = _create_child(
                request_id=request_id,
                amount=amount,
                audit_payload=audit_payload,
                status=child_status,
                write_performed=True,
            )

            return {
                "status": child_status,
                "gate_write_performed": True,
                "audit": child,
            }

        monkeypatch.setattr(
            treasury_api,
            "execute_reserved_live_transfer",
            fake_executor,
        )

        result = await (
            treasury_api
            .execute_treasury_withdrawal_jit(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        _confirmation(
                            row,
                            fresh,
                        )
                    ),
                ),
                user=_user(),
            )
        )

        assert (
            result["status"]
            == "jit_reconciling"
        )

        assert (
            result["requires_reconciliation"]
            is True
        )

        assert (
            get_withdrawal_lock_for_request(
                row["request_id"]
            )
            is not None
        )

        # The next iteration uses the same custody/currency
        # key, so clean only this parent's lock.
        release_withdrawal_lock(
            custody_account_id="zolnode",
            currency="USDT",
            owner_request_id=(
                row["request_id"]
            ),
        )


@pytest.mark.asyncio
async def test_definitive_jit_failure_releases_withdrawal_lock(
    monkeypatch,
):
    row = _create_jit_prepared_request()

    fresh = _preflight(
        row,
        jit_required=True,
        jit_amount="4.05",
    )

    _install_fresh_preflight(
        monkeypatch,
        jit_required=True,
        jit_amount="4.05",
    )

    _arm_jit(monkeypatch)

    async def fake_executor(
        *,
        request_id,
        amount,
        audit_payload,
        **kwargs,
    ):
        child = _create_child(
            request_id=request_id,
            amount=amount,
            audit_payload=audit_payload,
            status="failed",
            write_performed=True,
        )

        return {
            "status": "failed",
            "gate_write_performed": True,
            "audit": child,
        }

    monkeypatch.setattr(
        treasury_api,
        "execute_reserved_live_transfer",
        fake_executor,
    )

    result = await (
        treasury_api
        .execute_treasury_withdrawal_jit(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    _confirmation(
                        row,
                        fresh,
                    )
                ),
            ),
            user=_user(),
        )
    )

    assert result["status"] == "jit_failed"

    assert (
        result["withdrawal_lock_released"]
        is True
    )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )


@pytest.mark.asyncio
async def test_interrupted_jit_before_child_recovers_to_prepared(
    monkeypatch,
):
    row = _create_jit_prepared_request()

    transition_withdrawal_request(
        row["request_id"],
        expected_statuses={
            "jit_prepared",
        },
        new_status="jit_executing",
        username="arnold",
        action="jit_execution_started",
        details={
            "gate_write_performed": False,
        },
        simulation=False,
        completed=False,
    )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        lambda **kwargs: (
            pytest.fail(
                "No rate-limit/Gate reconcile should "
                "run when no child audit exists"
            )
        ),
    )

    result = await (
        treasury_api
        .reconcile_treasury_withdrawal_jit(
            row["request_id"],
            user=_user(),
        )
    )

    assert result["status"] == "jit_prepared"

    assert (
        result["recovered_before_child"]
        is True
    )

    assert (
        result["gate_read_performed"]
        is False
    )

    assert (
        result["gate_write_performed"]
        is False
    )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )


@pytest.mark.asyncio
async def test_reconcile_success_never_resubmits_and_credits_ownership(
    monkeypatch,
):
    row = _create_jit_prepared_request()

    child_id = (
        withdrawal_jit_transfer_request_id(
            row["request_id"]
        )
    )

    audit_payload = {
        "operation": "subaccount_to_main",
        "purpose": "withdrawal_jit",
        "withdrawal_request_id": (
            row["request_id"]
        ),
        "source_account_id": "arnold",
        "destination_account_id": "zolnode",
        "gate_payload": {
            "sub_account": "58601346",
            "sub_account_type": "spot",
            "currency": "USDT",
            "amount": "4.05",
            "direction": "from",
            "client_order_id": "test-jit-child",
        },
    }

    child = _create_child(
        request_id=child_id,
        amount=Decimal("4.05"),
        audit_payload=audit_payload,
        status="pending",
        write_performed=True,
    )

    assert child["status"] == "pending"

    transition_withdrawal_request(
        row["request_id"],
        expected_statuses={
            "jit_prepared",
        },
        new_status="jit_reconciling",
        username="arnold",
        action="jit_reconciling",
        details={
            "child_transfer_request_id": (
                child_id
            ),
            "gate_write_performed": True,
        },
        simulation=False,
        completed=False,
    )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        lambda **kwargs: None,
    )

    monkeypatch.setattr(
        treasury_api,
        "_treasury_account_or_http",
        lambda: _treasury_account(),
    )

    async def forbidden_submit(**kwargs):
        raise AssertionError(
            "JIT reconciliation must never submit "
            "another transfer"
        )

    monkeypatch.setattr(
        treasury_api,
        "execute_reserved_live_transfer",
        forbidden_submit,
    )

    calls = {
        "reconcile": 0,
    }

    async def fake_reconcile(
        *,
        settings,
        record,
        treasury_account,
    ):
        calls["reconcile"] += 1

        success = mark_transfer_request(
            record["request_id"],
            status="success",
            write_performed=True,
            completed=True,
        )

        return {
            "status": "success",
            "lock_released": True,
            "audit": success,
            "reconciliation": {
                "outcome": "success",
            },
        }

    monkeypatch.setattr(
        treasury_api,
        "reconcile_live_transfer",
        fake_reconcile,
    )

    result = await (
        treasury_api
        .reconcile_treasury_withdrawal_jit(
            row["request_id"],
            user=_user(),
        )
    )

    assert calls["reconcile"] == 1
    assert result["status"] == "jit_ready"

    event_id = (
        internal_transfer_credit_event_id(
            child_id
        )
    )

    with session_scope() as db:
        ownership = db.scalar(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .event_id
                == event_id
            )
        )

        assert ownership is not None

        assert (
            Decimal(
                ownership.delta_amount
            )
            == Decimal("4.05")
        )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )


def test_cancellation_forbidden_after_jit_money_boundary():
    row = _create_jit_prepared_request()

    child_id = (
        withdrawal_jit_transfer_request_id(
            row["request_id"]
        )
    )

    audit_payload = {
        "operation": "subaccount_to_main",
        "purpose": "withdrawal_jit",
        "withdrawal_request_id": (
            row["request_id"]
        ),
        "source_account_id": "arnold",
        "destination_account_id": "zolnode",
        "gate_payload": {
            "sub_account": "58601346",
            "sub_account_type": "spot",
            "currency": "USDT",
            "amount": "4.05",
            "direction": "from",
            "client_order_id": "uncertain-jit",
        },
    }

    _create_child(
        request_id=child_id,
        amount=Decimal("4.05"),
        audit_payload=audit_payload,
        status="uncertain",
        write_performed=True,
    )

    transition_withdrawal_request(
        row["request_id"],
        expected_statuses={
            "jit_prepared",
        },
        new_status="jit_reconciling",
        username="arnold",
        action="jit_reconciling",
        details={
            "child_transfer_request_id": (
                child_id
            ),
            "gate_write_performed": True,
        },
        simulation=False,
        completed=False,
    )

    with pytest.raises(
        HTTPException
    ) as captured:
        treasury_api.cancel_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalCancellationRequest(
                confirmation=(
                    withdrawal_cancel_confirmation_text(
                        row["request_id"]
                    )
                ),
                reason=(
                    "This must not be allowed after "
                    "the JIT money-moving boundary."
                ),
            ),
            user=_user(),
        )

    assert captured.value.status_code == 409

    assert (
        captured.value.detail["status"]
        == "jit_reconciling"
    )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )


def _move_parent_to_jit_ready(
    row: dict,
    *,
    action: str = "jit_not_required",
) -> dict:
    transition_withdrawal_request(
        row["request_id"],
        expected_statuses={
            "jit_prepared",
        },
        new_status="jit_ready",
        username="arnold",
        action=action,
        details={
            "gate_write_performed": (
                action == "jit_ready"
            ),
        },
        simulation=False,
        completed=False,
    )

    result = get_withdrawal_request(
        row["request_id"]
    )

    assert result is not None
    assert result["status"] == "jit_ready"

    return result


def test_hold_on_main_after_success_preserves_ownership_and_releases_lock():
    row = _create_jit_prepared_request()

    child_id = (
        withdrawal_jit_transfer_request_id(
            row["request_id"]
        )
    )

    audit_payload = {
        "operation": "subaccount_to_main",
        "purpose": "withdrawal_jit",
        "withdrawal_request_id": (
            row["request_id"]
        ),
        "source_account_id": "arnold",
        "destination_account_id": "zolnode",
        "gate_payload": {
            "sub_account": "58601346",
            "sub_account_type": "spot",
            "currency": "USDT",
            "amount": "4.05",
            "direction": "from",
            "client_order_id": (
                "hold-on-main-test"
            ),
        },
    }

    child = _create_child(
        request_id=child_id,
        amount=Decimal("4.05"),
        audit_payload=audit_payload,
        status="success",
        write_performed=True,
    )

    assert child["status"] == "success"

    row = _move_parent_to_jit_ready(
        row,
        action="jit_ready",
    )

    event_id = (
        internal_transfer_credit_event_id(
            child_id
        )
    )

    with session_scope() as db:
        ownership_before = db.scalar(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .event_id
                == event_id
            )
        )

        assert ownership_before is not None
        amount_before = Decimal(
            ownership_before.delta_amount
        )

    result = (
        treasury_api
        .hold_treasury_withdrawal_funds_on_main(
            row["request_id"],
            TreasuryWithdrawalCancellationRequest(
                confirmation=(
                    withdrawal_hold_on_main_confirmation_text(
                        row["request_id"]
                    )
                ),
                reason=(
                    "External withdrawal intentionally "
                    "abandoned; retain economic ownership "
                    "on main."
                ),
            ),
            user=_user(),
        )
    )

    assert (
        result["status"]
        == "funds_held_on_main"
    )

    assert result["lock_released"] is True

    assert (
        result["gate_write_performed"]
        is False
    )

    assert (
        result["ownership_ledger_changed"]
        is False
    )

    assert (
        result["funds_returned_to_source"]
        is False
    )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )

    with session_scope() as db:
        ownership_after = db.scalar(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .event_id
                == event_id
            )
        )

        assert ownership_after is not None

        assert (
            Decimal(
                ownership_after.delta_amount
            )
            == amount_before
            == Decimal("4.05")
        )


def test_hold_on_main_supports_no_jit_ready():
    row = _create_jit_prepared_request()

    row = _move_parent_to_jit_ready(
        row,
        action="jit_not_required",
    )

    child_id = (
        withdrawal_jit_transfer_request_id(
            row["request_id"]
        )
    )

    assert (
        get_transfer_request(child_id)
        is None
    )

    result = (
        treasury_api
        .hold_treasury_withdrawal_funds_on_main(
            row["request_id"],
            TreasuryWithdrawalCancellationRequest(
                confirmation=(
                    withdrawal_hold_on_main_confirmation_text(
                        row["request_id"]
                    )
                ),
                reason=(
                    "No JIT was required; abandon the "
                    "external withdrawal and release "
                    "custody reservation."
                ),
            ),
            user=_user(),
        )
    )

    assert (
        result["status"]
        == "funds_held_on_main"
    )

    assert result["child_transfer"] is None
    assert result["lock_released"] is True

    assert (
        result["gate_write_performed"]
        is False
    )


def test_hold_on_main_rejects_unresolved_jit():
    row = _create_jit_prepared_request()

    transition_withdrawal_request(
        row["request_id"],
        expected_statuses={
            "jit_prepared",
        },
        new_status="jit_reconciling",
        username="arnold",
        action="jit_reconciling",
        details={
            "gate_write_performed": True,
        },
        simulation=False,
        completed=False,
    )

    with pytest.raises(
        HTTPException
    ) as captured:
        treasury_api.hold_treasury_withdrawal_funds_on_main(
            row["request_id"],
            TreasuryWithdrawalCancellationRequest(
                confirmation=(
                    withdrawal_hold_on_main_confirmation_text(
                        row["request_id"]
                    )
                ),
                reason="Unresolved JIT must remain locked.",
            ),
            user=_user(),
        )

    assert captured.value.status_code == 409

    assert (
        captured.value.detail["status"]
        == "jit_reconciling"
    )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )


def test_hold_on_main_replay_recovers_stranded_lock():
    row = _create_jit_prepared_request()

    row = _move_parent_to_jit_ready(
        row,
    )

    transition_withdrawal_request(
        row["request_id"],
        expected_statuses={
            "jit_ready",
        },
        new_status="funds_held_on_main",
        username="arnold",
        action="funds_held_on_main",
        details={
            "gate_write_performed": False,
        },
        simulation=False,
        completed=True,
    )

    # Simulate process death after lifecycle commit but
    # before release_withdrawal_lock().
    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )

    result = (
        treasury_api
        .hold_treasury_withdrawal_funds_on_main(
            row["request_id"],
            TreasuryWithdrawalCancellationRequest(
                confirmation=(
                    withdrawal_hold_on_main_confirmation_text(
                        row["request_id"]
                    )
                ),
                reason="Recovery replay releases stranded lock.",
            ),
            user=_user(),
        )
    )

    assert result["idempotent_replay"] is True
    assert result["lock_released"] is True

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )
