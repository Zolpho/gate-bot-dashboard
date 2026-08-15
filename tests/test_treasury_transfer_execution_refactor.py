from __future__ import annotations

import inspect
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.accounts import GateAccountConfig
from app.db import init_db, session_scope
from app.gate_client import GateResponse
from app.models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryTransferReconciliation,
    TreasuryTransferRequest,
)
from app.treasury_transfer_audit import (
    mark_transfer_request,
    reserve_live_transfer,
)
from app.treasury_transfer_execution import (
    execute_reserved_live_transfer,
    existing_live_transfer_result,
    reconcile_live_transfer,
)
from app.treasury_transfer_locks import (
    acquire_transfer_lock,
    get_transfer_lock_for_request,
)
from app.config import Settings


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_database():
    init_db()


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


def test_terminal_existing_transfer_is_safe_replay():
    result = existing_live_transfer_result(
        {
            "request_id": "existing-success",
            "status": "success",
            "write_performed": True,
        }
    )

    assert result["status"] == "success"
    assert result["idempotent_replay"] is True

    assert (
        result["gate_write_performed"]
        is True
    )


def test_nonterminal_existing_transfer_blocks_retry():
    with pytest.raises(
        HTTPException,
    ) as captured:
        existing_live_transfer_result(
            {
                "request_id": "existing-pending",
                "status": "pending",
                "write_performed": True,
            }
        )

    assert captured.value.status_code == 409

    assert (
        captured.value.detail["status"]
        == "pending"
    )

    assert (
        captured.value.detail[
            "write_performed"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_reconcile_success_releases_lock(
    monkeypatch,
):
    from app import treasury_transfer_execution

    request_id = (
        "t2c4a-reconcile-"
        + uuid4().hex
    )

    event_id = (
        "internal-transfer-credit:"
        + request_id
    )

    payload = {
        "operation": "subaccount_to_main",
        "source_account_id": "arnold",
        "destination_account_id": "zolnode",
        "gate_payload": {
            "sub_account": "58601346",
            "sub_account_type": "spot",
            "currency": "USDT",
            "amount": "1",
            "direction": "from",
            "client_order_id": (
                "t2c4a-test-order"
            ),
        },
    }

    record, created = reserve_live_transfer(
        request_id=request_id,
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="arnold",
        currency="USDT",
        amount=Decimal("1"),
        payload=payload,
    )

    assert created is True

    acquire_transfer_lock(
        source_account_id="arnold",
        currency="USDT",
        owner_request_id=request_id,
        username="arnold",
    )

    record = mark_transfer_request(
        request_id,
        status="submitted",
        response={
            "tx_id": "test-tx",
        },
        gate_transfer_id="test-tx",
        write_performed=True,
        completed=False,
    )

    class FakeGateClient:
        def __init__(
            self,
            settings,
            account,
        ):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(
            self,
            exc_type,
            exc,
            tb,
        ):
            return None

        async def get_transfer_order_status(
            self,
            *,
            client_order_id=None,
            tx_id=None,
        ):
            return GateResponse(
                data={
                    "status": "SUCCESS",
                    "tx_id": "test-tx",
                },
                status_code=200,
                headers={},
                raw={
                    "status": "SUCCESS",
                    "tx_id": "test-tx",
                },
            )

    monkeypatch.setattr(
        treasury_transfer_execution,
        "GateClient",
        FakeGateClient,
    )

    try:
        result = await reconcile_live_transfer(
            settings=Settings(
                _env_file=None
            ),
            record=record,
            treasury_account=(
                _treasury_account()
            ),
        )

        assert result["status"] == "success"

        assert (
            result["lock_released"]
            is True
        )

        assert (
            get_transfer_lock_for_request(
                request_id
            )
            is None
        )

        assert (
            result["audit"]["write_performed"]
            is True
        )

    finally:
        from sqlalchemy import delete

        from app.models import (
            TreasuryTransferOperationLock,
        )

        with session_scope() as db:
            db.execute(
                delete(
                    TreasuryTransferOperationLock
                ).where(
                    TreasuryTransferOperationLock
                    .owner_request_id
                    == request_id
                )
            )

            db.execute(
                delete(
                    TreasuryTransferReconciliation
                ).where(
                    TreasuryTransferReconciliation
                    .request_id
                    == request_id
                )
            )

            db.execute(
                delete(
                    TreasuryOwnershipLedgerEntry
                ).where(
                    TreasuryOwnershipLedgerEntry
                    .event_id
                    == event_id
                )
            )

            db.execute(
                delete(
                    TreasuryTransferRequest
                ).where(
                    TreasuryTransferRequest
                    .request_id
                    == request_id
                )
            )


def test_executor_contains_exactly_one_transfer_post():
    source = inspect.getsource(
        execute_reserved_live_transfer
    )

    assert (
        source.count(
            "create_sub_account_transfer("
        )
        == 1
    )

    assert '"/withdrawals"' not in source
