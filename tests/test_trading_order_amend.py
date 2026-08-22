from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

import app.trading_order_amend as amend
from app.accounts import (
    GateAccountConfig,
)
from app.config import Settings
from app.db import (
    init_db,
    session_scope,
)
from app.gate_client import (
    GateAPIError,
    GateResponse,
)
from app.models import (
    TradingOrderAmendment,
    TradingOrderCancellation,
    TradingOrderRequest,
)
from app.trading_order_amend import (
    TradingOrderAmendDenied,
    amend_limit_order_price,
)
from app.trading_order_amend_audit import (
    get_active_order_amendment,
    get_order_amendment,
    reserve_order_amendment,
)
from app.trading_order_audit import (
    mark_order_request,
    reserve_limit_order,
)
from app.trading_order_cancel_audit import (
    reserve_order_cancellation,
)


init_db()


TRADING_ACCOUNT = GateAccountConfig(
    id="arnold",
    name="arnold",
    api_key="trading-key",
    api_secret="trading-secret",
    enabled=True,
    account_type="subaccount",
    gate_uid="58601346",
)


def make_settings(
    **overrides,
):
    values = {
        "trading_order_amends_enabled":
            True,
        "trading_order_amend_confirmation_text":
            "AMEND ORDER",
        "trading_order_amend_exptime_ms":
            5000,
    }

    values.update(
        overrides
    )

    return Settings(
        _env_file=None,
        **values,
    )


class FakeGateClient:
    mode = "success"

    get_calls = 0
    pair_calls = 0
    book_calls = 0
    patch_calls = []

    gate_text = ""

    def __init__(
        self,
        settings,
        account,
    ):
        self.settings = settings
        self.account = account

    async def __aenter__(
        self,
    ):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False

    @classmethod
    def reset(
        cls,
    ):
        cls.mode = "success"
        cls.get_calls = 0
        cls.pair_calls = 0
        cls.book_calls = 0
        cls.patch_calls = []
        cls.gate_text = ""

    @classmethod
    def order(
        cls,
        *,
        price="0.0015",
        status="open",
        finish_as="open",
        order_id="123456789",
    ):
        return {
            "id": order_id,
            "currency_pair":
                "EQTY_USDT",
            "account": "spot",
            "type": "limit",
            "side": "buy",
            "price": price,
            "amount": "1000",
            "filled_amount": "0",
            "left": "1000",
            "status": status,
            "finish_as": finish_as,
            "time_in_force": "poc",
            "text": cls.gate_text,
        }

    async def get_spot_order(
        self,
        order_id,
        *,
        currency_pair=None,
        account="spot",
    ):
        type(self).get_calls += 1

        if (
            type(self).mode
            == "lookup_error"
            and not type(self)
            .patch_calls
        ):
            raise GateAPIError(
                "lookup failed",
                status_code=503,
                label="",
                response=None,
            )

        if (
            type(self).mode
            == "identity_mismatch"
            and not type(self)
            .patch_calls
        ):
            data = type(self).order(
                order_id="987654321",
            )

        elif (
            type(self).mode
            == "ambiguous_applied"
            and type(self)
            .patch_calls
        ):
            data = type(self).order(
                price="0.0016",
            )

        elif (
            type(self).mode
            == "ambiguous_terminal_old"
            and type(self)
            .patch_calls
        ):
            data = type(self).order(
                price="0.0015",
                status="closed",
                finish_as="filled",
            )

        else:
            data = type(self).order(
                price="0.0015",
            )

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )

    async def get_spot_currency_pair(
        self,
        currency_pair,
    ):
        type(self).pair_calls += 1

        precision = (
            4
            if type(self).mode
            == "precision_reject"
            else 6
        )

        data = {
            "id": "EQTY_USDT",
            "precision": precision,
            "amount_precision": 2,
            "trade_status":
                "tradable",
        }

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )

    async def get_spot_order_book(
        self,
        currency_pair,
        *,
        interval="0",
        limit=20,
        with_id=True,
    ):
        type(self).book_calls += 1

        data = {
            "bids": [
                [
                    "0.0014",
                    "1000",
                ],
            ],
            "asks": [
                [
                    "0.0018",
                    "1000",
                ],
            ],
        }

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )

    async def amend_spot_order(
        self,
        order_id,
        *,
        currency_pair,
        price,
        expires_at_ms,
        account="spot",
    ):
        type(self).patch_calls.append({
            "order_id": order_id,
            "currency_pair":
                currency_pair,
            "price": price,
            "expires_at_ms":
                expires_at_ms,
            "account": account,
        })

        if (
            type(self).mode
            == "definitive_reject"
        ):
            raise GateAPIError(
                "invalid price",
                status_code=400,
                label="INVALID_PARAM_VALUE",
                response={
                    "label":
                        "INVALID_PARAM_VALUE",
                },
            )

        if type(self).mode in {
            "ambiguous_applied",
            "ambiguous_open_old",
            "ambiguous_terminal_old",
        }:
            raise GateAPIError(
                "network ambiguity",
                status_code=None,
                label="",
                response=None,
            )

        data = type(self).order(
            price=price,
        )

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )


