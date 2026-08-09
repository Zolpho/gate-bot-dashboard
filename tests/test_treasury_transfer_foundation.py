from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect

from app.accounts import GateAccountConfig
from app.config import Settings
from app.migrations import migrate_database
from app.treasury_transfer import (
    build_gate_subaccount_transfer_payload,
)
from app.treasury_transfer_audit import (
    list_transfer_reconciliations,
    mark_transfer_request,
    record_transfer_reconciliation,
    reserve_live_transfer,
)
from app.treasury_transfer_live_policy import (
    evaluate_live_transfer_policy,
)
from app.treasury_transfer_locks import (
    TreasuryTransferLocked,
    acquire_transfer_lock,
    release_transfer_lock,
)


def source_account() -> GateAccountConfig:
    return GateAccountConfig(
        id="arnold",
        name="Arnold",
        api_key="monitor-key",
        api_secret="monitor-secret",
        enabled=True,
        account_type="subaccount",
        gate_uid="12345678",
    )


def settings(
    *,
    armed: bool,
    accounts: str,
) -> Settings:
    return Settings(
        _env_file=None,
        treasury_transfers_live_armed=armed,
        treasury_transfers_live_accounts=accounts,
    )


def test_treasury_live_defaults_are_disarmed() -> None:
    value = Settings(_env_file=None)

    assert (
        value.treasury_transfers_live_armed
        is False
    )

    assert (
        value.treasury_transfers_live_accounts
        == ""
    )

    assert (
        value.treasury_transfer_confirmation_text
        == "LIVE TRANSFER"
    )


def test_treasury_live_account_allowlist() -> None:
    value = settings(
        armed=True,
        accounts="arnold, eqtydao",
    )

    assert (
        value.treasury_transfers_live_account_allowed(
            "arnold"
        )
        is True
    )

    assert (
        value.treasury_transfers_live_account_allowed(
            "reserves"
        )
        is False
    )


def test_live_policy_requires_arm_and_allowlist() -> None:
    disarmed = evaluate_live_transfer_policy(
        settings=settings(
            armed=False,
            accounts="arnold",
        ),
        source_account_id="arnold",
        currency="USDT",
        requested_amount=Decimal("1"),
        available_amount=Decimal("10"),
    )

    assert disarmed.allowed is False
    assert disarmed.reason == "live_not_armed"

    excluded = evaluate_live_transfer_policy(
        settings=settings(
            armed=True,
            accounts="eqtydao",
        ),
        source_account_id="arnold",
        currency="USDT",
        requested_amount=Decimal("1"),
        available_amount=Decimal("10"),
    )

    assert excluded.allowed is False
    assert (
        excluded.reason
        == "source_account_not_live_enabled"
    )


def test_live_policy_uses_available_balance() -> None:
    allowed = evaluate_live_transfer_policy(
        settings=settings(
            armed=True,
            accounts="arnold",
        ),
        source_account_id="arnold",
        currency="USDT",
        requested_amount=Decimal("1"),
        available_amount=Decimal("10"),
    )

    assert allowed.allowed is True

    denied = evaluate_live_transfer_policy(
        settings=settings(
            armed=True,
            accounts="arnold",
        ),
        source_account_id="arnold",
        currency="USDT",
        requested_amount=Decimal("11"),
        available_amount=Decimal("10"),
    )

    assert denied.allowed is False
    assert (
        denied.reason
        == "insufficient_available_balance"
    )


def test_gate_transfer_payload_is_sub_to_main() -> None:
    payload = (
        build_gate_subaccount_transfer_payload(
            source_account=source_account(),
            currency="usdt",
            amount=Decimal("1.25"),
            request_id=(
                "treasury-live-test-request-001"
            ),
        )
    )

    assert payload["sub_account"] == "12345678"
    assert payload["sub_account_type"] == "spot"
    assert payload["currency"] == "USDT"
    assert payload["amount"] == "1.25"
    assert payload["direction"] == "from"

    assert (
        len(payload["client_order_id"])
        <= 64
    )


def test_transfer_lock_serializes_source_currency() -> None:
    suffix = uuid4().hex

    first_request = f"lock-first-{suffix}"
    second_request = f"lock-second-{suffix}"

    acquire_transfer_lock(
        source_account_id="arnold",
        currency="USDT",
        owner_request_id=first_request,
        username="arnold",
    )

    try:
        with pytest.raises(
            TreasuryTransferLocked,
        ):
            acquire_transfer_lock(
                source_account_id="arnold",
                currency="USDT",
                owner_request_id=second_request,
                username="arnold",
            )

    finally:
        release_transfer_lock(
            source_account_id="arnold",
            currency="USDT",
            owner_request_id=first_request,
        )


def test_live_transfer_audit_and_reconciliation() -> None:
    request_id = (
        "foundation-"
        + uuid4().hex
    )

    payload = {
        "operation": "subaccount_to_main",
        "source_account_id": "arnold",
        "destination_account_id": "zolnode",
        "direction": "from",
        "currency": "USDT",
        "amount": "1",
    }

    first, created = reserve_live_transfer(
        request_id=request_id,
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="arnold",
        currency="USDT",
        amount=Decimal("1"),
        payload=payload,
    )

    assert created is True
    assert first["status"] == "reserved"
    assert first["simulation"] is False
    assert first["write_performed"] is False

    second, created_again = reserve_live_transfer(
        request_id=request_id,
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="arnold",
        currency="USDT",
        amount=Decimal("1"),
        payload=payload,
    )

    assert created_again is False
    assert (
        second["request_id"]
        == first["request_id"]
    )

    updated = mark_transfer_request(
        request_id,
        status="success",
        response={
            "tx_id": "12345",
            "status": "SUCCESS",
        },
        gate_transfer_id="12345",
        write_performed=True,
        completed=True,
    )

    assert updated["status"] == "success"
    assert updated["write_performed"] is True
    assert updated["gate_transfer_id"] == "12345"

    record_transfer_reconciliation(
        request_id=request_id,
        source_account_id="arnold",
        username="arnold",
        outcome="success",
        confidence="definitive",
        gate_status="SUCCESS",
        tx_id="12345",
        summary="Gate confirmed transfer success.",
        details={
            "status": "SUCCESS",
        },
    )

    rows = list_transfer_reconciliations(
        request_id
    )

    assert len(rows) == 1
    assert rows[0]["outcome"] == "success"
    assert rows[0]["confidence"] == "definitive"


def test_migration_creates_transfer_safety_tables(
    tmp_path,
) -> None:
    db_path = (
        tmp_path
        / "treasury-transfer-foundation.db"
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

        assert (
            "treasury_transfer_reconciliations"
            in names
        )

        assert (
            "treasury_transfer_operation_locks"
            in names
        )

    finally:
        engine.dispose()
