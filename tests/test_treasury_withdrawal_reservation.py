from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import (
    create_engine,
    delete,
    inspect,
)

import app.api.treasury as treasury_api
from app.api.treasury import (
    TreasuryWithdrawalCancellationRequest,
    TreasuryWithdrawalConfirmationRequest,
    TreasuryWithdrawalReservationRequest,
)
from app.db import init_db, session_scope
from app.migrations import migrate_database
from app.models import (
    TreasuryWithdrawalOperationLock,
)
from app.security import DashboardUser
from app.treasury_withdrawal_audit import (
    get_withdrawal_request,
    list_withdrawal_request_events,
    record_withdrawal_simulation,
)
from app.treasury_withdrawal_locks import (
    TreasuryWithdrawalLocked,
    acquire_withdrawal_lock,
    get_withdrawal_lock_for_request,
    release_withdrawal_lock,
)
from app.treasury_withdrawal_workflow import (
    withdrawal_cancel_confirmation_text,
    withdrawal_confirmation_text,
    withdrawal_reservation_confirmation_text,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_database():
    init_db()


@pytest.fixture(autouse=True)
def _clear_withdrawal_locks():
    def clear():
        with session_scope() as db:
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


def _destination_id() -> str:
    return (
        "wd_"
        + uuid4().hex
    )


def _address() -> str:
    return (
        "0x"
        + uuid4().hex
        + uuid4().hex[:8]
    )


def _preflight(
    *,
    destination_id: str,
    address: str,
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
        "execution_block_reason": (
            "withdrawal_execution_not_enabled"
        ),
        "gate_write_performed": False,
        "destination": {
            "destination_id": destination_id,
            "owner_account_id": "arnold",
            "currency": "USDT",
            "chain": "ARBEVM",
            "address": address,
            "memo": "",
            "status": (
                "approved"
                if valid
                else "revoked"
            ),
            "verification_method": (
                "manual_admin_approval"
            ),
            "valid_for_preflight": valid,
        },
        "funding": {
            "economic_available": "493.6",
            "withdrawal_funding_available": (
                "493.6"
            ),
            "source_spot_available": "492.6",
            "owner_main_held": "1",
            "owner_liquid_main_held": "1",
            "conservative_funding_required": (
                "5"
            ),
            "jit_required": True,
            "minimum_jit_transfer": "4",
        },
        "fee": {
            "estimated_fee": "0.05",
            "estimate_only": True,
            "semantics_verified": False,
        },
        "checks": {
            "destination_owner_match": True,
            "destination_currency_match": True,
            "destination_chain_match": True,
            "destination_approved": valid,
            "destination_memo_valid": True,
        },
        "errors": (
            []
            if valid
            else ["destination_approved"]
        ),
    }


def _create_request(
    *,
    conservative_funding_required: str = "5",
    minimum_jit_transfer: str = "4",
):
    request_id = (
        "wd-reserve-"
        + uuid4().hex
    )

    destination_id = _destination_id()
    address = _address()

    destination = {
        "destination_id": destination_id,
        "owner_account_id": "arnold",
        "currency": "USDT",
        "chain": "ARBEVM",
        "address": address,
        "memo": "",
        "status": "approved",
        "verification_method": (
            "manual_admin_approval"
        ),
    }

    preflight = _preflight(
        destination_id=destination_id,
        address=address,
    )

    preflight["funding"][
        "conservative_funding_required"
    ] = conservative_funding_required

    preflight["funding"][
        "minimum_jit_transfer"
    ] = minimum_jit_transfer

    preflight["funding"]["jit_required"] = (
        Decimal(minimum_jit_transfer)
        > Decimal("0")
    )

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
                Decimal(
                    conservative_funding_required
                )
            ),
            minimum_jit_transfer=(
                Decimal(
                    minimum_jit_transfer
                )
            ),
            jit_required=(
                Decimal(
                    minimum_jit_transfer
                )
                > Decimal("0")
            ),
            payload=payload,
            preflight=preflight,
            destination_snapshot=destination,
        )
    )

    assert created is True

    return (
        row,
        destination_id,
        address,
    )


