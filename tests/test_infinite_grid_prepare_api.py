from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import bot_control as bc
from app.gate_client import GateResponse
from app.security import DashboardUser


class ReadOnlyGateClient:
    calls: list[
        tuple[str, str | None]
    ] = []

    def __init__(
        self,
        *_args,
        **_kwargs,
    ) -> None:
        pass

    async def __aenter__(
        self,
    ):
        return self

    async def __aexit__(
        self,
        *_args,
    ) -> None:
        return None

    async def get_spot_currency_pair(
        self,
        market: str,
    ) -> GateResponse:
        self.calls.append(
            (
                "pair",
                market,
            )
        )

        return GateResponse(
            data={
                "id": market,
                "base": "EQTY",
                "quote": "USDT",
                "trade_status": "tradable",
                "precision": 6,
                "amount_precision": 2,
                "min_base_amount": "1",
                "min_quote_amount": "1",
            },
            status_code=200,
            headers={},
            raw={},
        )

    async def list_spot_tickers(
        self,
        market: str,
    ) -> GateResponse:
        self.calls.append(
            (
                "ticker",
                market,
            )
        )

        return GateResponse(
            data=[
                {
                    "currency_pair":
                        market,
                    "last":
                        "0.001700",
                    "highest_bid":
                        "0.001699",
                    "lowest_ask":
                        "0.001701",
                }
            ],
            status_code=200,
            headers={},
            raw={},
        )

    async def list_spot_accounts(
        self,
    ) -> GateResponse:
        self.calls.append(
            (
                "balances",
                None,
            )
        )

        return GateResponse(
            data=[
                {
                    "currency":
                        "USDT",
                    "available":
                        "750",
                    "locked":
                        "25",
                }
            ],
            status_code=200,
            headers={},
            raw={},
        )

    async def create_infinite_grid(
        self,
        _payload,
    ):
        raise AssertionError(
            "prepare route must never call "
            "create_infinite_grid"
        )


def user() -> DashboardUser:
    return DashboardUser(
        username="zolnode",
        role="account_operator",
        account_ids=(
            "zolnode",
        ),
    )


def monitor_account():
    return SimpleNamespace(
        id="zolnode",
        name="zolnode",
        enabled=True,
        configured=True,
    )


@pytest.fixture
def prepare_env(
    monkeypatch: pytest.MonkeyPatch,
):
    ReadOnlyGateClient.calls = []

    monkeypatch.setattr(
        bc,
        "GateClient",
        ReadOnlyGateClient,
    )

    monkeypatch.setattr(
        bc,
        "get_gate_account",
        lambda account_id: (
            monitor_account()
            if account_id
            == "zolnode"
            else None
        ),
    )

    monkeypatch.setattr(
        bc,
        "get_bot_control_account",
        lambda account_id: (
            object()
            if account_id
            == "zolnode"
            else None
        ),
    )


def request(
    **overrides,
) -> bc.InfiniteGridPrepareRequest:
    payload = {
        "account_id":
            "zolnode",
        "market":
            "eqty_usdt",
        "money":
            "500",
        "price_floor":
            "0.001500",
        "profit_per_grid":
            "0.01",
    }

    payload.update(
        overrides
    )

    return (
        bc.InfiniteGridPrepareRequest(
            **payload
        )
    )


def test_prepare_is_read_only_and_returns_exact_preview(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(),
            user(),
        )
    )

    assert (
        result["status"]
        == "ready"
    )

    assert (
        result["can_create"]
        is True
    )

    assert (
        result["write_performed"]
        is False
    )

    assert result[
        "credential_profiles"
    ] == {
        "prepare":
            "monitor",
        "create":
            "bot_control",
    }

    assert result[
        "account"
    ] == {
        "id":
            "zolnode",
        "name":
            "zolnode",
        "bot_control_available":
            True,
    }

    assert (
        result[
            "market"
        ][
            "id"
        ]
        == "EQTY_USDT"
    )

    assert (
        result[
            "market_snapshot"
        ][
            "last"
        ]
        == "0.0017"
    )

    assert (
        result[
            "balance"
        ][
            "available"
        ]
        == "750"
    )

    assert (
        result[
            "balance"
        ][
            "remaining_after_investment"
        ]
        == "250"
    )

    assert result[
        "grid"
    ][
        "has_fixed_upper_bound"
    ] is False

    assert result[
        "gate_create_payload_preview"
    ] == {
        "strategy_type":
            "infinite_grid",
        "market":
            "EQTY_USDT",
        "create_params": {
            "money":
                "500",
            "price_floor":
                "0.0015",
            "profit_per_grid":
                "0.01",
        },
    }

    assert (
        ReadOnlyGateClient.calls
        == [
            (
                "pair",
                "EQTY_USDT",
            ),
            (
                "ticker",
                "EQTY_USDT",
            ),
            (
                "balances",
                None,
            ),
        ]
    )


def test_prepare_optional_controls_flow_to_preview(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                grid_num=20,
                price_type=1,
                trigger_price=(
                    "0.001600"
                ),
                stop_profit=(
                    "0.003000"
                ),
                stop_loss=(
                    "0.001000"
                ),
            ),
            user(),
        )
    )

    params = result[
        "gate_create_payload_preview"
    ][
        "create_params"
    ]

    assert params[
        "grid_num"
    ] == 20

    assert params[
        "price_type"
    ] == 1

    assert params[
        "trigger_price"
    ] == "0.0016"

    assert params[
        "stop_profit"
    ] == "0.003"

    assert params[
        "stop_loss"
    ] == "0.001"


