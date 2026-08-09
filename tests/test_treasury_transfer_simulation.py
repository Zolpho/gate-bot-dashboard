from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect

from app.accounts import GateAccountConfig
from app.migrations import migrate_database
from app.treasury_transfer import (
    TreasuryTransferValidationError,
    build_subaccount_to_main_preflight,
)
from app.treasury_transfer_audit import (
    TreasuryTransferIdempotencyConflict,
    record_simulation,
)


def source(
    account_id: str = "arnold",
    account_type: str = "subaccount",
) -> GateAccountConfig:
    return GateAccountConfig(
        id=account_id,
        name=account_id,
        api_key="monitor-key",
        api_secret="monitor-secret",
        enabled=True,
        account_type=account_type,
        gate_uid="123456",
    )


def balances(
    available: str = "10",
    locked: str = "0",
):
    return [
        {
            "currency": "USDT",
            "available": available,
            "locked": locked,
        }
    ]


def test_transfer_preflight_valid() -> None:
    result = build_subaccount_to_main_preflight(
        source_account=source(),
        main_account_id="zolnode",
        currency="USDT",
        amount=Decimal("1"),
        spot_accounts=balances("10", "2"),
    )

    assert result["can_simulate"] is True
    assert result["source_account_id"] == "arnold"
    assert result["destination_account_id"] == "zolnode"
    assert result["direction"] == "from"
    assert result["available"] == "10"
    assert result["locked"] == "2"
    assert result["remaining_after_transfer"] == "9"
    assert result["errors"] == []


def test_transfer_preflight_insufficient_balance() -> None:
    result = build_subaccount_to_main_preflight(
        source_account=source(),
        main_account_id="zolnode",
        currency="USDT",
        amount=Decimal("11"),
        spot_accounts=balances("10"),
    )

    assert result["can_simulate"] is False
    assert result["remaining_after_transfer"] is None
    assert "Insufficient available balance" in (
        result["errors"][0]
    )


def test_transfer_preflight_rejects_main_source() -> None:
    with pytest.raises(
        TreasuryTransferValidationError,
        match="do not require",
    ):
        build_subaccount_to_main_preflight(
            source_account=source(
                "zolnode",
                "main",
            ),
            main_account_id="zolnode",
            currency="USDT",
            amount=Decimal("1"),
            spot_accounts=balances(),
        )


def test_transfer_preflight_rejects_non_subaccount() -> None:
    with pytest.raises(
        TreasuryTransferValidationError,
        match="account_type='subaccount'",
    ):
        build_subaccount_to_main_preflight(
            source_account=source(
                "other",
                "main",
            ),
            main_account_id="zolnode",
            currency="USDT",
            amount=Decimal("1"),
            spot_accounts=balances(),
        )


def test_simulation_audit_is_idempotent() -> None:
    payload = {
        "request_id": "t2a-idempotent-001",
        "source_account_id": "arnold",
        "destination_account_id": "zolnode",
        "direction": "from",
        "currency": "USDT",
        "amount": "1",
    }

    first, created_first = record_simulation(
        request_id="t2a-idempotent-001",
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="t2a-test-user",
        currency="USDT",
        amount=Decimal("1"),
        payload=payload,
        response={"status": "ready"},
    )

    second, created_second = record_simulation(
        request_id="t2a-idempotent-001",
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="t2a-test-user",
        currency="USDT",
        amount=Decimal("1"),
        payload=payload,
        response={"status": "ready"},
    )

    assert created_first is True
    assert created_second is False
    assert first["request_id"] == second["request_id"]
    assert first["simulation"] is True
    assert first["write_performed"] is False


def test_simulation_audit_rejects_request_id_reuse() -> None:
    first_payload = {
        "request_id": "t2a-conflict-001",
        "source_account_id": "arnold",
        "destination_account_id": "zolnode",
        "direction": "from",
        "currency": "USDT",
        "amount": "1",
    }

    record_simulation(
        request_id="t2a-conflict-001",
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="t2a-conflict-user",
        currency="USDT",
        amount=Decimal("1"),
        payload=first_payload,
        response={"status": "ready"},
    )

    second_payload = {
        **first_payload,
        "amount": "2",
    }

    with pytest.raises(
        TreasuryTransferIdempotencyConflict,
    ):
        record_simulation(
            request_id="t2a-conflict-001",
            source_account_id="arnold",
            destination_account_id="zolnode",
            username="t2a-conflict-user",
            currency="USDT",
            amount=Decimal("2"),
            payload=second_payload,
            response={"status": "ready"},
        )


def test_migration_creates_treasury_transfer_table(
    tmp_path,
) -> None:
    db_path = (
        tmp_path
        / "treasury-transfer-migration.db"
    )

    engine = create_engine(
        f"sqlite:///{db_path}"
    )

    try:
        migrate_database(engine)

        names = set(
            inspect(engine).get_table_names()
        )

        assert (
            "treasury_transfer_requests"
            in names
        )

    finally:
        engine.dispose()
