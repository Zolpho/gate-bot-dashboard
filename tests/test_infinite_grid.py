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
    estimate_infinite_grid_requirements,
    format_infinite_grid_minimum_rejection,
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


def test_accepts_profit_per_grid_at_live_gate_minimum() -> None:
    errors = _validate_profit_per_grid(
        "0.002"
    )

    assert not any(
        "Profit per grid"
        in item
        for item in errors
    )


def test_rejects_profit_per_grid_below_live_gate_minimum() -> None:
    errors = _validate_profit_per_grid(
        "0.0019"
    )

    assert any(
        "at least 0.2%"
        in item
        for item in errors
    )


def test_accepts_profit_per_grid_above_live_gate_minimum() -> None:
    errors = _validate_profit_per_grid(
        "0.0021"
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

def test_eqty_estimator_reconstructs_live_four_level_ladder() -> None:
    result = estimate_infinite_grid_requirements(
        market="EQTY_USDT",
        current_price=Decimal(
            "0.001870"
        ),
        price_floor=Decimal(
            "0.0018"
        ),
        profit_per_grid=Decimal(
            "0.01"
        ),
    )

    assert (
        result[
            "estimated_levels_to_floor"
        ]
        == 4
    )

    assert (
        result[
            "estimated_gate_minimum"
        ]
        == "124.523726"
    )

    assert (
        result[
            "recommended_minimum"
        ]
        == "130"
    )


def test_minimum_estimator_stays_within_observed_gate_band() -> None:
    observations = [
        (
            "0.0018",
            "0.002",
            "1221.647567",
        ),
        (
            "0.0018",
            "0.005",
            "304.414219",
        ),
        (
            "0.0018",
            "0.01",
            "127.088567",
        ),
        (
            "0.0018",
            "0.02",
            "56.537508",
        ),
        (
            "0.0018",
            "0.03",
            "37.506895",
        ),
        (
            "0.0017",
            "0.01",
            "134.71598",
        ),
        (
            "0.0016",
            "0.01",
            "142.382026",
        ),
        (
            "0.0015",
            "0.01",
            "150.066401",
        ),
        (
            "0.0015",
            "0.02",
            "66.695383",
        ),
        (
            "0.0010",
            "0.01",
            "200.120982",
        ),
    ]

    for floor, roi, observed in observations:
        result = (
            estimate_infinite_grid_requirements(
                market="EQTY_USDT",
                current_price=Decimal(
                    "0.001870"
                ),
                price_floor=Decimal(
                    floor
                ),
                profit_per_grid=Decimal(
                    roi
                ),
            )
        )

        estimate = Decimal(
            result[
                "estimated_gate_minimum"
            ]
        )

        gate = Decimal(
            observed
        )

        relative_error = abs(
            estimate
            - gate
        ) / gate

        assert (
            relative_error
            <= Decimal(
                "0.03"
            )
        )

        assert (
            Decimal(
                result[
                    "recommended_minimum"
                ]
            )
            >= gate
        )


def test_minimum_estimator_is_not_applied_to_other_markets() -> None:
    result = estimate_infinite_grid_requirements(
        market="BTC_USDT",
        current_price=Decimal(
            "100"
        ),
        price_floor=Decimal(
            "90"
        ),
        profit_per_grid=Decimal(
            "0.01"
        ),
    )

    assert (
        result[
            "calibrated"
        ]
        is False
    )

    assert (
        result[
            "estimated_levels_to_floor"
        ]
        is not None
    )

    assert (
        result[
            "estimated_gate_minimum"
        ]
        is None
    )

    assert (
        result[
            "recommended_minimum"
        ]
        is None
    )


def test_formats_gate_minimum_rejection_without_internal_noise() -> None:
    message = (
        format_infinite_grid_minimum_rejection(
            response={
                "code":
                    400,
                "label":
                    "GRID_USER_INVEST_MONEY_NOT_ENOUGH",
                "message": (
                    "bot-service/gts.createInfinite"
                    "(grid_infinite.go:27): "
                    "invest money.20 "
                    "< min invest money.126.456285"
                ),
            },
            market="EQTY_USDT",
        )
    )

    assert message == (
        "Infinity Grid not created: "
        "20 USDT is below Gate's minimum of "
        "126.456285 USDT for these settings. "
        "Gate may recalculate this dynamic minimum "
        "when market conditions or strategy settings change."
    )

    assert (
        "grid_infinite.go"
        not in message
    )


def test_eqty_estimator_does_not_extrapolate_beyond_observed_roi_band() -> None:
    for roi in (
        "0.0019",
        "0.031",
        "0.05",
    ):
        result = (
            estimate_infinite_grid_requirements(
                market="EQTY_USDT",
                current_price=Decimal(
                    "0.001870"
                ),
                price_floor=Decimal(
                    "0.0018"
                ),
                profit_per_grid=Decimal(
                    roi
                ),
            )
        )

        assert (
            result[
                "calibrated"
            ]
            is False
        )

        assert (
            result[
                "estimated_levels_to_floor"
            ]
            is not None
        )

        assert (
            result[
                "estimated_gate_minimum"
            ]
            is None
        )

        assert (
            result[
                "recommended_minimum"
            ]
            is None
        )