@pytest.fixture(autouse=True)
def clean_state(
    monkeypatch,
):
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TradingOrderAmendment
                )
            )
            db.execute(
                delete(
                    TradingOrderCancellation
                )
            )
            db.execute(
                delete(
                    TradingOrderRequest
                )
            )

    clear()
    FakeGateClient.reset()

    monkeypatch.setattr(
        amend,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        amend,
        "get_trading_account",
        lambda account_id:
            TRADING_ACCOUNT
            if account_id == "arnold"
            else None,
    )

    yield

    clear()
    FakeGateClient.reset()


def create_source_order():
    (
        request,
        created,
    ) = reserve_limit_order(
        request_id="request-a",
        account_id="arnold",
        username="alice",
        pair="EQTY_USDT",
        side="buy",
        price=Decimal(
            "0.0015"
        ),
        amount=Decimal(
            "1000"
        ),
        time_in_force="poc",
        funding_asset="USDT",
    )

    assert created is True

    FakeGateClient.gate_text = str(
        request.get(
            "gate_text"
        )
        or ""
    )

    mark_order_request(
        "request-a",
        status="submitted",
        response={},
        gate_order_id="123456789",
        gate_status_code=201,
        write_performed=True,
        completed=True,
    )

    return request


async def do_amend(
    *,
    settings=None,
    amend_request_id="amend-a",
    requested_price=Decimal(
        "0.0016"
    ),
    confirmation="AMEND ORDER",
):
    return await amend_limit_order_price(
        settings=(
            settings
            or make_settings()
        ),
        username="alice",
        allowed_account_ids={
            "arnold",
        },
        amend_request_id=(
            amend_request_id
        ),
        order_request_id="request-a",
        requested_price=(
            requested_price
        ),
        confirmation=confirmation,
    )


@pytest.mark.asyncio
async def test_successful_amend_is_exactly_one_patch():
    create_source_order()

    result = await do_amend()

    assert result["status"] == "amended"
    assert result["definitive"] is True

    assert (
        result["gate_write_performed"]
        is True
    )

    assert FakeGateClient.get_calls == 1
    assert FakeGateClient.pair_calls == 1
    assert FakeGateClient.book_calls == 1

    assert len(
        FakeGateClient.patch_calls
    ) == 1

    assert (
        FakeGateClient
        .patch_calls[0]["price"]
        == "0.0016"
    )

    stored = get_order_amendment(
        "amend-a"
    )

    assert stored is not None
    assert stored["status"] == "amended"
    assert stored["active"] is False
    assert stored["write_performed"] is True


@pytest.mark.asyncio
async def test_amend_arm_disabled_blocks_before_gate():
    create_source_order()

    with pytest.raises(
        TradingOrderAmendDenied,
    ) as caught:
        await do_amend(
            settings=make_settings(
                trading_order_amends_enabled=False,
            )
        )

    assert (
        caught.value.code
        == "amendment_disabled"
    )

    assert FakeGateClient.get_calls == 0
    assert FakeGateClient.patch_calls == []


@pytest.mark.asyncio
async def test_confirmation_mismatch_blocks_before_gate():
    create_source_order()

    with pytest.raises(
        TradingOrderAmendDenied,
    ) as caught:
        await do_amend(
            confirmation="WRONG"
        )

    assert (
        caught.value.code
        == "confirmation_mismatch"
    )

    assert FakeGateClient.get_calls == 0
    assert FakeGateClient.patch_calls == []


@pytest.mark.asyncio
async def test_existing_amend_request_is_replay_safe():
    create_source_order()

    first = await do_amend()

    assert first["status"] == "amended"

    counts = (
        FakeGateClient.get_calls,
        FakeGateClient.pair_calls,
        FakeGateClient.book_calls,
        len(
            FakeGateClient.patch_calls
        ),
    )

    second = await do_amend()

    assert (
        second["status"]
        == "idempotent_replay"
    )

    assert second["definitive"] is True

    assert (
        second["gate_write_performed"]
        is False
    )

    assert (
        (
            FakeGateClient.get_calls,
            FakeGateClient.pair_calls,
            FakeGateClient.book_calls,
            len(
                FakeGateClient.patch_calls
            ),
        )
        == counts
    )


