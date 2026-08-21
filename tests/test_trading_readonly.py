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
