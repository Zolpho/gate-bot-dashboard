from __future__ import annotations

from decimal import Decimal

from app.balances import build_account_balance_payload, price_in_usdt


def test_price_in_usdt_direct_inverse_and_bridge() -> None:
    prices = {
        "EQTY_USDT": Decimal("0.001"),
        "BTC_USDT": Decimal("60000"),
        "ABC_BTC": Decimal("0.0001"),
        "USDT_XYZ": Decimal("2"),
    }
    assert price_in_usdt("EQTY", prices) == (Decimal("0.001"), "EQTY_USDT")
    assert price_in_usdt("ABC", prices) == (Decimal("6.0000"), "ABC_BTC>BTC_USDT")
    assert price_in_usdt("XYZ", prices) == (Decimal("0.5"), "USDT_XYZ:inverse")
    assert price_in_usdt("UNKNOWN", prices) == (None, None)


def test_build_account_balance_payload() -> None:
    payload = build_account_balance_payload(
        account_id="zolnode",
        display_name="Zolnode",
        total_balance={
            "total": {"amount": "1525", "currency": "USDT"},
            "details": {
                "quant": {"amount": "1000", "currency": "USDT"},
                "spot": {"amount": "525", "currency": "USDT"},
            },
        },
        spot_accounts=[
            {"currency": "USDT", "available": "300", "locked": "25"},
            {"currency": "EQTY", "available": "100000", "locked": "50000"},
            {"currency": "ABC", "available": "2", "locked": "0"},
            {"currency": "NOQUOTE", "available": "3", "locked": "0"},
        ],
        spot_tickers=[
            {"currency_pair": "EQTY_USDT", "last": "0.001"},
            {"currency_pair": "BTC_USDT", "last": "60000"},
            {"currency_pair": "ABC_BTC", "last": "0.0001"},
        ],
        bot_summary={
            "invest_amount": 900,
            "current_value": 1000,
            "pnl": 100,
            "running_bots": 2,
            "tracked_bots": 2,
        },
    )

    assert payload["total_value"] == 1525.0
    assert payload["quant_value"] == 1000.0
    assert payload["spot_value"] == 525.0
    assert payload["summary"]["usdt"]["total"] == 325.0
    assert payload["summary"]["eqty"]["total"] == 150000.0
    assert payload["summary"]["eqty"]["value_usdt"] == 150.0
    assert payload["summary"]["other_value"] == 12.0
    assert payload["summary"]["other_count"] == 2
    assert payload["summary"]["unvalued_count"] == 1
    assert payload["bot_allocation"]["current_value"] == 1000.0
