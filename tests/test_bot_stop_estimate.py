from decimal import Decimal

from app.bot_stop_estimate import (
    estimate_stop_return,
)


def test_direct_gate_base_and_quote():
    result = estimate_stop_return(
        market="EQTY_USDT",
        base_amount="46325.51",
        quote_amount="247.172",
        current_value="335.10",
        market_price="0.001898",
    )

    assert result["available"] is True
    assert result["base"] == {
        "currency": "EQTY",
        "amount": "46325.51",
    }
    assert result["quote"]["currency"] == "USDT"
    assert result["quote"]["amount"] == "247.172"
    assert result["quote"]["derived"] is False
    assert result["method"] == "gate_position"
    assert result["confidence"] == "high"


def test_quote_is_derived_from_current_value():
    result = estimate_stop_return(
        market="EQTY_USDT",
        base_amount="46325.51",
        quote_amount=None,
        current_value="334.4496239549",
        market_price="0.001898",
    )

    expected = (
        Decimal("334.4496239549")
        - (
            Decimal("46325.51")
            * Decimal("0.001898")
        )
    )

    assert result["available"] is True
    assert result["quote"]["derived"] is True

    assert (
        Decimal(
            result["quote"]["amount"]
        )
        == expected
    )

    assert (
        result["method"]
        == "gate_position_plus_current_value"
    )

    assert result["confidence"] == "medium"


def test_generic_non_usdt_pair():
    result = estimate_stop_return(
        market="ETH_BTC",
        base_amount="0.25",
        quote_amount="0.004",
        current_value=None,
        market_price="0.035",
    )

    assert (
        result["base"]["currency"]
        == "ETH"
    )
    assert (
        result["quote"]["currency"]
        == "BTC"
    )

    assert (
        result[
            "estimated_total_quote_value"
        ]
        == "0.01275"
    )


def test_unavailable_without_position_data():
    result = estimate_stop_return(
        market="SOL_USDC",
        base_amount=None,
        quote_amount=None,
        current_value="100",
        market_price="150",
    )

    assert result["available"] is False
    assert result["confidence"] == "unavailable"
    assert result["method"] == "unavailable"