def test_prepare_rejects_insufficient_balance_without_write(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                money="1000"
            ),
            user(),
        )
    )

    assert (
        result["status"]
        == "invalid"
    )

    assert (
        result["can_create"]
        is False
    )

    assert (
        result["write_performed"]
        is False
    )

    assert any(
        "exceeds available"
        in item
        for item in result[
            "errors"
        ]
    )


def test_prepare_requires_bot_control_credentials(
    prepare_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bc,
        "get_bot_control_account",
        lambda _account_id: None,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        asyncio.run(
            bc.prepare_infinite_grid(
                request(),
                user(),
            )
        )

    assert (
        exc_info.value.status_code
        == 409
    )

    assert (
        "Bot Control credentials"
        in str(
            exc_info.value.detail
        )
    )

    assert (
        ReadOnlyGateClient.calls
        == []
    )


def test_prepare_preserves_account_authorization(
    prepare_env,
) -> None:
    unauthorized = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=(
            "arnold",
        ),
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        asyncio.run(
            bc.prepare_infinite_grid(
                request(),
                unauthorized,
            )
        )

    assert (
        exc_info.value.status_code
        == 403
    )

    assert (
        ReadOnlyGateClient.calls
        == []
    )



def _assert_read_only_prepare_contract(
    result: dict,
    *,
    ready: bool,
) -> None:
    assert (
        result["write_performed"]
        is False
    )

    assert (
        result["can_create"]
        is ready
    )

    assert (
        result["status"]
        == (
            "ready"
            if ready
            else "invalid"
        )
    )

    assert (
        ReadOnlyGateClient.calls
        == [
            (
                "pair",
                "EQTY_USDT",
            ),
            (
                "ticker",
                "EQTY_USDT",
            ),
            (
                "balances",
                None,
            ),
        ]
    )


def test_prepare_propagates_gate_minimum_profit_error(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                profit_per_grid="0.004",
            ),
            user(),
        )
    )

    _assert_read_only_prepare_contract(
        result,
        ready=False,
    )

    assert any(
        "greater than 0.4%"
        in item
        for item in result[
            "errors"
        ]
    )

    assert (
        result[
            "gate_create_payload_preview"
        ][
            "create_params"
        ][
            "profit_per_grid"
        ]
        == "0.004"
    )


def test_prepare_accepts_profit_just_above_gate_minimum(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                profit_per_grid="0.0041",
            ),
            user(),
        )
    )

    _assert_read_only_prepare_contract(
        result,
        ready=True,
    )

    assert not any(
        "Profit per grid"
        in item
        for item in result[
            "errors"
        ]
    )


def test_prepare_propagates_gate_maximum_profit_error(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                profit_per_grid="1",
            ),
            user(),
        )
    )

    _assert_read_only_prepare_contract(
        result,
        ready=False,
    )

    assert any(
        "less than 100%"
        in item
        for item in result[
            "errors"
        ]
    )

    assert (
        result[
            "gate_create_payload_preview"
        ][
            "create_params"
        ][
            "profit_per_grid"
        ]
        == "1"
    )


def test_prepare_accepts_profit_just_below_gate_maximum(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                profit_per_grid="0.999",
            ),
            user(),
        )
    )

    _assert_read_only_prepare_contract(
        result,
        ready=True,
    )

    assert not any(
        "Profit per grid"
        in item
        for item in result[
            "errors"
        ]
    )


def test_prepare_propagates_trigger_equal_market_error(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                trigger_price="0.001700",
            ),
            user(),
        )
    )

    _assert_read_only_prepare_contract(
        result,
        ready=False,
    )

    assert any(
        "Trigger price must be below"
        in item
        for item in result[
            "errors"
        ]
    )

    assert (
        result[
            "gate_create_payload_preview"
        ][
            "create_params"
        ][
            "trigger_price"
        ]
        == "0.0017"
    )


def test_prepare_accepts_trigger_below_market(
    prepare_env,
) -> None:
    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                trigger_price="0.001600",
            ),
            user(),
        )
    )

    _assert_read_only_prepare_contract(
        result,
        ready=True,
    )

    assert not any(
        "Trigger price"
        in item
        for item in result[
            "errors"
        ]
    )


def test_prepare_rejects_trigger_when_market_price_unavailable(
    prepare_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ticker_without_last(
        self,
        market: str,
    ) -> GateResponse:
        self.calls.append(
            (
                "ticker",
                market,
            )
        )

        return GateResponse(
            data=[
                {
                    "currency_pair":
                        market,
                    "last":
                        None,
                    "highest_bid":
                        "0.001699",
                    "lowest_ask":
                        "0.001701",
                }
            ],
            status_code=200,
            headers={},
            raw={},
        )

    monkeypatch.setattr(
        ReadOnlyGateClient,
        "list_spot_tickers",
        ticker_without_last,
    )

    result = asyncio.run(
        bc.prepare_infinite_grid(
            request(
                trigger_price="0.001600",
            ),
            user(),
        )
    )

    _assert_read_only_prepare_contract(
        result,
        ready=False,
    )

    assert any(
        "cannot be validated"
        in item
        for item in result[
            "errors"
        ]
    )

    assert (
        result[
            "market_snapshot"
        ][
            "last"
        ]
        is None
    )
