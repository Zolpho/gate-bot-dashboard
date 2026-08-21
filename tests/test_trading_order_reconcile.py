from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.db import (
    init_db,
    session_scope,
)
from app.gate_client import (
    GateAPIError,
    GateResponse,
)
from app.models import (
    TradingOrderOperationLock,
    TradingOrderReconciliation,
    TradingOrderRequest,
)
from app.trading_order_audit import (
    get_order_request,
    mark_order_request,
    reserve_limit_order,
)
from app.trading_order_locks import (
    acquire_trading_lock,
    get_trading_lock_for_request,
)
from app.trading_order_reconcile import (
    reconcile_spot_order_request,
)


init_db()


@pytest.fixture(autouse=True)
def clean_state():
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


def gate_response(
    data,
) -> GateResponse:
    return GateResponse(
        data=data,
        status_code=200,
        headers={},
        raw=data,
    )


def gate_order(
    *,
    order_id="12345",
    text="",
    status="open",
    pair="EQTY_USDT",
    side="buy",
    price="0.0017",
    amount="1000",
    tif="gtc",
):
    return {
        "id": order_id,
        "text": text,
        "currency_pair": pair,
        "status": status,
        "type": "limit",
        "account": "spot",
        "side": side,
        "price": price,
        "amount": amount,
        "time_in_force": tif,
        "left": amount,
        "filled_total": "0",
    }


class FakeGateClient:
    def __init__(
        self,
        *,
        single=None,
        single_error=None,
        finished_pages=None,
        finished_error=None,
    ):
        self.single = single
        self.single_error = (
            single_error
        )
        self.finished_pages = (
            finished_pages
            if finished_pages
            is not None
            else [[]]
        )
        self.finished_error = (
            finished_error
        )

        self.single_calls = []
        self.finished_calls = []

    async def get_spot_order(
        self,
        order_id,
        *,
        currency_pair=None,
        account="spot",
    ):
        self.single_calls.append(
            {
                "order_id": order_id,
                "currency_pair": (
                    currency_pair
                ),
                "account": account,
            }
        )

        if self.single_error:
            raise self.single_error

        return gate_response(
            self.single
        )

    async def list_spot_orders(
        self,
        **kwargs,
    ):
        self.finished_calls.append(
            kwargs
        )

        if self.finished_error:
            raise self.finished_error

        page = kwargs["page"]

        data = (
            self.finished_pages[
                page - 1
            ]
            if page
            <= len(
                self.finished_pages
            )
            else []
        )

        return gate_response(
            data
        )


def reserve_request(
    request_id="request-a",
    *,
    write_performed=False,
):
    row, created = reserve_limit_order(
        request_id=request_id,
        account_id="arnold",
        username="arnold",
        pair="EQTY_USDT",
        side="buy",
        price=Decimal("0.0017"),
        amount=Decimal("1000"),
        time_in_force="gtc",
        funding_asset="USDT",
    )

    assert created is True

    acquire_trading_lock(
        account_id="arnold",
        funding_asset="USDT",
        pair="EQTY_USDT",
        side="buy",
        owner_request_id=(
            request_id
        ),
        username="arnold",
    )

    if write_performed:
        row = mark_order_request(
            request_id,
            status="submitting",
            write_performed=True,
        )

    return row


@pytest.mark.asyncio
async def test_no_write_is_definitive_and_releases_lock():
    reserve_request(
        write_performed=False
    )

    client = FakeGateClient()

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
        )
    )

    assert (
        result["outcome"]
        == "not_submitted"
    )
    assert (
        result["confidence"]
        == "definitive"
    )
    assert (
        result["gate_read_performed"]
        is False
    )
    assert (
        result["lock_released"]
        is True
    )

    assert not client.single_calls
    assert not client.finished_calls

    assert (
        get_trading_lock_for_request(
            "request-a"
        )
        is None
    )


@pytest.mark.asyncio
async def test_pending_text_match_is_definitive():
    row = reserve_request(
        write_performed=True
    )

    client = FakeGateClient(
        single=gate_order(
            order_id="777",
            text=row["gate_text"],
            status="open",
        )
    )

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
        )
    )

    assert (
        result["outcome"]
        == "order_found"
    )
    assert (
        result["status"]
        == "confirmed_open"
    )
    assert (
        result["confidence"]
        == "definitive"
    )
    assert (
        result["lock_released"]
        is True
    )

    saved = get_order_request(
        "request-a"
    )

    assert saved is not None
    assert (
        saved["gate_order_id"]
        == "777"
    )


