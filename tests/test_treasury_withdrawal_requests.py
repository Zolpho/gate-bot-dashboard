from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import (
    create_engine,
    func,
    inspect,
    select,
)

import app.api.treasury as treasury_api
from app.api.treasury import (
    TreasuryWithdrawalSimulationRequest,
)
from app.db import init_db, session_scope
from app.migrations import migrate_database
from app.models import (
    TreasuryWithdrawalOperationLock,
    TreasuryWithdrawalReconciliation,
)
from app.security import DashboardUser
from app.treasury_withdrawal_audit import (
    TreasuryWithdrawalIdempotencyConflict,
    find_matching_withdrawal_request,
    record_withdrawal_simulation,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_test_database():
    # Focused execution of this module does not start
    # FastAPI's lifespan, so initialize the configured
    # /tmp test database explicitly.
    init_db()


def _request_id() -> str:
    return (
        "wd-sim-"
        + uuid4().hex
    )


def _payload(
    request_id: str,
    *,
    amount: str = "5",
):
    return {
        "operation": (
            "external_withdrawal_simulation"
        ),
        "owner_account_id": "arnold",
        "custody_account_id": "zolnode",
        "destination_id": (
            "wd_0123456789abcdef"
            "0123456789abcdef"
        ),
        "currency": "USDT",
        "amount": amount,
    }


def _destination():
    return {
        "destination_id": (
            "wd_0123456789abcdef"
            "0123456789abcdef"
        ),
        "owner_account_id": "arnold",
        "currency": "USDT",
        "chain": "ARBEVM",
        "address": (
            "0x111111111111111111111111"
            "1111111111111111"
        ),
        "memo": "",
        "label": "Approved wallet",
        "status": "approved",
        "verification_method": (
            "manual_admin_approval"
        ),
        "approved_by": "rootadmin",
        "approved_at": (
            "2026-08-15T12:30:16+00:00"
        ),
        "valid_for_preflight": True,
    }


def _preflight():
    return {
        "status": "ready",
        "preflight_valid": True,
        "executable": False,
        "execution_block_reason": (
            "withdrawal_execution_not_enabled"
        ),
        "gate_write_performed": False,
        "destination": _destination(),
        "funding": {
            "economic_available": "493.6",
            "withdrawal_funding_available": (
                "493.6"
            ),
            "source_spot_available": "492.6",
            "owner_main_held": "1",
            "owner_liquid_main_held": "1",
            "conservative_funding_required": (
                "5.05"
            ),
            "jit_required": True,
            "minimum_jit_transfer": "4.05",
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
            "destination_approved": True,
            "destination_memo_valid": True,
        },
        "errors": [],
    }


def test_withdrawal_request_tables_migrate(
    tmp_path,
) -> None:
    path = (
        tmp_path
        / "withdrawal-request-migration.db"
    )

    engine = create_engine(
        f"sqlite:///{path}"
    )

    migrate_database(engine)

    tables = set(
        inspect(engine).get_table_names()
    )

    assert (
        "treasury_withdrawal_requests"
        in tables
    )

    assert (
        "treasury_withdrawal_reconciliations"
        in tables
    )

    assert (
        "treasury_withdrawal_operation_locks"
        in tables
    )


def test_withdrawal_simulation_records_snapshot():
    request_id = _request_id()
    payload = _payload(request_id)
    destination = _destination()
    preflight = _preflight()

    row, created = (
        record_withdrawal_simulation(
            request_id=request_id,
            owner_account_id="arnold",
            custody_account_id="zolnode",
            username="arnold",
            destination_id=(
                destination["destination_id"]
            ),
            currency="USDT",
            chain="ARBEVM",
            address=destination["address"],
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
            preflight=preflight,
            destination_snapshot=destination,
        )
    )

    assert created is True
    assert row["status"] == "simulated"
    assert row["simulation"] is True
    assert row["write_performed"] is False

    assert row["chain"] == "ARBEVM"

    assert (
        row["address"]
        == destination["address"]
    )

    assert (
        row["estimated_fee"]
        == "0.05"
    )

    assert (
        row["conservative_funding_required"]
        == "5.05"
    )

    assert (
        row["minimum_jit_transfer"]
        == "4.05"
    )

    assert (
        row["destination_snapshot"]["status"]
        == "approved"
    )

    assert (
        row["gate_withdraw_order_id"]
        is None
    )

    assert (
        row["gate_withdrawal_id"]
        is None
    )

    assert row["gate_txid"] is None


def test_withdrawal_simulation_is_idempotent():
    request_id = _request_id()
    payload = _payload(request_id)
    destination = _destination()

    kwargs = {
        "request_id": request_id,
        "owner_account_id": "arnold",
        "custody_account_id": "zolnode",
        "username": "arnold",
        "destination_id": (
            destination["destination_id"]
        ),
        "currency": "USDT",
        "chain": "ARBEVM",
        "address": destination["address"],
        "memo": "",
        "amount": Decimal("5"),
        "estimated_fee": Decimal("0.05"),
        "conservative_funding_required": (
            Decimal("5.05")
        ),
        "minimum_jit_transfer": (
            Decimal("4.05")
        ),
        "jit_required": True,
        "payload": payload,
        "preflight": _preflight(),
        "destination_snapshot": destination,
    }

    first, created_first = (
        record_withdrawal_simulation(
            **kwargs
        )
    )

    second, created_second = (
        record_withdrawal_simulation(
            **kwargs
        )
    )

    assert created_first is True
    assert created_second is False

    assert (
        first["request_id"]
        == second["request_id"]
    )


def test_withdrawal_request_id_conflict_fails_closed():
    request_id = _request_id()
    destination = _destination()

    record_withdrawal_simulation(
        request_id=request_id,
        owner_account_id="arnold",
        custody_account_id="zolnode",
        username="arnold",
        destination_id=(
            destination["destination_id"]
        ),
        currency="USDT",
        chain="ARBEVM",
        address=destination["address"],
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
        payload=_payload(
            request_id,
            amount="5",
        ),
        preflight=_preflight(),
        destination_snapshot=destination,
    )

    with pytest.raises(
        TreasuryWithdrawalIdempotencyConflict
    ):
        find_matching_withdrawal_request(
            request_id=request_id,
            owner_account_id="arnold",
            username="arnold",
            payload=_payload(
                request_id,
                amount="6",
            ),
        )


def test_withdrawal_simulation_request_forbids_destination_override_fields():
    base = {
        "request_id": _request_id(),
        "owner_account_id": "arnold",
        "destination_id": (
            "wd_0123456789abcdef"
            "0123456789abcdef"
        ),
        "currency": "USDT",
        "amount": "5",
    }

    for field, value in (
        ("chain", "ETH"),
        (
            "address",
            "0x222222222222222222222222"
            "2222222222222222",
        ),
        ("memo", "malicious override"),
    ):
        with pytest.raises(
            ValidationError
        ):
            TreasuryWithdrawalSimulationRequest(
                **base,
                **{
                    field: value,
                },
            )


@pytest.mark.asyncio
async def test_withdrawal_simulation_api_records_no_lock_or_reconciliation(
    monkeypatch,
):
    request_id = _request_id()
    calls = 0

    async def fake_preflight(
        currency,
        *,
        user,
        owner_account_id,
        destination_id,
        amount,
    ):
        nonlocal calls
        calls += 1

        assert currency == "USDT"
        assert owner_account_id == "arnold"

        assert (
            destination_id.startswith("wd_")
        )

        assert amount == Decimal("5")

        return {
            "preflight": _preflight(),
        }

    monkeypatch.setattr(
        treasury_api,
        "treasury_withdrawal_preflight",
        fake_preflight,
    )

    user = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )

    result = await (
        treasury_api
        .simulate_treasury_withdrawal_request(
            TreasuryWithdrawalSimulationRequest(
                request_id=request_id,
                owner_account_id="arnold",
                destination_id=(
                    "wd_0123456789abcdef"
                    "0123456789abcdef"
                ),
                currency="USDT",
                amount=Decimal("5"),
            ),
            user=user,
        )
    )

    assert calls == 1
    assert result["status"] == "ready"
    assert result["audit_recorded"] is True
    assert result["audit_created"] is True

    assert (
        result["gate_write_performed"]
        is False
    )

    assert result["executable"] is False

    with session_scope() as db:
        locks = db.scalar(
            select(func.count())
            .select_from(
                TreasuryWithdrawalOperationLock
            )
            .where(
                TreasuryWithdrawalOperationLock
                .owner_request_id
                == request_id
            )
        )

        reconciliations = db.scalar(
            select(func.count())
            .select_from(
                TreasuryWithdrawalReconciliation
            )
            .where(
                TreasuryWithdrawalReconciliation
                .request_id
                == request_id
            )
        )

    assert locks == 0
    assert reconciliations == 0


