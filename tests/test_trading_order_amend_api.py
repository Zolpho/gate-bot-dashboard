from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.api.trading as trading_api
import app.trading_order_amend as amend_module


@pytest.mark.asyncio
async def test_capabilities_expose_disarmed_amend_and_recovery(
    monkeypatch,
):
    settings = SimpleNamespace(
        trading_limit_orders_enabled=False,
        trading_limit_order_confirmation_text=(
            "LIVE ORDER"
        ),
        trading_order_cancels_enabled=True,
        trading_order_cancel_confirmation_text=(
            "CANCEL ORDER"
        ),
        trading_order_amends_enabled=False,
        trading_order_amend_confirmation_text=(
            "AMEND ORDER"
        ),
    )

    user = SimpleNamespace(
        account_ids=["zolnode"],
    )

    monkeypatch.setattr(
        trading_api,
        "get_trading_account",
        lambda account_id: SimpleNamespace(
            enabled=True,
            configured=True,
        ),
    )

    result = await (
        trading_api
        .trading_execution_capabilities(
            user=user,
            settings=settings,
        )
    )

    assert (
        result["amendment_implemented"]
        is True
    )
    assert (
        result["amendment_route_available"]
        is True
    )
    assert (
        result["amend_arm_enabled"]
        is False
    )
    assert (
        result[
            "amend_reconciliation_implemented"
        ]
        is True
    )
    assert (
        result[
            "amend_reconciliation_route_available"
        ]
        is True
    )
    assert (
        result[
            "amend_reconciliation_gate_get_only"
        ]
        is True
    )
    assert (
        result["gate_read_performed"]
        is False
    )
    assert (
        result["gate_write_performed"]
        is False
    )


@pytest.mark.asyncio
async def test_amend_api_wires_guarded_coordinator(
    monkeypatch,
):
    user = SimpleNamespace(
        username="alice",
        account_ids=["zolnode"],
    )
    settings = SimpleNamespace()

    monkeypatch.setattr(
        trading_api,
        "_trading_request_for_user",
        lambda user, request_id: {
            "request_id": request_id,
            "account_id": "zolnode",
        },
    )

    captured = {}

    async def fake_amend(**kwargs):
        captured.update(kwargs)
        return {
            "status": "blocked",
            "gate_write_performed": False,
        }

    monkeypatch.setattr(
        trading_api,
        "amend_limit_order_price",
        fake_amend,
    )

    request = (
        trading_api
        .LimitOrderAmendRequest(
            amend_request_id="amend-1",
            requested_price=Decimal(
                "0.123"
            ),
            confirmation="AMEND ORDER",
        )
    )

    result = await (
        trading_api.amend_trading_limit_order(
            request_id="order-1",
            request=request,
            user=user,
            settings=settings,
        )
    )

    assert result["status"] == "blocked"
    assert (
        captured["order_request_id"]
        == "order-1"
    )
    assert (
        captured["amend_request_id"]
        == "amend-1"
    )
    assert (
        captured["requested_price"]
        == Decimal("0.123")
    )
    assert (
        captured["allowed_account_ids"]
        == {"zolnode"}
    )


@pytest.mark.asyncio
async def test_manual_reconcile_api_is_explicit_and_read_only(
    monkeypatch,
):
    user = SimpleNamespace(
        username="alice",
        account_ids=["zolnode"],
    )
    settings = SimpleNamespace()

    monkeypatch.setattr(
        trading_api,
        "_trading_request_for_user",
        lambda user, request_id: {
            "request_id": request_id,
            "account_id": "zolnode",
        },
    )

    captured = {}

    async def fake_reconcile(**kwargs):
        captured.update(kwargs)

        return {
            "status": "uncertain",
            "gate_read_performed": True,
            "gate_write_performed": False,
            "write_performed": False,
        }

    monkeypatch.setattr(
        trading_api,
        "reconcile_limit_order_amendment",
        fake_reconcile,
    )

    result = await (
        trading_api
        .reconcile_trading_limit_order_amendment(
            request_id="order-1",
            amend_request_id="amend-1",
            user=user,
            settings=settings,
        )
    )

    assert (
        captured["order_request_id"]
        == "order-1"
    )
    assert (
        captured["amend_request_id"]
        == "amend-1"
    )
    assert (
        captured["allowed_account_ids"]
        == {"zolnode"}
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
        result["write_performed"]
        is False
    )


def test_manual_reconciliation_code_has_no_patch_primitive():
    public_source = inspect.getsource(
        amend_module
        .reconcile_limit_order_amendment
    )

    helper_source = inspect.getsource(
        amend_module
        ._reconcile_after_amend_write
    )

    assert (
        "amend_spot_order"
        not in public_source
    )
    assert (
        "amend_spot_order"
        not in helper_source
    )

    assert (
        "_reconcile_after_amend_write"
        in public_source
    )
    assert (
        "_read_gate_order"
        in helper_source
    )


