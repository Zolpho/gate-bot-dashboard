from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.api.bots as bots_api
from app.gate_native_activity_transport import (
    NativeActivityTransportError,
)


class FakeDB:
    def __init__(
        self,
        bot,
    ) -> None:
        self.bot = bot

    def scalar(
        self,
        statement,
    ):
        return self.bot


def make_bot(
    *,
    strategy_type: str = "infinite_grid",
    strategy_id: str = "5453981",
    market: str = "EQTY_USDT",
):
    return SimpleNamespace(
        id=42,
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        market=market,
    )


def live_trade_result(
    *,
    market: str = "EQTY_USDT",
):
    return {
        "source":
            "gate_native_order_record",

        "credential_mode":
            "none",

        "strategy_id":
            "5453981",

        "trades": {
            "strategy_id":
                "5453981",

            "items": [
                {
                    "strategy_id":
                        "5453981",

                    "order_id":
                        "1937538950",

                    "side":
                        "sell",

                    "price":
                        "0.001887",

                    "quantity":
                        "1970",

                    "match_amount":
                        "3.71739",

                    "fee":
                        "0.0036430422",

                    "profit":
                        "0.0318169578",

                    "profit_positive":
                        True,

                    "status":
                        "finished",

                    "order_index":
                        4,

                    "finish_time":
                        1791720158,

                    "market":
                        market,
                }
            ],

            "pagination": {
                "page": 1,
                "page_size": 30,
                "page_count": 2,
                "total_count": 36,
            },

            "summary": {
                "returned_count": 1,
                "gate_total_count": 36,
                "sell_count": 1,
                "buy_count": 0,
                "positive_profit_count": 1,
            },
        },
    }


class FakeTransport:
    calls = []

    async def __aenter__(
        self,
    ):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        return None

    async def fetch_trades(
        self,
        strategy_id,
        *,
        page,
        page_size,
        status,
    ):
        self.__class__.calls.append(
            {
                "strategy_id":
                    strategy_id,

                "page":
                    page,

                "page_size":
                    page_size,

                "status":
                    status,
            }
        )

        return live_trade_result()


@pytest.mark.asyncio
async def test_infinity_activity_returns_live_trades_and_session_bound_orders(
    monkeypatch,
) -> None:
    FakeTransport.calls = []

    monkeypatch.setattr(
        bots_api,
        "GateNativeActivityTransport",
        FakeTransport,
    )

    result = (
        await bots_api.get_bot_native_activity(
            42,
            page=1,
            page_size=30,
            db=FakeDB(
                make_bot()
            ),
        )
    )

    assert result[
        "bot_id"
    ] == 42

    assert result[
        "strategy_id"
    ] == "5453981"

    assert result[
        "strategy_type"
    ] == "infinite_grid"

    assert result[
        "market"
    ] == "EQTY_USDT"

    assert result[
        "trades"
    ][
        "available"
    ] is True

    assert result[
        "trades"
    ][
        "reason"
    ] is None

    assert result[
        "trades"
    ][
        "source"
    ] == "gate_native_order_record"

    assert result[
        "trades"
    ][
        "credential_mode"
    ] == "none"

    assert result[
        "trades"
    ][
        "data"
    ][
        "pagination"
    ][
        "total_count"
    ] == 36

    assert result[
        "open_orders"
    ] == {
        "available": False,
        "reason":
            "gate_web_session_required",
        "source":
            "gate_native_order_book",
        "requires_gate_web_session":
            True,
        "data": None,
    }

    assert FakeTransport.calls == [
        {
            "strategy_id":
                "5453981",
            "page":
                1,
            "page_size":
                30,
            "status":
                "finished",
        }
    ]


@pytest.mark.asyncio
async def test_spot_grid_stays_explicitly_unproven_and_makes_no_transport(
    monkeypatch,
) -> None:
    class MustNotRun:
        def __init__(
            self,
            *args,
            **kwargs,
        ):
            raise AssertionError(
                "Spot Grid transport must "
                "not run before live proof"
            )

    monkeypatch.setattr(
        bots_api,
        "GateNativeActivityTransport",
        MustNotRun,
    )

    result = (
        await bots_api.get_bot_native_activity(
            42,
            page=1,
            page_size=30,
            db=FakeDB(
                make_bot(
                    strategy_type="spot_grid",
                    strategy_id="5263197",
                )
            ),
        )
    )

    assert result[
        "trades"
    ][
        "available"
    ] is False

    assert result[
        "trades"
    ][
        "reason"
    ] == (
        "spot_grid_live_transport_unproven"
    )

    assert result[
        "open_orders"
    ][
        "available"
    ] is False

    assert result[
        "open_orders"
    ][
        "reason"
    ] == (
        "spot_grid_live_transport_unproven"
    )


