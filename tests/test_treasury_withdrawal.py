from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.deposits import (
    normalize_currency_chains,
)
from app.security import DashboardUser
from app.treasury_withdrawal import (
    build_withdrawal_capabilities,
    normalize_withdraw_status,
)


CHAINS = [
    {
        "chain": "TRX",
        "name_en": "TRON",
        "is_disabled": 0,
        "is_deposit_disabled": 0,
        "is_withdraw_disabled": 0,
        "decimal": "6",
    },
    {
        "chain": "ETH",
        "name_en": "Ethereum",
        "is_disabled": 0,
        "is_deposit_disabled": 0,
        "is_withdraw_disabled": 1,
        "decimal": "6",
    },
]


STATUS = [
    {
        "currency": "USDT",
        "withdraw_percent": "0%",
        "withdraw_fix": "9",
        "withdraw_day_limit": "100000",
        "withdraw_day_limit_remain": "50000",
        "withdraw_amount_mini": "1",
        "withdraw_eachtime_limit": "20000",
        "withdraw_fix_on_chains": {
            "TRX": "1",
        },
        "withdraw_percent_on_chains": {
            "TRX": "0%",
        },
    }
]


def test_chain_normalization_includes_withdrawal_state():
    rows = normalize_currency_chains(
        CHAINS
    )

    trx = next(
        item
        for item in rows
        if item["chain"] == "TRX"
    )

    eth = next(
        item
        for item in rows
        if item["chain"] == "ETH"
    )

    assert trx["withdraw_enabled"] is True
    assert trx["withdraw_disabled"] is False

    assert eth["withdraw_enabled"] is False
    assert eth["withdraw_disabled"] is True


def test_withdraw_status_normalization():
    result = normalize_withdraw_status(
        STATUS,
        currency="USDT",
    )

    assert result["available"] is True
    assert result["minimum"] == "1"
    assert (
        result["maximum_per_withdrawal"]
        == "20000"
    )
    assert (
        result["daily_limit_remaining"]
        == "50000"
    )


def test_subaccount_economic_availability():
    result = build_withdrawal_capabilities(
        owner_account_id="arnold",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[
            {
                "currency": "USDT",
                "available": "10",
                "locked": "2",
            }
        ],
        raw_chains=CHAINS,
        raw_withdraw_status=STATUS,
        owner_main_held=Decimal("3"),
        custody_liabilities=Decimal("3"),
    )

    availability = result["availability"]

    assert (
        availability["source_spot_available"]
        == "10"
    )
    assert availability["owner_main_held"] == "3"
    assert (
        availability["economic_available"]
        == "13"
    )

    trx = next(
        item
        for item in result["chains"]
        if item["chain"] == "TRX"
    )

    assert trx["capability_ready"] is True
    assert trx["fixed_fee"] == "1"
    assert trx["fixed_fee_source"] == "chain"


def test_disabled_chain_is_not_ready():
    result = build_withdrawal_capabilities(
        owner_account_id="arnold",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[],
        raw_chains=CHAINS,
        raw_withdraw_status=STATUS,
        owner_main_held=Decimal("0"),
        custody_liabilities=Decimal("0"),
    )

    eth = next(
        item
        for item in result["chains"]
        if item["chain"] == "ETH"
    )

    assert eth["withdraw_enabled"] is False
    assert eth["capability_ready"] is False
    assert eth["fixed_fee"] == "9"
    assert eth["fixed_fee_source"] == "currency"


def test_main_account_subtracts_third_party_liabilities():
    result = build_withdrawal_capabilities(
        owner_account_id="zolnode",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[
            {
                "currency": "USDT",
                "available": "100",
                "locked": "0",
            }
        ],
        raw_chains=CHAINS,
        raw_withdraw_status=STATUS,
        owner_main_held=Decimal("0"),
        custody_liabilities=Decimal("30"),
    )

    availability = result["availability"]

    assert (
        availability["third_party_liabilities"]
        == "30"
    )
    assert (
        availability["economic_available"]
        == "70"
    )
    assert (
        availability["accounting_shortfall"]
        == "0"
    )


def test_main_account_shortfall_fails_closed_to_zero():
    result = build_withdrawal_capabilities(
        owner_account_id="zolnode",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[
            {
                "currency": "USDT",
                "available": "20",
                "locked": "0",
            }
        ],
        raw_chains=CHAINS,
        raw_withdraw_status=STATUS,
        owner_main_held=Decimal("0"),
        custody_liabilities=Decimal("30"),
    )

    availability = result["availability"]

    assert (
        availability["economic_available"]
        == "0"
    )
    assert (
        availability["accounting_shortfall"]
        == "10"
    )


def test_missing_gate_status_disables_capability():
    result = build_withdrawal_capabilities(
        owner_account_id="arnold",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[],
        raw_chains=CHAINS,
        raw_withdraw_status=[],
        owner_main_held=Decimal("0"),
        custody_liabilities=Decimal("0"),
    )

    assert (
        result["gate_limits"]["status_available"]
        is False
    )

    assert all(
        not item["capability_ready"]
        for item in result["chains"]
    )


@pytest.mark.asyncio
async def test_capability_api_is_owner_scoped():
    from app.api.treasury import (
        treasury_withdrawal_capabilities,
    )

    user = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await treasury_withdrawal_capabilities(
            "USDT",
            user=user,
            owner_account_id="eqtydao",
        )

    assert exc_info.value.status_code == 403