@pytest.mark.asyncio
async def test_manual_reconciliation_works_with_arm_off_and_get_only(
    monkeypatch,
):
    source = {
        "request_id": "order-1",
        "account_id": "zolnode",
        "pair": "EQTY_USDT",
        "gate_order_id": "123456",
    }

    amendment = {
        "amend_request_id": "amend-1",
        "order_request_id": "order-1",
        "account_id": "zolnode",
        "pair": "EQTY_USDT",
        "gate_order_id": "123456",
        "current_price": "1",
        "requested_price": "2",
        "status": "uncertain",
        "write_performed": True,
        "completed_at": None,
    }

    monkeypatch.setattr(
        amend_module,
        "get_order_request",
        lambda request_id: source,
    )

    monkeypatch.setattr(
        amend_module,
        "get_order_amendment",
        lambda amend_request_id: amendment,
    )

    monkeypatch.setattr(
        amend_module,
        "get_trading_account",
        lambda account_id: SimpleNamespace(
            enabled=True,
            configured=True,
        ),
    )

    monkeypatch.setattr(
        amend_module,
        "_source_matches_gate",
        lambda **kwargs: [],
    )

    def fake_mark(
        amend_request_id,
        *,
        status,
        response=None,
        error="",
        gate_status_code=None,
        gate_label="",
        write_performed=None,
        completed=False,
    ):
        updated = dict(amendment)
        updated["status"] = status

        if write_performed is not None:
            updated["write_performed"] = (
                write_performed
            )

        updated["completed_at"] = (
            "completed"
            if completed
            else None
        )

        return updated

    monkeypatch.setattr(
        amend_module,
        "mark_order_amendment",
        fake_mark,
    )

    class FakeGateClient:
        last = None

        def __init__(self, *args, **kwargs):
            self.get_calls = 0
            self.patch_calls = 0
            type(self).last = self

        async def __aenter__(self):
            return self

        async def __aexit__(
            self,
            exc_type,
            exc,
            tb,
        ):
            return False

        async def get_spot_order(
            self,
            order_id,
            *,
            currency_pair=None,
            account="spot",
        ):
            self.get_calls += 1

            return SimpleNamespace(
                status_code=200,
                data={
                    "id": "123456",
                    "currency_pair": (
                        "EQTY_USDT"
                    ),
                    "price": "2",
                    "status": "open",
                },
            )

        async def amend_spot_order(
            self,
            *args,
            **kwargs,
        ):
            self.patch_calls += 1
            raise AssertionError(
                "manual reconciliation "
                "must never PATCH"
            )

    monkeypatch.setattr(
        amend_module,
        "GateClient",
        FakeGateClient,
    )

    # Critical 3J5 condition:
    # NEW amendments remain globally disabled.
    settings = SimpleNamespace(
        trading_order_amends_enabled=False,
    )

    result = await (
        amend_module
        .reconcile_limit_order_amendment(
            settings=settings,
            username="alice",
            allowed_account_ids={
                "zolnode",
            },
            order_request_id="order-1",
            amend_request_id="amend-1",
        )
    )

    client = FakeGateClient.last

    assert client is not None
    assert client.get_calls == 1
    assert client.patch_calls == 0

    assert (
        result["status"]
        == "confirmed_amended"
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
        result["write_performed"]
        is False
    )
    assert (
        result[
            "historical_amend_write_performed"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_manual_reconciliation_rejects_unwritten_amendment(
    monkeypatch,
):
    source = {
        "request_id": "order-1",
        "account_id": "zolnode",
        "pair": "EQTY_USDT",
        "gate_order_id": "123456",
    }

    amendment = {
        "amend_request_id": "amend-1",
        "order_request_id": "order-1",
        "account_id": "zolnode",
        "pair": "EQTY_USDT",
        "gate_order_id": "123456",
        "current_price": "1",
        "requested_price": "2",
        "status": "reserved",
        "write_performed": False,
        "completed_at": None,
    }

    monkeypatch.setattr(
        amend_module,
        "get_order_request",
        lambda request_id: source,
    )

    monkeypatch.setattr(
        amend_module,
        "get_order_amendment",
        lambda amend_request_id: amendment,
    )

    with pytest.raises(
        amend_module.TradingOrderAmendDenied
    ) as exc_info:
        await (
            amend_module
            .reconcile_limit_order_amendment(
                settings=SimpleNamespace(
                    trading_order_amends_enabled=False,
                ),
                username="alice",
                allowed_account_ids={
                    "zolnode",
                },
                order_request_id="order-1",
                amend_request_id="amend-1",
            )
        )

    assert (
        exc_info.value.code
        == "amendment_not_write_ambiguous"
    )