def _install_preflight(
    monkeypatch,
    *,
    destination_id: str,
    address: str,
    valid: bool = True,
):
    calls = {
        "count": 0,
    }

    async def fake_preflight(
        currency,
        *,
        user,
        owner_account_id,
        destination_id,
        amount,
    ):
        calls["count"] += 1

        assert currency == "USDT"
        assert owner_account_id == "arnold"
        assert amount == Decimal("5")

        return {
            "preflight": _preflight(
                destination_id=(
                    destination_id
                ),
                address=address,
                valid=valid,
            ),
        }

    monkeypatch.setattr(
        treasury_api,
        "treasury_withdrawal_preflight",
        fake_preflight,
    )

    return calls


def test_withdrawal_request_event_table_migrates(
    tmp_path,
):
    path = (
        tmp_path
        / "withdrawal-events.db"
    )

    engine = create_engine(
        f"sqlite:///{path}"
    )

    try:
        migrate_database(engine)

        names = set(
            inspect(engine).get_table_names()
        )

        assert (
            "treasury_withdrawal_request_events"
            in names
        )

    finally:
        engine.dispose()


def test_withdrawal_lock_serializes_main_custody_currency():
    first = (
        "wd-lock-"
        + uuid4().hex
    )

    second = (
        "wd-lock-"
        + uuid4().hex
    )

    lock = acquire_withdrawal_lock(
        owner_account_id="arnold",
        custody_account_id="zolnode",
        currency="USDT",
        owner_request_id=first,
        username="arnold",
    )

    assert (
        lock["lock_key"]
        == "treasury-withdrawal:zolnode:USDT"
    )

    with pytest.raises(
        TreasuryWithdrawalLocked
    ):
        acquire_withdrawal_lock(
            owner_account_id="eqtydao",
            custody_account_id="zolnode",
            currency="USDT",
            owner_request_id=second,
            username="eqtydao",
        )

    release_withdrawal_lock(
        custody_account_id="zolnode",
        currency="USDT",
        owner_request_id=first,
    )


@pytest.mark.asyncio
async def test_reserve_valid_request_acquires_custody_lock(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    calls = _install_preflight(
        monkeypatch,
        destination_id=destination_id,
        address=address,
    )

    result = await (
        treasury_api
        .reserve_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_reservation_confirmation_text(
                        row["request_id"]
                    )
                ),
            ),
            user=_user(),
        )
    )

    assert calls["count"] == 1
    assert result["status"] == "reserved"
    assert result["reservation_created"] is True
    assert result["gate_write_performed"] is False
    assert result["executable"] is False

    lock = result["operation_lock"]

    assert (
        lock["lock_key"]
        == "treasury-withdrawal:zolnode:USDT"
    )

    stored = get_withdrawal_request(
        row["request_id"]
    )

    assert stored is not None
    assert stored["status"] == "reserved"
    assert stored["simulation"] is False
    assert stored["write_performed"] is False

    events = list_withdrawal_request_events(
        row["request_id"]
    )

    assert [
        event["action"]
        for event in events
    ] == ["reserved"]


