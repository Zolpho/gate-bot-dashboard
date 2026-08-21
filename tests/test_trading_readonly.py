from fastapi import HTTPException

from app.api.trading import (
    _explicit_trading_account,
    _normalize_candlesticks,
    _normalize_order_book,
)
from app.security import DashboardUser


def test_trading_uses_explicit_account_scope():
    user = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )

    assert (
        _explicit_trading_account(
            user,
            "ARNOLD",
        )
        == "arnold"
    )


def test_super_admin_has_no_trading_wildcard():
    user = DashboardUser(
        username="admin",
        role="super_admin",
        account_ids=("zolnode",),
    )

    try:
        _explicit_trading_account(
            user,
            "arnold",
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError(
            "Super-admin trading wildcard was allowed"
        )


def test_normalize_gate_candlesticks():
    rows = [
        [
            "1700000060",
            "100.5",
            "1.20",
            "1.25",
            "1.10",
            "1.15",
            "82.4",
            "true",
        ],
        [
            "1700000000",
            "90",
            "1.15",
            "1.20",
            "1.05",
            "1.10",
            "80",
            "true",
        ],
    ]

    result = _normalize_candlesticks(rows)

    assert [
        item["time"]
        for item in result
    ] == [
        1700000000,
        1700000060,
    ]

    assert result[0]["open"] == "1.10"
    assert result[1]["close"] == "1.20"
    assert result[1]["base_volume"] == "82.4"
    assert result[1]["closed"] is True


def test_normalize_order_book_and_spread():
    result = _normalize_order_book(
        {
            "id": 123,
            "asks": [
                ["1.03", "4"],
                ["1.02", "3"],
            ],
            "bids": [
                ["0.99", "2"],
                ["1.00", "1"],
            ],
        }
    )

    assert (
        result["asks"][0]["price"]
        == "1.02"
    )

    assert (
        result["bids"][0]["price"]
        == "1.00"
    )

    assert result["best_ask"] == "1.02"
    assert result["best_bid"] == "1.00"
    assert result["spread"] == "0.02"


def test_book_interval_validation():
    from app.api.trading import _book_interval

    assert _book_interval("0") == "0"
    assert _book_interval("0.000001") == "0.000001"
    assert _book_interval("0.001000") == "0.001"


def test_order_book_depth_ratio():
    result = _normalize_order_book(
        {
            "asks": [
                ["1.01", "25"],
                ["1.02", "25"],
            ],
            "bids": [
                ["1.00", "50"],
                ["0.99", "50"],
            ],
        }
    )

    assert result["bid_amount_total"] == "100"
    assert result["ask_amount_total"] == "50"

    assert (
        result["buy_percent"]
        == "66.66666666666666666666666667"
    )

    assert (
        result["sell_percent"]
        == "33.33333333333333333333333333"
    )


def test_order_book_depth_ratio_uses_top_20_levels():
    asks = [
        ["2", "1"]
        for _ in range(20)
    ]

    bids = [
        ["1", "1"]
        for _ in range(20)
    ]

    # Huge 21st levels must not affect the displayed ratio.
    asks.append(["3", "100000"])
    bids.append(["0.5", "200000"])

    result = _normalize_order_book(
        {
            "asks": asks,
            "bids": bids,
        }
    )

    assert result["ask_amount_total"] == "20"
    assert result["bid_amount_total"] == "20"
    assert result["buy_percent"] == "50.0"
    assert result["sell_percent"] == "50.0"


def test_limit_order_buy_preflight_ready():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="buy",
        time_in_force="gtc",
        price=Decimal("2"),
        amount=Decimal("3"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=3,
        min_base_amount=Decimal("0.1"),
        min_quote_amount=Decimal("1"),
        base_available=Decimal("10"),
        quote_available=Decimal("10"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2.1"),
    )

    assert result["blockers"] == []
    assert result["total"] == Decimal("6")
    assert result["required"] == Decimal("6")
    assert result["available"] == Decimal("10")
    assert result["remaining"] == Decimal("4")
    assert result["marketable"] is False


def test_limit_order_buy_insufficient_quote():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="buy",
        time_in_force="gtc",
        price=Decimal("2"),
        amount=Decimal("6"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=3,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("100"),
        quote_available=Decimal("10"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2.1"),
    )

    assert any(
        "Insufficient" in item
        for item in result["blockers"]
    )


def test_limit_order_post_only_crossing_is_blocked():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="buy",
        time_in_force="poc",
        price=Decimal("2.1"),
        amount=Decimal("1"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=3,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("100"),
        quote_available=Decimal("100"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2"),
    )

    assert result["marketable"] is True

    assert any(
        "Post-only" in item
        for item in result["blockers"]
    )


def test_limit_order_precision_is_enforced():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="sell",
        time_in_force="gtc",
        price=Decimal("1.234"),
        amount=Decimal("1.111"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=2,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("100"),
        quote_available=Decimal("100"),
        best_bid=Decimal("1"),
        best_ask=Decimal("2"),
    )

    assert any(
        "Price exceeds" in item
        for item in result["blockers"]
    )

    assert any(
        "Amount exceeds" in item
        for item in result["blockers"]
    )


def test_limit_order_sell_uses_base_balance():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="sell",
        time_in_force="gtc",
        price=Decimal("2"),
        amount=Decimal("11"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=0,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("10"),
        quote_available=Decimal("999"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2.1"),
    )

    assert result["required_currency"] == "base"

    assert any(
        "Insufficient" in item
        for item in result["blockers"]
    )
