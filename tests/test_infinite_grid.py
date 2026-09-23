from __future__ import annotations

import asyncio
from decimal import Decimal

from app.config import Settings
from app.gate_client import (
    GateClient,
    GateResponse,
)
from app.infinite_grid import (
    build_infinite_grid_payload,
    validate_infinite_grid,
)


def test_build_minimal_infinite_grid_payload() -> None:
    payload = build_infinite_grid_payload(
        market="eqty_usdt",
        money=Decimal("500"),
        price_floor=Decimal(
            "0.0015"
        ),
        profit_per_grid=Decimal(
            "0.01"
        ),
    )

    assert payload == {
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


def test_optional_fields_are_only_sent_when_explicit() -> None:
    payload = build_infinite_grid_payload(
        market="EQTY_USDT",
        money=Decimal("500"),
        price_floor=Decimal(
            "0.0015"
        ),
        profit_per_grid=Decimal(
            "0.01"
        ),
        grid_num=20,
        price_type=1,
        trigger_price=Decimal(
            "0.0016"
        ),
        stop_profit=Decimal(
            "0.003"
        ),
        stop_loss=Decimal(
            "0.001"
        ),
        profit_sharing_ratio=Decimal(
            "0.1"
        ),
        is_use_base=False,
    )

    assert payload[
        "create_params"
    ] == {
        "money":
            "500",
        "price_floor":
            "0.0015",
        "profit_per_grid":
            "0.01",
        "grid_num":
            20,
        "price_type":
            1,
        "trigger_price":
            "0.0016",
        "stop_profit":
            "0.003",
        "stop_loss":
            "0.001",
        "profit_sharing_ratio":
            "0.1",
        "is_use_base":
            False,
    }


def test_valid_infinite_grid_plan() -> None:
    errors, warnings, math = (
        validate_infinite_grid(
            money=Decimal(
                "500"
            ),
            price_floor=Decimal(
                "0.0015"
            ),
            profit_per_grid=Decimal(
                "0.01"
            ),
            price_precision=6,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "1000"
            ),
            current_price=Decimal(
                "0.0017"
            ),
        )
    )

    assert errors == []
    assert warnings == []

    assert (
        math[
            "strategy_type"
        ]
        == "infinite_grid"
    )

    assert (
        math[
            "has_fixed_upper_bound"
        ]
        is False
    )

    assert math[
        "price_type"
    ] is None


def test_rejects_non_positive_required_values() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal("0"),
            price_floor=Decimal(
                "0"
            ),
            profit_per_grid=Decimal(
                "0"
            ),
            price_precision=6,
            trade_status="tradable",
            min_quote_amount=None,
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "1"
            ),
        )
    )

    assert len(errors) == 3


def test_rejects_insufficient_balance() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal(
                "101"
            ),
            price_floor=Decimal(
                "1"
            ),
            profit_per_grid=Decimal(
                "0.01"
            ),
            price_precision=4,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
        )
    )

    assert any(
        "exceeds available"
        in item
        for item in errors
    )


def test_rejects_invalid_optional_grid_controls() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal(
                "10"
            ),
            price_floor=Decimal(
                "1"
            ),
            profit_per_grid=Decimal(
                "0.01"
            ),
            grid_num=0,
            price_type=7,
            price_precision=4,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
        )
    )

    assert any(
        "Grid count"
        in item
        for item in errors
    )

    assert any(
        "price_type"
        in item
        for item in errors
    )


def test_rejects_price_floor_precision_over_market_limit() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal(
                "10"
            ),
            price_floor=Decimal(
                "1.12345"
            ),
            profit_per_grid=Decimal(
                "0.01"
            ),
            price_precision=4,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
        )
    )

    assert any(
        "price_floor"
        in item
        for item in errors
    )


def test_floor_at_or_above_market_is_warning_not_invented_gate_rule() -> None:
    errors, warnings, _ = (
        validate_infinite_grid(
            money=Decimal(
                "10"
            ),
            price_floor=Decimal(
                "2"
            ),
            profit_per_grid=Decimal(
                "0.01"
            ),
            price_precision=4,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
        )
    )

    assert errors == []

    assert len(
        warnings
    ) == 1

    assert (
        "Gate remains authoritative"
        in warnings[0]
    )