@pytest.mark.asyncio
async def test_withdrawal_simulation_api_replay_skips_fresh_gate_preflight(
    monkeypatch,
):
    request_id = _request_id()
    calls = 0

    async def fake_preflight(
        currency,
        *,
        user,
        owner_account_id,
        destination_id,
        amount,
    ):
        nonlocal calls
        calls += 1

        return {
            "preflight": _preflight(),
        }

    monkeypatch.setattr(
        treasury_api,
        "treasury_withdrawal_preflight",
        fake_preflight,
    )

    user = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )

    request = TreasuryWithdrawalSimulationRequest(
        request_id=request_id,
        owner_account_id="arnold",
        destination_id=(
            "wd_0123456789abcdef"
            "0123456789abcdef"
        ),
        currency="USDT",
        amount=Decimal("5"),
    )

    first = await (
        treasury_api
        .simulate_treasury_withdrawal_request(
            request,
            user=user,
        )
    )

    second = await (
        treasury_api
        .simulate_treasury_withdrawal_request(
            request,
            user=user,
        )
    )

    assert calls == 1
    assert first["audit_created"] is True

    assert (
        second["status"]
        == "simulated_replay"
    )

    assert (
        second["idempotent_replay"]
        is True
    )

    assert (
        second["current_preflight_rechecked"]
        is False
    )

    assert (
        second["gate_write_performed"]
        is False
    )