@pytest.mark.asyncio
async def test_finished_history_finds_fast_fill():
    row = reserve_request(
        write_performed=True
    )

    client = FakeGateClient(
        single_error=GateAPIError(
            "not pending",
            status_code=404,
            label="ORDER_NOT_FOUND",
        ),
        finished_pages=[
            [
                gate_order(
                    order_id="888",
                    text=row[
                        "gate_text"
                    ],
                    status="closed",
                )
            ]
        ],
    )

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
            now=datetime(
                2026,
                8,
                21,
                14,
                0,
                tzinfo=timezone.utc,
            ),
        )
    )

    assert (
        result["outcome"]
        == "order_found"
    )
    assert (
        result["status"]
        == "confirmed_closed"
    )
    assert (
        result["lock_released"]
        is True
    )

    assert len(
        client.finished_calls
    ) == 1

    call = client.finished_calls[0]

    assert call["status"] == "finished"
    assert (
        call["currency_pair"]
        == "EQTY_USDT"
    )


@pytest.mark.asyncio
async def test_known_gate_order_id_is_used_first():
    reserve_request(
        write_performed=True
    )

    mark_order_request(
        "request-a",
        status="uncertain",
        gate_order_id="999",
    )

    client = FakeGateClient(
        single=gate_order(
            order_id="999",
            status="cancelled",
        )
    )

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
        )
    )

    assert (
        client.single_calls[0][
            "order_id"
        ]
        == "999"
    )

    assert (
        result["status"]
        == "confirmed_cancelled"
    )


@pytest.mark.asyncio
async def test_matching_text_with_different_intent_is_attention():
    row = reserve_request(
        write_performed=True
    )

    client = FakeGateClient(
        single=gate_order(
            order_id="777",
            text=row["gate_text"],
            status="open",
            amount="2000",
        )
    )

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
        )
    )

    assert (
        result["outcome"]
        == "correlation_conflict"
    )
    assert (
        result[
            "manual_review_required"
        ]
        is True
    )
    assert (
        result["lock_released"]
        is False
    )

    assert (
        get_trading_lock_for_request(
            "request-a"
        )
        is not None
    )


@pytest.mark.asyncio
async def test_not_found_after_write_is_inconclusive():
    reserve_request(
        write_performed=True
    )

    client = FakeGateClient(
        single_error=GateAPIError(
            "not found",
            status_code=404,
            label="ORDER_NOT_FOUND",
        ),
        finished_pages=[[]],
    )

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
        )
    )

    assert (
        result["outcome"]
        == "not_found"
    )
    assert (
        result["confidence"]
        == "inconclusive"
    )
    assert (
        result["status"]
        == "uncertain"
    )
    assert (
        result["lock_released"]
        is False
    )

    assert (
        get_trading_lock_for_request(
            "request-a"
        )
        is not None
    )


@pytest.mark.asyncio
async def test_gate_transport_error_keeps_lock():
    reserve_request(
        write_performed=True
    )

    client = FakeGateClient(
        single_error=GateAPIError(
            "network error",
            status_code=None,
            label="",
        )
    )

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
        )
    )

    assert (
        result["outcome"]
        == "lookup_error"
    )
    assert (
        result["confidence"]
        == "inconclusive"
    )
    assert (
        result["lock_released"]
        is False
    )


@pytest.mark.asyncio
async def test_duplicate_finished_correlation_requires_attention():
    row = reserve_request(
        write_performed=True
    )

    client = FakeGateClient(
        single_error=GateAPIError(
            "not pending",
            status_code=404,
            label="ORDER_NOT_FOUND",
        ),
        finished_pages=[
            [
                gate_order(
                    order_id="1",
                    text=row[
                        "gate_text"
                    ],
                    status="closed",
                ),
                gate_order(
                    order_id="2",
                    text=row[
                        "gate_text"
                    ],
                    status="closed",
                ),
            ]
        ],
    )

    result = await (
        reconcile_spot_order_request(
            client=client,
            request_id="request-a",
        )
    )

    assert (
        result["outcome"]
        == "duplicate_correlation"
    )
    assert (
        result["status"]
        == "attention"
    )
    assert (
        result["lock_released"]
        is False
    )