def test_gate_client_uses_exact_infinite_grid_endpoint() -> None:
    payload = (
        build_infinite_grid_payload(
            market="EQTY_USDT",
            money=Decimal(
                "25"
            ),
            price_floor=Decimal(
                "0.0015"
            ),
            profit_per_grid=Decimal(
                "0.01"
            ),
        )
    )

    calls: list[
        tuple[
            str,
            str,
            object,
        ]
    ] = []

    async def scenario() -> None:
        settings = Settings(
            gate_api_key="test-key",
            gate_api_secret=(
                "test-secret"
            ),
        )

        async with GateClient(
            settings
        ) as client:
            async def fake_request(
                method: str,
                endpoint: str,
                **kwargs,
            ) -> GateResponse:
                calls.append(
                    (
                        method,
                        endpoint,
                        kwargs.get(
                            "json_body"
                        ),
                    )
                )

                return GateResponse(
                    data={
                        "strategy_id":
                            "test-only",
                    },
                    status_code=200,
                    headers={},
                    raw={},
                )

            client.request = (
                fake_request
            )

            response = (
                await client
                .create_infinite_grid(
                    payload
                )
            )

            assert (
                response.status_code
                == 200
            )

    asyncio.run(
        scenario()
    )

    assert calls == [
        (
            "POST",
            "/bot/infinite-grid/create",
            payload,
        )
    ]


def _validate_profit_per_grid(
    value: str,
) -> list[str]:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal("10"),
            price_floor=Decimal("1"),
            profit_per_grid=Decimal(
                value
            ),
            grid_num=10,
            price_type=1,
            price_precision=6,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
        )
    )

    return errors


def test_rejects_profit_per_grid_at_gate_minimum() -> None:
    errors = _validate_profit_per_grid(
        "0.004"
    )

    assert any(
        "greater than 0.4%"
        in item
        for item in errors
    )


def test_rejects_profit_per_grid_below_gate_minimum() -> None:
    errors = _validate_profit_per_grid(
        "0.0039"
    )

    assert any(
        "greater than 0.4%"
        in item
        for item in errors
    )


def test_accepts_profit_per_grid_above_gate_minimum() -> None:
    errors = _validate_profit_per_grid(
        "0.0041"
    )

    assert not any(
        "Profit per grid"
        in item
        for item in errors
    )


def test_rejects_profit_per_grid_at_gate_maximum() -> None:
    errors = _validate_profit_per_grid(
        "1"
    )

    assert any(
        "less than 100%"
        in item
        for item in errors
    )


def test_rejects_profit_per_grid_above_gate_maximum() -> None:
    errors = _validate_profit_per_grid(
        "1.01"
    )

    assert any(
        "less than 100%"
        in item
        for item in errors
    )


def test_accepts_profit_per_grid_below_gate_maximum() -> None:
    errors = _validate_profit_per_grid(
        "0.999"
    )

    assert not any(
        "Profit per grid"
        in item
        for item in errors
    )


def test_rejects_trigger_price_equal_to_market() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal("10"),
            price_floor=Decimal("1"),
            profit_per_grid=Decimal(
                "0.01"
            ),
            grid_num=10,
            price_type=1,
            price_precision=6,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
            trigger_price=Decimal(
                "2"
            ),
        )
    )

    assert any(
        "Trigger price must be below"
        in item
        for item in errors
    )


def test_rejects_trigger_price_above_market() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal("10"),
            price_floor=Decimal("1"),
            profit_per_grid=Decimal(
                "0.01"
            ),
            grid_num=10,
            price_type=1,
            price_precision=6,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
            trigger_price=Decimal(
                "2.1"
            ),
        )
    )

    assert any(
        "Trigger price must be below"
        in item
        for item in errors
    )


def test_accepts_trigger_price_below_market() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal("10"),
            price_floor=Decimal("1"),
            profit_per_grid=Decimal(
                "0.01"
            ),
            grid_num=10,
            price_type=1,
            price_precision=6,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=Decimal(
                "2"
            ),
            trigger_price=Decimal(
                "1.9"
            ),
        )
    )

    assert not any(
        "Trigger price"
        in item
        for item in errors
    )


def test_trigger_price_requires_current_market_price() -> None:
    errors, _, _ = (
        validate_infinite_grid(
            money=Decimal("10"),
            price_floor=Decimal("1"),
            profit_per_grid=Decimal(
                "0.01"
            ),
            grid_num=10,
            price_type=1,
            price_precision=6,
            trade_status="tradable",
            min_quote_amount=Decimal(
                "1"
            ),
            available_quote=Decimal(
                "100"
            ),
            current_price=None,
            trigger_price=Decimal(
                "1.9"
            ),
        )
    )

    assert any(
        "cannot be validated"
        in item
        for item in errors
    )
