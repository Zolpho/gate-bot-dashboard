from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from app.accounts import GateAccountConfig
from app.config import Settings
from app.db import init_db, session_scope
from app.gate_client import (
    GateClient,
    GateResponse,
)
from app.models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryWithdrawalRequest,
)
from app.treasury_ownership import (
    ownership_amount,
)
from app.treasury_withdrawal_audit import (
    get_withdrawal_request,
)
from app.treasury_withdrawal_locks import (
    acquire_withdrawal_lock,
    get_withdrawal_lock_for_request,
    release_withdrawal_lock,
)
from app.treasury_withdrawal_settlement import (
    TreasuryWithdrawalSettlementError,
    apply_withdrawal_ownership_settlement,
    settle_withdrawal_from_gate,
    withdrawal_debit_event_id,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_settlement_test_database():
    # This module must also work when executed alone.
    # conftest configures the test DB, but another test
    # module / TestClient must not be required to create
    # its schema.
    init_db()


def _seed(
    *,
    ownership: str = "2",
    request_amount: str = "1",
) -> tuple[
    str,
    str,
    dict,
]:
    token = uuid4().hex

    owner = (
        "settlement-owner-"
        + token[:12]
    )

    request_id = (
        "wd-settlement-"
        + token
    )

    order_id = (
        "wd_"
        + token[:29]
    )

    withdrawal_id = (
        "w"
        + token[:20]
    )

    txid = (
        "0x"
        + token
    )

    with session_scope() as db:
        db.add(
            TreasuryOwnershipLedgerEntry(
                event_id=(
                    "settlement-seed:"
                    + token
                ),
                owner_account_id=owner,
                custody_account_id=(
                    "zolnode"
                ),
                currency="USDT",
                delta_amount=Decimal(
                    ownership
                ),
                entry_type=(
                    "internal_transfer_credit"
                ),
                source_request_id=(
                    "seed-"
                    + token
                ),
                reason="Settlement test seed.",
                metadata_json="{}",
            )
        )

        db.add(
            TreasuryWithdrawalRequest(
                request_id=request_id,
                owner_account_id=owner,
                custody_account_id=(
                    "zolnode"
                ),
                username=owner,
                destination_id=(
                    "wd_test_destination"
                ),
                currency="USDT",
                chain="ETH",
                address=(
                    "0x111111111111111111111111"
                    "1111111111111111"
                ),
                memo="",
                amount=Decimal(
                    request_amount
                ),
                estimated_fee=(
                    Decimal("1")
                ),
                conservative_funding_required=(
                    Decimal("2")
                ),
                minimum_jit_transfer=(
                    Decimal("0")
                ),
                jit_required=False,
                status=(
                    "withdrawal_done_unsettled"
                ),
                request_hash=(
                    "a" * 64
                ),
                request_json="{}",
                preflight_json="{}",
                destination_snapshot_json="{}",
                gate_withdraw_order_id=(
                    order_id
                ),
                gate_withdrawal_id=(
                    withdrawal_id
                ),
                gate_txid=txid,
                gate_status="DONE",
                error="",
                simulation=False,
                write_performed=True,
            )
        )

    gate_record = {
        "id": withdrawal_id,
        "withdraw_order_id": order_id,
        "currency": "USDT",
        "amount": request_amount,
        "fee": "1",
        "address": (
            "0x111111111111111111111111"
            "1111111111111111"
        ),
        "memo": "",
        "chain": "ETH",
        "status": "DONE",
        "block_number": "123456",
        "txid": txid,
    }

    return (
        owner,
        request_id,
        gate_record,
    )


def test_settlement_debits_gate_record_amount_not_amount_plus_fee():
    (
        owner,
        request_id,
        record,
    ) = _seed(
        ownership="2",
        request_amount="1",
    )

    result = (
        apply_withdrawal_ownership_settlement(
            request_id=request_id,
            username=owner,
            gate_record=record,
        )
    )

    assert (
        result["status"]
        == "withdrawal_settled"
    )

    assert (
        result["settlement_amount"]
        == "1"
    )

    assert result["gate_fee"] == "1"

    # Critical fee-semantics regression:
    # Gate record amount=1 and fee=1 causes
    # ONE ownership unit to be consumed,
    # not two.
    assert (
        result["ownership_before"]
        == "2"
    )

    assert (
        result["ownership_after"]
        == "1"
    )

    assert (
        ownership_amount(
            owner_account_id=owner,
            custody_account_id="zolnode",
            currency="USDT",
        )
        == Decimal("1")
    )

    row = get_withdrawal_request(
        request_id
    )

    assert row is not None

    assert (
        row["status"]
        == "withdrawal_settled"
    )


def test_settlement_is_idempotent_and_never_double_debits():
    (
        owner,
        request_id,
        record,
    ) = _seed()

    first = (
        apply_withdrawal_ownership_settlement(
            request_id=request_id,
            username=owner,
            gate_record=record,
        )
    )

    second = (
        apply_withdrawal_ownership_settlement(
            request_id=request_id,
            username=owner,
            gate_record=record,
        )
    )

    assert (
        first["ownership_ledger_changed"]
        is True
    )

    assert (
        second["ownership_ledger_changed"]
        is False
    )

    assert second["idempotent_replay"] is True

    assert (
        second["ledger_event_id"]
        == withdrawal_debit_event_id(
            request_id
        )
    )

    assert (
        ownership_amount(
            owner_account_id=owner,
            custody_account_id="zolnode",
            currency="USDT",
        )
        == Decimal("1")
    )


def test_settlement_rejects_gate_amount_mismatch():
    (
        owner,
        request_id,
        record,
    ) = _seed()

    record = dict(record)
    record["amount"] = "1.5"

    with pytest.raises(
        TreasuryWithdrawalSettlementError,
        match="amount mismatch",
    ):
        apply_withdrawal_ownership_settlement(
            request_id=request_id,
            username=owner,
            gate_record=record,
        )

    assert (
        ownership_amount(
            owner_account_id=owner,
            custody_account_id="zolnode",
            currency="USDT",
        )
        == Decimal("2")
    )

    row = get_withdrawal_request(
        request_id
    )

    assert row is not None

    assert (
        row["status"]
        == "withdrawal_done_unsettled"
    )


def test_settlement_rejects_insufficient_owner_ownership():
    (
        owner,
        request_id,
        record,
    ) = _seed(
        ownership="0.5",
    )

    with pytest.raises(
        TreasuryWithdrawalSettlementError,
        match="insufficient",
    ):
        apply_withdrawal_ownership_settlement(
            request_id=request_id,
            username=owner,
            gate_record=record,
        )

    assert (
        ownership_amount(
            owner_account_id=owner,
            custody_account_id="zolnode",
            currency="USDT",
        )
        == Decimal("0.5")
    )

    row = get_withdrawal_request(
        request_id
    )

    assert row is not None

    assert (
        row["status"]
        == "withdrawal_done_unsettled"
    )


def test_settlement_requires_done_with_positive_block():
    (
        owner,
        request_id,
        record,
    ) = _seed()

    record = dict(record)
    record["block_number"] = "0"

    with pytest.raises(
        TreasuryWithdrawalSettlementError,
        match="on-chain",
    ):
        apply_withdrawal_ownership_settlement(
            request_id=request_id,
            username=owner,
            gate_record=record,
        )



def _settlement_settings(
    *,
    armed: bool = False,
) -> Settings:
    return Settings(
        _env_file=None,
        treasury_main_account="zolnode",
        treasury_withdrawals_live_armed=(
            armed
        ),
    )


def _settlement_treasury_account(
) -> GateAccountConfig:
    return GateAccountConfig(
        id="zolnode",
        name="zolnode",
        api_key="treasury-test-key",
        api_secret="treasury-test-secret",
        enabled=True,
        account_type="main",
        gate_uid="13079163",
    )


def test_gate_verified_settlement_releases_lock(
    monkeypatch,
):
    (
        owner,
        request_id,
        record,
    ) = _seed(
        ownership="2",
        request_amount="1",
    )

    acquire_withdrawal_lock(
        owner_account_id=owner,
        custody_account_id="zolnode",
        currency="USDT",
        owner_request_id=request_id,
        username=owner,
    )

    calls = []

    async def fake_list_withdrawals(
        self,
        **kwargs,
    ):
        calls.append(kwargs)

        return GateResponse(
            data=[record],
            status_code=200,
            headers={},
            raw=[record],
        )

    monkeypatch.setattr(
        GateClient,
        "list_withdrawals",
        fake_list_withdrawals,
    )

    try:
        result = asyncio.run(
            settle_withdrawal_from_gate(
                settings=(
                    _settlement_settings()
                ),
                request_id=request_id,
                username=owner,
                treasury_account=(
                    _settlement_treasury_account()
                ),
            )
        )

        assert (
            result["status"]
            == "withdrawal_settled"
        )

        assert (
            result[
                "ownership_settlement_performed"
            ]
            is True
        )

        assert (
            result["ownership_ledger_changed"]
            is True
        )

        assert (
            result["settlement_amount"]
            == "1"
        )

        assert (
            result["gate_fee"]
            == "1"
        )

        assert (
            result["gate_read_performed"]
            is True
        )

        assert (
            result["gate_write_performed"]
            is False
        )

        assert (
            result["lock_released"]
            is True
        )

        assert (
            get_withdrawal_lock_for_request(
                request_id
            )
            is None
        )

        assert len(calls) == 1

        assert (
            calls[0]["currency"]
            == "USDT"
        )

        assert (
            calls[0][
                "withdraw_order_id"
            ]
            == record[
                "withdraw_order_id"
            ]
        )

        assert (
            ownership_amount(
                owner_account_id=owner,
                custody_account_id="zolnode",
                currency="USDT",
            )
            == Decimal("1")
        )

        # Replay proves both the ledger debit and
        # Gate GET are idempotent after settlement.
        replay = asyncio.run(
            settle_withdrawal_from_gate(
                settings=(
                    _settlement_settings()
                ),
                request_id=request_id,
                username=owner,
                treasury_account=None,
            )
        )

        assert (
            replay["status"]
            == "withdrawal_settled"
        )

        assert (
            replay["idempotent_replay"]
            is True
        )

        assert (
            replay["ownership_ledger_changed"]
            is False
        )

        assert (
            replay["gate_read_performed"]
            is False
        )

        assert (
            replay["gate_write_performed"]
            is False
        )

        assert len(calls) == 1

        assert (
            ownership_amount(
                owner_account_id=owner,
                custody_account_id="zolnode",
                currency="USDT",
            )
            == Decimal("1")
        )

    finally:
        release_withdrawal_lock(
            custody_account_id="zolnode",
            currency="USDT",
            owner_request_id=request_id,
        )


def test_gate_record_mismatch_blocks_settlement(
    monkeypatch,
):
    (
        owner,
        request_id,
        record,
    ) = _seed(
        ownership="2",
        request_amount="1",
    )

    acquire_withdrawal_lock(
        owner_account_id=owner,
        custody_account_id="zolnode",
        currency="USDT",
        owner_request_id=request_id,
        username=owner,
    )

    bad_record = dict(record)

    bad_record["address"] = (
        "0x222222222222222222222222"
        "2222222222222222"
    )

    async def fake_list_withdrawals(
        self,
        **kwargs,
    ):
        return GateResponse(
            data=[bad_record],
            status_code=200,
            headers={},
            raw=[bad_record],
        )

    monkeypatch.setattr(
        GateClient,
        "list_withdrawals",
        fake_list_withdrawals,
    )

    try:
        with pytest.raises(
            TreasuryWithdrawalSettlementError,
            match="mismatches",
        ):
            asyncio.run(
                settle_withdrawal_from_gate(
                    settings=(
                        _settlement_settings()
                    ),
                    request_id=request_id,
                    username=owner,
                    treasury_account=(
                        _settlement_treasury_account()
                    ),
                )
            )

        row = get_withdrawal_request(
            request_id
        )

        assert row is not None

        assert (
            row["status"]
            == "withdrawal_done_unsettled"
        )

        assert (
            ownership_amount(
                owner_account_id=owner,
                custody_account_id="zolnode",
                currency="USDT",
            )
            == Decimal("2")
        )

        assert (
            get_withdrawal_lock_for_request(
                request_id
            )
            is not None
        )

    finally:
        release_withdrawal_lock(
            custody_account_id="zolnode",
            currency="USDT",
            owner_request_id=request_id,
        )
