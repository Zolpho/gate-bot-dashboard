from __future__ import annotations

from decimal import Decimal

from app.bot_control_live_policy import (
    evaluate_live_account_policy,
    evaluate_live_create_policy,
    evaluate_live_stop_policy,
)
from app.config import Settings


def settings_for_test(
    *,
    armed: bool = True,
    accounts: str = "zolnode",
) -> Settings:
    return Settings(
        bot_control_live_armed=armed,
        bot_control_live_accounts=accounts,
    )


def test_live_execution_requires_arm():
    decision = evaluate_live_account_policy(
        settings=settings_for_test(
            armed=False
        ),
        account_id="zolnode",
        action="spot_grid_create",
    )

    assert decision.allowed is False
    assert (
        decision.reason
        == "live_not_armed"
    )


def test_account_must_be_allowed():
    decision = evaluate_live_account_policy(
        settings=settings_for_test(
            accounts="zolnode"
        ),
        account_id="arnold",
        action="spot_grid_create",
    )

    assert decision.allowed is False
    assert (
        decision.reason
        == "account_not_live_enabled"
    )


def test_wildcard_allows_any_account():
    decision = evaluate_live_account_policy(
        settings=settings_for_test(
            accounts="*"
        ),
        account_id="arnold",
        action="spot_grid_create",
    )

    assert decision.allowed is True


def test_create_maximum_is_available_quote_balance():
    decision = evaluate_live_create_policy(
        settings=settings_for_test(),
        account_id="zolnode",
        market="ETH_BTC",
        quote_currency="BTC",
        requested_investment=Decimal(
            "0.35"
        ),
        available_quote=Decimal(
            "0.50"
        ),
    )

    assert decision.allowed is True

    result = decision.safe_dict()

    assert (
        result["maximum_investment"]
        == "0.50"
    )

    assert (
        result["quote_currency"]
        == "BTC"
    )

    assert (
        result["market_restriction"]
        is False
    )

    assert (
        result["static_investment_cap"]
        is False
    )


def test_create_can_use_full_available_balance():
    decision = evaluate_live_create_policy(
        settings=settings_for_test(),
        account_id="zolnode",
        market="BTC_USDT",
        quote_currency="USDT",
        requested_investment=Decimal(
            "203.27475731"
        ),
        available_quote=Decimal(
            "203.27475731"
        ),
    )

    assert decision.allowed is True


def test_create_rejects_above_available_balance():
    decision = evaluate_live_create_policy(
        settings=settings_for_test(),
        account_id="zolnode",
        market="BTC_USDT",
        quote_currency="USDT",
        requested_investment=Decimal(
            "101"
        ),
        available_quote=Decimal(
            "100"
        ),
    )

    assert decision.allowed is False

    assert (
        decision.reason
        == "insufficient_available_quote_balance"
    )


def test_no_market_allowlist():
    markets = (
        ("EQTY_USDT", "USDT"),
        ("BTC_USDT", "USDT"),
        ("ETH_BTC", "BTC"),
        ("SOL_USDC", "USDC"),
    )

    for market, quote in markets:
        decision = evaluate_live_create_policy(
            settings=settings_for_test(),
            account_id="zolnode",
            market=market,
            quote_currency=quote,
            requested_investment=Decimal("1"),
            available_quote=Decimal("10"),
        )

        assert decision.allowed is True


def test_live_stop_uses_account_gate_not_market_gate():
    decision = evaluate_live_stop_policy(
        settings=settings_for_test(),
        account_id="zolnode",
        market="SOME_OTHER_PAIR",
        strategy_id="123456",
    )

    assert decision.allowed is True