@pytest.mark.asyncio
async def test_unresolved_amend_blocks_second_intent():
    create_source_order()

    reserve_order_amendment(
        amend_request_id="amend-a",
        order_request_id="request-a",
        account_id="arnold",
        username="alice",
        pair="EQTY_USDT",
        gate_order_id="123456789",
        current_price=Decimal(
            "0.0015"
        ),
        requested_price=Decimal(
            "0.0016"
        ),
    )

    with pytest.raises(
        TradingOrderAmendDenied,
    ) as caught:
        await do_amend(
            amend_request_id="amend-b",
            requested_price=Decimal(
                "0.0017"
            ),
        )

    assert (
        caught.value.code
        == "amendment_in_progress"
    )

    assert FakeGateClient.get_calls == 0
    assert FakeGateClient.patch_calls == []


@pytest.mark.asyncio
async def test_existing_cancellation_blocks_amend():
    create_source_order()

    reserve_order_cancellation(
        cancel_request_id="cancel-a",
        order_request_id="request-a",
        account_id="arnold",
        username="alice",
        pair="EQTY_USDT",
        gate_order_id="123456789",
    )

    with pytest.raises(
        TradingOrderAmendDenied,
    ) as caught:
        await do_amend()

    assert (
        caught.value.code
        == "cancellation_recorded"
    )

    assert FakeGateClient.get_calls == 0
    assert FakeGateClient.patch_calls == []


@pytest.mark.asyncio
async def test_identity_mismatch_blocks_before_patch():
    create_source_order()

    FakeGateClient.mode = (
        "identity_mismatch"
    )

    result = await do_amend()

    assert (
        result["status"]
        == "precheck_error"
    )

    assert (
        result["gate_write_performed"]
        is False
    )

    assert FakeGateClient.get_calls == 1
    assert FakeGateClient.patch_calls == []


@pytest.mark.asyncio
async def test_price_precision_blocks_before_patch():
    create_source_order()

    FakeGateClient.mode = (
        "precision_reject"
    )

    result = await do_amend(
        requested_price=Decimal(
            "0.00161"
        )
    )

    assert (
        result["status"]
        == "precheck_error"
    )

    assert (
        "precision"
        in result["error"].lower()
    )

    assert FakeGateClient.patch_calls == []

    assert (
        get_order_amendment(
            "amend-a"
        )
        is None
    )


@pytest.mark.asyncio
async def test_poc_crossing_blocks_before_patch():
    create_source_order()

    result = await do_amend(
        requested_price=Decimal(
            "0.0019"
        )
    )

    assert (
        result["status"]
        == "precheck_error"
    )

    assert (
        "POC buy amendment"
        in result["error"]
    )

    assert FakeGateClient.book_calls == 1
    assert FakeGateClient.patch_calls == []


@pytest.mark.asyncio
async def test_definitive_gate_rejection_is_terminal():
    create_source_order()

    FakeGateClient.mode = (
        "definitive_reject"
    )

    result = await do_amend()

    assert result["status"] == "rejected"
    assert result["definitive"] is True

    assert (
        result["gate_write_performed"]
        is True
    )

    assert len(
        FakeGateClient.patch_calls
    ) == 1

    stored = get_order_amendment(
        "amend-a"
    )

    assert stored is not None
    assert stored["active"] is False


@pytest.mark.asyncio
async def test_ambiguous_patch_reconciles_requested_price():
    create_source_order()

    FakeGateClient.mode = (
        "ambiguous_applied"
    )

    result = await do_amend()

    assert (
        result["status"]
        == "confirmed_amended"
    )

    assert result["definitive"] is True

    assert FakeGateClient.get_calls == 2

    assert len(
        FakeGateClient.patch_calls
    ) == 1

    assert (
        get_active_order_amendment(
            "request-a"
        )
        is None
    )


@pytest.mark.asyncio
async def test_ambiguous_open_old_price_stays_locked():
    create_source_order()

    FakeGateClient.mode = (
        "ambiguous_open_old"
    )

    result = await do_amend()

    assert result["status"] == "uncertain"
    assert result["definitive"] is False

    assert (
        result["manual_review_required"]
        is True
    )

    assert FakeGateClient.get_calls == 2

    assert len(
        FakeGateClient.patch_calls
    ) == 1

    active = (
        get_active_order_amendment(
            "request-a"
        )
    )

    assert active is not None
    assert active["status"] == "uncertain"


@pytest.mark.asyncio
async def test_ambiguous_terminal_old_price_is_not_applied():
    create_source_order()

    FakeGateClient.mode = (
        "ambiguous_terminal_old"
    )

    result = await do_amend()

    assert (
        result["status"]
        == "confirmed_not_applied"
    )

    assert result["definitive"] is True

    assert FakeGateClient.get_calls == 2

    assert len(
        FakeGateClient.patch_calls
    ) == 1

    assert (
        get_active_order_amendment(
            "request-a"
        )
        is None
    )
