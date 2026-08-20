from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.db import init_db, session_scope, utcnow
from app.models import TreasuryOwnershipLedgerEntry
from app.treasury_user_transfer import (
    TreasuryUserTransferError,
    execute_user_transfer,
    preview_user_transfer,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_database():
    init_db()


def _seed(
    *,
    owner: str,
    custody: str,
    currency: str,
    amount: Decimal,
    suffix: str,
) -> None:
    with session_scope() as db:
        db.add(
            TreasuryOwnershipLedgerEntry(
                event_id=f"test-user-transfer-seed:{suffix}",
                owner_account_id=owner,
                custody_account_id=custody,
                currency=currency,
                delta_amount=amount,
                entry_type="test_seed",
                source_request_id=(
                    f"test-user-transfer-seed:{suffix}"
                ),
                reason="User transfer test seed.",
                metadata_json=json.dumps(
                    {"test": True}
                ),
                created_at=utcnow(),
            )
        )


def _cleanup(*account_ids: str) -> None:
    with session_scope() as db:
        db.execute(
            delete(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .owner_account_id.in_(
                    list(account_ids)
                )
            )
        )


def test_user_transfer_moves_ownership_atomically():
    suffix = uuid4().hex
    source = f"source-{suffix}"
    destination = f"dest-{suffix}"
    custody = f"custody-{suffix}"

    try:
        _seed(
            owner=source,
            custody=custody,
            currency="USDT",
            amount=Decimal("5"),
            suffix=suffix,
        )

        preview = preview_user_transfer(
            source_account_id=source,
            destination_account_id=destination,
            custody_account_id=custody,
            currency="USDT",
            amount=Decimal("2"),
        )

        assert preview["can_transfer"] is True
        assert preview["source_before"] == "5"
        assert preview["source_after"] == "3"
        assert preview["destination_before"] == "0"
        assert preview["destination_after"] == "2"
        assert preview["gate_write_required"] is False

        result = execute_user_transfer(
            request_id=f"user-transfer-{suffix}",
            username="tester",
            source_account_id=source,
            destination_account_id=destination,
            custody_account_id=custody,
            currency="USDT",
            amount=Decimal("2"),
        )

        assert result["status"] == "success"
        assert result["state_changed"] is True
        assert result["gate_write_performed"] is False
        assert result["source_after"] == "3"
        assert result["destination_after"] == "2"

        after = preview_user_transfer(
            source_account_id=source,
            destination_account_id=destination,
            custody_account_id=custody,
            currency="USDT",
            amount=Decimal("1"),
        )

        assert after["source_before"] == "3"
        assert after["destination_before"] == "2"

    finally:
        _cleanup(source, destination)


def test_user_transfer_replay_is_idempotent():
    suffix = uuid4().hex
    source = f"source-{suffix}"
    destination = f"dest-{suffix}"
    custody = f"custody-{suffix}"
    request_id = f"user-transfer-{suffix}"

    try:
        _seed(
            owner=source,
            custody=custody,
            currency="USDT",
            amount=Decimal("5"),
            suffix=suffix,
        )

        first = execute_user_transfer(
            request_id=request_id,
            username="tester",
            source_account_id=source,
            destination_account_id=destination,
            custody_account_id=custody,
            currency="USDT",
            amount=Decimal("2"),
        )

        replay = execute_user_transfer(
            request_id=request_id,
            username="tester",
            source_account_id=source,
            destination_account_id=destination,
            custody_account_id=custody,
            currency="USDT",
            amount=Decimal("2"),
        )

        assert first["state_changed"] is True
        assert replay["state_changed"] is False
        assert replay["idempotent_replay"] is True
        assert replay["gate_write_performed"] is False

        with session_scope() as db:
            rows = db.scalars(
                db.query(
                    TreasuryOwnershipLedgerEntry
                ).where(
                    TreasuryOwnershipLedgerEntry
                    .source_request_id
                    == request_id
                ).statement
            ).all()

        assert len(rows) == 2

    finally:
        _cleanup(source, destination)


def test_user_transfer_insufficient_balance_has_no_partial_write():
    suffix = uuid4().hex
    source = f"source-{suffix}"
    destination = f"dest-{suffix}"
    custody = f"custody-{suffix}"
    request_id = f"user-transfer-{suffix}"

    try:
        _seed(
            owner=source,
            custody=custody,
            currency="USDT",
            amount=Decimal("1"),
            suffix=suffix,
        )

        with pytest.raises(
            TreasuryUserTransferError,
            match="Insufficient",
        ):
            execute_user_transfer(
                request_id=request_id,
                username="tester",
                source_account_id=source,
                destination_account_id=destination,
                custody_account_id=custody,
                currency="USDT",
                amount=Decimal("2"),
            )

        with session_scope() as db:
            rows = db.scalars(
                db.query(
                    TreasuryOwnershipLedgerEntry
                ).where(
                    TreasuryOwnershipLedgerEntry
                    .source_request_id
                    == request_id
                ).statement
            ).all()

        assert rows == []

    finally:
        _cleanup(source, destination)


def test_user_transfer_rejects_same_owner():
    with pytest.raises(
        TreasuryUserTransferError,
        match="must be different",
    ):
        preview_user_transfer(
            source_account_id="arnold",
            destination_account_id="arnold",
            custody_account_id="zolnode",
            currency="USDT",
            amount=Decimal("1"),
        )


def test_user_transfer_blocked_by_active_transfer_lock():
    from app.treasury_transfer_locks import (
        acquire_transfer_lock,
        release_transfer_lock,
    )

    suffix = uuid4().hex
    source = f"source-{suffix}"
    destination = f"dest-{suffix}"
    custody = f"custody-{suffix}"
    request_id = f"user-transfer-{suffix}"
    lock_request = f"existing-transfer-{suffix}"

    try:
        _seed(
            owner=source,
            custody=custody,
            currency="USDT",
            amount=Decimal("5"),
            suffix=suffix,
        )

        acquire_transfer_lock(
            source_account_id=source,
            currency="USDT",
            owner_request_id=lock_request,
            username="tester",
        )

        preview = preview_user_transfer(
            source_account_id=source,
            destination_account_id=destination,
            custody_account_id=custody,
            currency="USDT",
            amount=Decimal("1"),
        )

        assert preview["can_transfer"] is False
        assert (
            preview["operation_blockers"][0]["type"]
            == "treasury_transfer"
        )

        with pytest.raises(
            TreasuryUserTransferError,
            match="active Treasury operation",
        ):
            execute_user_transfer(
                request_id=request_id,
                username="tester",
                source_account_id=source,
                destination_account_id=destination,
                custody_account_id=custody,
                currency="USDT",
                amount=Decimal("1"),
            )

    finally:
        release_transfer_lock(
            source_account_id=source,
            currency="USDT",
            owner_request_id=lock_request,
        )
        _cleanup(source, destination)


def test_user_transfer_blocked_by_active_withdrawal_lock():
    from app.treasury_withdrawal_locks import (
        acquire_withdrawal_lock,
        release_withdrawal_lock,
    )

    suffix = uuid4().hex
    source = f"source-{suffix}"
    destination = f"dest-{suffix}"
    custody = f"custody-{suffix}"
    request_id = f"user-transfer-{suffix}"
    lock_request = f"existing-withdrawal-{suffix}"

    try:
        _seed(
            owner=source,
            custody=custody,
            currency="USDT",
            amount=Decimal("5"),
            suffix=suffix,
        )

        acquire_withdrawal_lock(
            owner_account_id=source,
            custody_account_id=custody,
            currency="USDT",
            owner_request_id=lock_request,
            username="tester",
        )

        preview = preview_user_transfer(
            source_account_id=source,
            destination_account_id=destination,
            custody_account_id=custody,
            currency="USDT",
            amount=Decimal("1"),
        )

        assert preview["can_transfer"] is False
        assert (
            preview["operation_blockers"][0]["type"]
            == "treasury_withdrawal"
        )

        with pytest.raises(
            TreasuryUserTransferError,
            match="active Treasury operation",
        ):
            execute_user_transfer(
                request_id=request_id,
                username="tester",
                source_account_id=source,
                destination_account_id=destination,
                custody_account_id=custody,
                currency="USDT",
                amount=Decimal("1"),
            )

    finally:
        release_withdrawal_lock(
            custody_account_id=custody,
            currency="USDT",
            owner_request_id=lock_request,
        )
        _cleanup(source, destination)