@pytest.mark.asyncio
async def test_non_grid_activity_is_explicitly_unsupported(
    monkeypatch,
) -> None:
    class MustNotRun:
        def __init__(
            self,
            *args,
            **kwargs,
        ):
            raise AssertionError(
                "Unsupported strategy transport "
                "must not run"
            )

    monkeypatch.setattr(
        bots_api,
        "GateNativeActivityTransport",
        MustNotRun,
    )

    result = (
        await bots_api.get_bot_native_activity(
            42,
            page=1,
            page_size=30,
            db=FakeDB(
                make_bot(
                    strategy_type="futures_grid",
                )
            ),
        )
    )

    assert result[
        "trades"
    ][
        "reason"
    ] == "unsupported_strategy_type"

    assert result[
        "open_orders"
    ][
        "reason"
    ] == "unsupported_strategy_type"


@pytest.mark.asyncio
async def test_missing_strategy_id_does_not_call_transport(
    monkeypatch,
) -> None:
    class MustNotRun:
        def __init__(
            self,
            *args,
            **kwargs,
        ):
            raise AssertionError(
                "Missing strategy ID must not "
                "run transport"
            )

    monkeypatch.setattr(
        bots_api,
        "GateNativeActivityTransport",
        MustNotRun,
    )

    result = (
        await bots_api.get_bot_native_activity(
            42,
            page=1,
            page_size=30,
            db=FakeDB(
                make_bot(
                    strategy_id="",
                )
            ),
        )
    )

    assert result[
        "trades"
    ][
        "available"
    ] is False

    assert result[
        "trades"
    ][
        "reason"
    ] == "missing_strategy_id"

    assert result[
        "open_orders"
    ][
        "reason"
    ] == "gate_web_session_required"


@pytest.mark.asyncio
async def test_transport_failure_returns_degraded_safe_contract(
    monkeypatch,
) -> None:
    class FailedTransport:
        async def __aenter__(
            self,
        ):
            return self

        async def __aexit__(
            self,
            exc_type,
            exc,
            tb,
        ) -> None:
            return None

        async def fetch_trades(
            self,
            *args,
            **kwargs,
        ):
            raise NativeActivityTransportError(
                "secret-internal-diagnostic"
            )

    monkeypatch.setattr(
        bots_api,
        "GateNativeActivityTransport",
        FailedTransport,
    )

    result = (
        await bots_api.get_bot_native_activity(
            42,
            page=1,
            page_size=30,
            db=FakeDB(
                make_bot()
            ),
        )
    )

    assert result[
        "trades"
    ] == {
        "available": False,
        "reason":
            "gate_native_trades_unavailable",
        "source":
            "gate_native_order_record",
        "credential_mode":
            "none",
        "data":
            None,
    }

    assert (
        "secret-internal-diagnostic"
        not in repr(
            result
        )
    )


@pytest.mark.asyncio
async def test_market_mismatch_fails_closed(
    monkeypatch,
) -> None:
    class WrongMarketTransport:
        async def __aenter__(
            self,
        ):
            return self

        async def __aexit__(
            self,
            exc_type,
            exc,
            tb,
        ) -> None:
            return None

        async def fetch_trades(
            self,
            *args,
            **kwargs,
        ):
            return live_trade_result(
                market="BTC_USDT"
            )

    monkeypatch.setattr(
        bots_api,
        "GateNativeActivityTransport",
        WrongMarketTransport,
    )

    result = (
        await bots_api.get_bot_native_activity(
            42,
            page=1,
            page_size=30,
            db=FakeDB(
                make_bot()
            ),
        )
    )

    assert result[
        "trades"
    ] == {
        "available": False,
        "reason":
            "gate_native_contract_mismatch",
        "source":
            "gate_native_order_record",
        "credential_mode":
            "none",
        "data":
            None,
    }


@pytest.mark.asyncio
async def test_missing_bot_is_404() -> None:
    with pytest.raises(
        bots_api.HTTPException
    ) as exc_info:
        await bots_api.get_bot_native_activity(
            404,
            page=1,
            page_size=30,
            db=FakeDB(
                None
            ),
        )

    assert (
        exc_info.value.status_code
        == 404
    )


def test_native_activity_route_is_registered_get_only() -> None:
    matches = [
        route
        for route
        in bots_api.router.routes
        if getattr(
            route,
            "path",
            None,
        )
        == (
            "/api/bots/"
            "{bot_id}/native-activity"
        )
    ]

    assert len(
        matches
    ) == 1

    assert matches[
        0
    ].methods == {
        "GET"
    }
