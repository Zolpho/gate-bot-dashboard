from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.deposits import (
    normalize_currency_chains,
)
from app.security import DashboardUser
from app.treasury_withdrawal import (
    build_withdrawal_capabilities,
    build_withdrawal_preflight,
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


def test_subaccount_main_held_is_capped_by_main_liquidity():
    result = build_withdrawal_capabilities(
        owner_account_id="arnold",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[
            {
                "currency": "USDT",
                "available": "10",
                "locked": "0",
            }
        ],
        main_spot_accounts=[
            {
                "currency": "USDT",
                "available": "7",
                "locked": "0",
            }
        ],
        raw_chains=CHAINS,
        raw_withdraw_status=STATUS,
        owner_main_held=Decimal("5"),
        custody_liabilities=Decimal("10"),
    )

    availability = result["availability"]

    assert (
        availability["economic_available"]
        == "15"
    )

    assert (
        availability["owner_liquid_main_held"]
        == "2"
    )

    assert (
        availability[
            "withdrawal_funding_available"
        ]
        == "12"
    )

    # Main custody details are used internally for
    # the calculation but must not be exposed to
    # a subaccount owner.
    assert "main_spot_available" not in availability
    assert "main_spot_locked" not in availability
    assert "custody_liabilities" not in availability
    assert "third_party_liabilities" not in availability
    assert (
        "custody_liquidity_shortfall"
        not in availability
    )


def _ready_capabilities():
    return build_withdrawal_capabilities(
        owner_account_id="arnold",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[
            {
                "currency": "USDT",
                "available": "10",
                "locked": "0",
            }
        ],
        main_spot_accounts=[
            {
                "currency": "USDT",
                "available": "20",
                "locked": "0",
            }
        ],
        raw_chains=CHAINS,
        raw_withdraw_status=STATUS,
        owner_main_held=Decimal("3"),
        custody_liabilities=Decimal("3"),
    )


def test_withdrawal_preflight_ready_and_jit_calculated():
    result = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="TRX",
        amount=Decimal("5"),
    )

    assert result["preflight_valid"] is True
    assert result["executable"] is False
    assert (
        result["execution_block_reason"]
        == "withdrawal_execution_not_enabled"
    )

    assert (
        result["fee"]["estimated_fee"]
        == "1"
    )

    assert (
        result["funding"][
            "conservative_funding_required"
        ]
        == "6"
    )

    assert (
        result["funding"][
            "minimum_jit_transfer"
        ]
        == "3"
    )

    assert (
        result["funding"]["jit_required"]
        is True
    )


def test_withdrawal_preflight_rejects_below_minimum():
    result = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="TRX",
        amount=Decimal("0.5"),
    )

    assert result["preflight_valid"] is False
    assert (
        result["checks"]["minimum_valid"]
        is False
    )


def test_withdrawal_preflight_rejects_precision():
    result = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="TRX",
        amount=Decimal("1.0000001"),
    )

    assert result["preflight_valid"] is False
    assert (
        result["checks"]["precision_valid"]
        is False
    )


def test_withdrawal_preflight_rejects_disabled_chain():
    result = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="ETH",
        amount=Decimal("5"),
    )

    assert result["preflight_valid"] is False
    assert (
        result["checks"]["chain_available"]
        is False
    )


def test_withdrawal_preflight_reserves_fee_for_funding():
    capabilities = (
        build_withdrawal_capabilities(
            owner_account_id="arnold",
            main_account_id="zolnode",
            currency="USDT",
            spot_accounts=[],
            main_spot_accounts=[
                {
                    "currency": "USDT",
                    "available": "1",
                    "locked": "0",
                }
            ],
            raw_chains=CHAINS,
            raw_withdraw_status=STATUS,
            owner_main_held=Decimal("1"),
            custody_liabilities=Decimal("1"),
        )
    )

    result = build_withdrawal_preflight(
        capabilities=capabilities,
        chain="TRX",
        amount=Decimal("1"),
    )

    assert (
        result["funding"][
            "conservative_funding_required"
        ]
        == "2"
    )

    assert (
        result["checks"][
            "economic_balance_valid"
        ]
        is False
    )

    assert (
        result["checks"][
            "funding_balance_valid"
        ]
        is False
    )

    assert result["preflight_valid"] is False


def test_withdrawal_preflight_rejects_unknown_chain():
    result = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="BASE",
        amount=Decimal("5"),
    )

    assert result["preflight_valid"] is False
    assert (
        result["checks"]["chain_known"]
        is False
    )


@pytest.mark.asyncio
async def test_preflight_api_is_owner_scoped():
    from app.api.treasury import (
        treasury_withdrawal_preflight,
    )

    user = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await treasury_withdrawal_preflight(
            "USDT",
            user=user,
            owner_account_id="eqtydao",
            chain="TRX",
            amount=Decimal("1"),
        )

    assert exc_info.value.status_code == 403


def test_main_owner_can_see_main_custody_details():
    result = build_withdrawal_capabilities(
        owner_account_id="zolnode",
        main_account_id="zolnode",
        currency="USDT",
        spot_accounts=[
            {
                "currency": "USDT",
                "available": "100",
                "locked": "2",
            }
        ],
        raw_chains=CHAINS,
        raw_withdraw_status=STATUS,
        owner_main_held=Decimal("0"),
        custody_liabilities=Decimal("30"),
    )

    availability = result["availability"]

    assert (
        availability["main_spot_available"]
        == "100"
    )
    assert (
        availability["main_spot_locked"]
        == "2"
    )
    assert (
        availability["custody_liabilities"]
        == "30"
    )
    assert (
        availability["third_party_liabilities"]
        == "30"
    )
