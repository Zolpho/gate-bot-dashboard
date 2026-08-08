from decimal import Decimal

from app.spot_grid import (
    build_spot_grid_payload,
    validate_spot_grid,
)


def test_valid_spot_grid_plan() -> None:
    errors, warnings, math = validate_spot_grid(
        money=Decimal("500"),
        low_price=Decimal("0.00165"),
        high_price=Decimal("0.00200"),
        grid_num=10,
        price_type=0,
        price_precision=6,
        trade_status="tradable",
        min_quote_amount=Decimal("1"),
        available_quote=Decimal("1000"),
        current_price=Decimal("0.00180"),
    )

    assert errors == []
    assert math["price_type"] == "arithmetic"
    assert math["arithmetic_price_step"] == "0.000035"


def test_rejects_insufficient_balance() -> None:
    errors, _, _ = validate_spot_grid(
        money=Decimal("500"),
        low_price=Decimal("1"),
        high_price=Decimal("2"),
        grid_num=10,
        price_type=0,
        price_precision=4,
        trade_status="tradable",
        min_quote_amount=Decimal("1"),
        available_quote=Decimal("100"),
        current_price=Decimal("1.5"),
    )

    assert any(
        "exceeds available" in item
        for item in errors
    )


def test_rejects_bad_price_precision() -> None:
    errors, _, _ = validate_spot_grid(
        money=Decimal("100"),
        low_price=Decimal("1.12345"),
        high_price=Decimal("2"),
        grid_num=10,
        price_type=0,
        price_precision=4,
        trade_status="tradable",
        min_quote_amount=Decimal("1"),
        available_quote=Decimal("500"),
        current_price=Decimal("1.5"),
    )

    assert any(
        "low_price" in item
        for item in errors
    )


def test_build_gate_payload() -> None:
    payload = build_spot_grid_payload(
        market="eqty_usdt",
        money=Decimal("500"),
        low_price=Decimal("0.00165"),
        high_price=Decimal("0.002"),
        grid_num=10,
        price_type=0,
        trigger_price=Decimal("0.0018"),
    )

    assert payload == {
        "strategy_type": "spot_grid",
        "market": "EQTY_USDT",
        "create_params": {
            "money": "500",
            "low_price": "0.00165",
            "high_price": "0.002",
            "grid_num": 10,
            "price_type": 0,
            "is_use_base": False,
            "trigger_price": "0.0018",
        },
    }
