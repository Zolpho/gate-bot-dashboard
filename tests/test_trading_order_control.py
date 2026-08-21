from __future__ import annotations

import re
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.db import (
    init_db,
    session_scope,
)
from app.models import (
    TradingOrderOperationLock,
    TradingOrderReconciliation,
    TradingOrderRequest,
)
from app.trading_order_audit import (
    TradingOrderIdempotencyConflict,
    get_order_request,
    list_order_reconciliations,
    list_order_requests,
    mark_order_request,
    record_order_reconciliation,
    reserve_limit_order,
)
from app.trading_order_identity import (
    gate_text_for_request_id,
)
from app.trading_order_locks import (
    TradingOrderLocked,
    acquire_trading_lock,
    get_trading_lock_for_request,
    release_trading_lock,
)


init_db()


@pytest.fixture(autouse=True)
def clean_trading_order_state():
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TradingOrderOperationLock
                )
            )
            db.execute(
                delete(
                    TradingOrderReconciliation
                )
            )
            db.execute(
                delete(
                    TradingOrderRequest
                )
            )

    clear()
    yield
    clear()


def reserve(
    request_id: str,
    *,
    account_id: str = "arnold",
    username: str = "arnold",
    pair: str = "EQTY_USDT",
    side: str = "buy",
    price: str = "0.0017",
    amount: str = "1000",
    tif: str = "gtc",
    funding_asset: str = "USDT",
):
    return reserve_limit_order(
        request_id=request_id,
        account_id=account_id,
        username=username,
        pair=pair,
        side=side,
        price=Decimal(price),
        amount=Decimal(amount),
        time_in_force=tif,
        funding_asset=(
            funding_asset
        ),
    )


def test_gate_text_is_deterministic_and_gate_safe():
    first = gate_text_for_request_id(
        "user-ui-request-123"
    )

    second = gate_text_for_request_id(
        "user-ui-request-123"
    )

    other = gate_text_for_request_id(
        "different-request"
    )

    assert first == second
    assert first != other

    assert first.startswith("t-")

    assert (
        len(
            first[2:].encode("utf-8")
        )
        <= 28
    )

    assert re.fullmatch(
        r"t-[0-9A-Za-z_.-]+",
        first,
    )


def test_gate_text_rejects_blank_request_id():
    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        gate_text_for_request_id("   ")


def test_reserve_limit_order_persists_intent():
    row, created = reserve(
        "request-a"
    )

    assert created is True
    assert row["status"] == "reserved"
    assert row["account_id"] == "arnold"
    assert row["pair"] == "EQTY_USDT"
    assert row["side"] == "buy"
    assert row["price"] == "0.0017"
    assert row["amount"] == "1000"
    assert row["total"] == "1.7000"
    assert row["funding_asset"] == "USDT"
    assert row["gate_text"].startswith(
        "t-"
    )
    assert row["gate_order_id"] is None
    assert row["write_performed"] is False


def test_identical_request_is_idempotent():
    first, created_first = reserve(
        "request-a"
    )

    second, created_second = reserve(
        "request-a"
    )

    assert created_first is True
    assert created_second is False
    assert (
        second["request_hash"]
        == first["request_hash"]
    )
    assert (
        second["gate_text"]
        == first["gate_text"]
    )


def test_request_id_conflict_is_rejected():
    reserve(
        "request-a",
        amount="1000",
    )

    with pytest.raises(
        TradingOrderIdempotencyConflict,
    ):
        reserve(
            "request-a",
            amount="2000",
        )


def test_mark_order_request_updates_audit():
    reserve(
        "request-a"
    )

    updated = mark_order_request(
        "request-a",
        status="preflight_failed",
        response={
            "reason": "test",
        },
        error="blocked",
        completed=True,
    )

    assert (
        updated["status"]
        == "preflight_failed"
    )
    assert (
        updated["response"]
        == {"reason": "test"}
    )
    assert updated["error"] == "blocked"
    assert (
        updated["write_performed"]
        is False
    )
    assert (
        updated["completed_at"]
        is not None
    )


def test_order_list_is_account_scoped():
    reserve(
        "request-a",
        account_id="arnold",
    )

    reserve(
        "request-b",
        account_id="eqtydao",
        username="eqtydao",
    )

    rows = list_order_requests(
        account_ids={"arnold"}
    )

    assert len(rows) == 1
    assert (
        rows[0]["account_id"]
        == "arnold"
    )


def test_same_funding_asset_blocks_other_pair():
    acquire_trading_lock(
        account_id="arnold",
        funding_asset="USDT",
        pair="EQTY_USDT",
        side="buy",
        owner_request_id="request-a",
        username="arnold",
    )

    with pytest.raises(
        TradingOrderLocked,
    ):
        acquire_trading_lock(
            account_id="arnold",
            funding_asset="USDT",
            pair="BTC_USDT",
            side="buy",
            owner_request_id=(
                "request-b"
            ),
            username="arnold",
        )


def test_different_funding_assets_can_coexist():
    first = acquire_trading_lock(
        account_id="arnold",
        funding_asset="USDT",
        pair="EQTY_USDT",
        side="buy",
        owner_request_id="request-a",
        username="arnold",
    )

    second = acquire_trading_lock(
        account_id="arnold",
        funding_asset="EQTY",
        pair="EQTY_USDT",
        side="sell",
        owner_request_id="request-b",
        username="arnold",
    )

    assert (
        first["lock_key"]
        != second["lock_key"]
    )


def test_same_request_can_reacquire_own_lock():
    first = acquire_trading_lock(
        account_id="arnold",
        funding_asset="USDT",
        pair="EQTY_USDT",
        side="buy",
        owner_request_id="request-a",
        username="arnold",
    )

    second = acquire_trading_lock(
        account_id="arnold",
        funding_asset="USDT",
        pair="EQTY_USDT",
        side="buy",
        owner_request_id="request-a",
        username="arnold",
    )

    assert first == second

    found = (
        get_trading_lock_for_request(
            "request-a"
        )
    )

    assert found is not None
    assert (
        found["owner_request_id"]
        == "request-a"
    )


def test_lock_release_requires_owner():
    acquire_trading_lock(
        account_id="arnold",
        funding_asset="USDT",
        pair="EQTY_USDT",
        side="buy",
        owner_request_id="request-a",
        username="arnold",
    )

    assert (
        release_trading_lock(
            account_id="arnold",
            funding_asset="USDT",
            owner_request_id=(
                "wrong-request"
            ),
        )
        is False
    )

    assert (
        release_trading_lock(
            account_id="arnold",
            funding_asset="USDT",
            owner_request_id=(
                "request-a"
            ),
        )
        is True
    )


def test_reconciliation_is_persistent():
    reserve(
        "request-a"
    )

    saved = (
        record_order_reconciliation(
            request_id="request-a",
            account_id="arnold",
            username="arnold",
            pair="EQTY_USDT",
            outcome="not_found",
            confidence="inconclusive",
            gate_status="",
            summary=(
                "No Gate order evidence."
            ),
            details={
                "read_only": True,
            },
        )
    )

    assert (
        saved["outcome"]
        == "not_found"
    )

    rows = (
        list_order_reconciliations(
            "request-a"
        )
    )

    assert len(rows) == 1
    assert (
        rows[0]["details"][
            "read_only"
        ]
        is True
    )

    request = get_order_request(
        "request-a"
    )

    assert request is not None
    assert (
        request["write_performed"]
        is False
    )