@pytest.mark.asyncio
async def test_reserve_invalid_preflight_does_not_lock_or_transition(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    _install_preflight(
        monkeypatch,
        destination_id=destination_id,
        address=address,
        valid=False,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .reserve_treasury_withdrawal_request(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_reservation_confirmation_text(
                            row["request_id"]
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409

    stored = get_withdrawal_request(
        row["request_id"]
    )

    assert stored is not None
    assert stored["status"] == "simulated"

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )


@pytest.mark.asyncio
async def test_reserve_rejects_destination_snapshot_mismatch(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    _install_preflight(
        monkeypatch,
        destination_id=destination_id,
        address=(
            "0x"
            + "f" * 40
        ),
        valid=True,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .reserve_treasury_withdrawal_request(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_reservation_confirmation_text(
                            row["request_id"]
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

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )


@pytest.mark.asyncio
async def test_reserve_rejects_legacy_funding_snapshot_before_lock(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request(
            conservative_funding_required="5.05",
            minimum_jit_transfer="4.05",
        )
    )

    calls = _install_preflight(
        monkeypatch,
        destination_id=destination_id,
        address=address,
        valid=True,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .reserve_treasury_withdrawal_request(
                row["request_id"],
                TreasuryWithdrawalReservationRequest(
                    confirmation=(
                        withdrawal_reservation_confirmation_text(
                            row["request_id"]
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert calls["count"] == 1
    assert exc_info.value.status_code == 409

    detail = exc_info.value.detail

    assert (
        detail["reason"]
        == "withdrawal_funding_snapshot_changed"
    )

    assert (
        detail["stored_estimated_fee"]
        == "0.05"
    )

    assert (
        detail["fresh_estimated_fee"]
        == "0.05"
    )

    assert (
        detail[
            "stored_conservative_funding_required"
        ]
        == "5.05"
    )

    assert (
        detail[
            "fresh_conservative_funding_required"
        ]
        == "5"
    )

    assert (
        detail["gate_write_performed"]
        is False
    )

    stored = get_withdrawal_request(
        row["request_id"]
    )

    assert stored is not None
    assert stored["status"] == "simulated"

    # Immutable legacy authority remains historical.
    assert (
        stored[
            "conservative_funding_required"
        ]
        == "5.05"
    )

    assert (
        stored["minimum_jit_transfer"]
        == "4.05"
    )

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )

    assert (
        list_withdrawal_request_events(
            row["request_id"]
        )
        == []
    )

async def test_confirm_valid_request_rechecks_and_keeps_lock(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    calls = _install_preflight(
        monkeypatch,
        destination_id=destination_id,
        address=address,
    )

    reserved = await (
        treasury_api
        .reserve_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_reservation_confirmation_text(
                        row["request_id"]
                    )
                ),
            ),
            user=_user(),
        )
    )

    current = reserved["audit"]

    result = await (
        treasury_api
        .confirm_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalConfirmationRequest(
                confirmation=(
                    withdrawal_confirmation_text(
                        current
                    )
                ),
            ),
            user=_user(),
        )
    )

    assert calls["count"] == 2
    assert result["status"] == "confirmed_ready"
    assert result["confirmation_created"] is True
    assert result["gate_write_performed"] is False
    assert result["executable"] is False

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )

    events = list_withdrawal_request_events(
        row["request_id"]
    )

    assert [
        event["action"]
        for event in events
    ] == [
        "reserved",
        "confirmed_ready",
    ]


@pytest.mark.asyncio
async def test_confirm_requires_exact_confirmation(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    _install_preflight(
        monkeypatch,
        destination_id=destination_id,
        address=address,
    )

    await (
        treasury_api
        .reserve_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_reservation_confirmation_text(
                        row["request_id"]
                    )
                ),
            ),
            user=_user(),
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .confirm_treasury_withdrawal_request(
                row["request_id"],
                TreasuryWithdrawalConfirmationRequest(
                    confirmation="WRONG",
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 400

    stored = get_withdrawal_request(
        row["request_id"]
    )

    assert stored is not None
    assert stored["status"] == "reserved"

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is not None
    )


@pytest.mark.asyncio
async def test_confirm_invalid_preflight_blocks_and_releases_lock(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    calls = {
        "count": 0,
    }

    async def fake_preflight(
        currency,
        *,
        user,
        owner_account_id,
        destination_id,
        amount,
    ):
        calls["count"] += 1

        return {
            "preflight": _preflight(
                destination_id=(
                    destination_id
                ),
                address=address,
                valid=(
                    calls["count"] == 1
                ),
            ),
        }

    monkeypatch.setattr(
        treasury_api,
        "treasury_withdrawal_preflight",
        fake_preflight,
    )

    reserved = await (
        treasury_api
        .reserve_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_reservation_confirmation_text(
                        row["request_id"]
                    )
                ),
            ),
            user=_user(),
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .confirm_treasury_withdrawal_request(
                row["request_id"],
                TreasuryWithdrawalConfirmationRequest(
                    confirmation=(
                        withdrawal_confirmation_text(
                            reserved["audit"]
                        )
                    ),
                ),
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409

    stored = get_withdrawal_request(
        row["request_id"]
    )

    assert stored is not None
    assert stored["status"] == "blocked"
    assert stored["write_performed"] is False

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )

    events = list_withdrawal_request_events(
        row["request_id"]
    )

    assert [
        event["action"]
        for event in events
    ] == [
        "reserved",
        "confirmation_blocked",
    ]


@pytest.mark.asyncio
async def test_cancel_releases_withdrawal_lock(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    _install_preflight(
        monkeypatch,
        destination_id=destination_id,
        address=address,
    )

    await (
        treasury_api
        .reserve_treasury_withdrawal_request(
            row["request_id"],
            TreasuryWithdrawalReservationRequest(
                confirmation=(
                    withdrawal_reservation_confirmation_text(
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
                    "T2C3B local cancellation test "
                    "releases the custody lock."
                ),
            ),
            user=_user(),
        )
    )

    assert result["status"] == "cancelled"
    assert result["cancelled"] is True
    assert result["lock_released"] is True
    assert result["gate_write_performed"] is False

    assert (
        get_withdrawal_lock_for_request(
            row["request_id"]
        )
        is None
    )


@pytest.mark.asyncio
async def test_fresh_preflight_uses_original_amount_precision(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    # Reproduce SQLite Numeric(48, 24) storage scale.
    row = dict(row)
    row["amount"] = Decimal(
        "5.000000000000000000000000"
    )

    # The immutable request payload preserves what the
    # caller actually submitted and what T2C.3A validated.
    row["request"] = dict(
        row["request"]
    )
    row["request"]["amount"] = "5"

    observed = {}

    async def fake_preflight(
        currency,
        *,
        user,
        owner_account_id,
        destination_id,
        amount,
    ):
        observed["amount"] = amount

        return {
            "preflight": _preflight(
                destination_id=destination_id,
                address=address,
                valid=True,
            ),
        }

    monkeypatch.setattr(
        treasury_api,
        "treasury_withdrawal_preflight",
        fake_preflight,
    )

    result = await (
        treasury_api._fresh_request_preflight(
            row=row,
            user=_user(),
        )
    )

    assert result["preflight_valid"] is True

    amount = observed["amount"]

    assert amount == Decimal("5")

    # Equality alone is insufficient:
    # Decimal("5.000") == Decimal("5").
    # We specifically require the original precision.
    assert amount.as_tuple().exponent == 0


@pytest.mark.asyncio
async def test_fresh_preflight_fails_closed_on_amount_snapshot_mismatch(
    monkeypatch,
):
    row, destination_id, address = (
        _create_request()
    )

    row = dict(row)

    row["amount"] = Decimal(
        "6.000000000000000000000000"
    )

    row["request"] = dict(
        row["request"]
    )
    row["request"]["amount"] = "5"

    called = False

    async def fake_preflight(*args, **kwargs):
        nonlocal called
        called = True

        raise AssertionError(
            "Gate/read preflight must not be called "
            "after amount mismatch"
        )

    monkeypatch.setattr(
        treasury_api,
        "treasury_withdrawal_preflight",
        fake_preflight,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            ._fresh_request_preflight(
                row=row,
                user=_user(),
            )
        )

    assert exc_info.value.status_code == 409

    assert (
        exc_info.value.detail["reason"]
        == "withdrawal_amount_snapshot_mismatch"
    )

    assert called is False
