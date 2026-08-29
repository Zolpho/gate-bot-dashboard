from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.deposits import (
    normalize_currency_chains,
)
from app.security import DashboardUser
from app.treasury_withdrawal import (
    bind_destination_to_preflight,
    bind_gate_address_eligibility_to_preflight,
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
        == "5"
    )

    assert (
        result["funding"][
            "minimum_jit_transfer"
        ]
        == "2"
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


def test_withdrawal_preflight_rejects_amount_consumed_by_fee():
    result = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="TRX",
        amount=Decimal("1"),
    )

    # Regression for the real Gate rejection where:
    #
    # requested amount = 1
    # Gate minimum     = 1
    # fixed fee        = 1
    #
    # The old preflight accepted this because the gross
    # amount met the minimum even though nothing remained
    # after the fee.
    assert (
        result["checks"]["minimum_valid"]
        is True
    )

    assert (
        result["fee"]["estimated_fee"]
        == "1"
    )

    assert (
        result["fee"][
            "recipient_amount_estimate"
        ]
        == "0"
    )

    assert (
        result["checks"][
            "recipient_amount_positive"
        ]
        is False
    )

    assert (
        result["checks"][
            "recipient_minimum_valid"
        ]
        is False
    )

    assert result["preflight_valid"] is False

    assert (
        "recipient_amount_positive"
        in result["errors"]
    )

    assert (
        "recipient_minimum_valid"
        in result["errors"]
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


def test_withdrawal_preflight_uses_requested_amount_for_funding():
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

    # Gate funding authority is the requested amount.
    # The fee must not be added a second time.
    assert (
        result["funding"][
            "conservative_funding_required"
        ]
        == "1"
    )

    assert (
        result["checks"][
            "economic_balance_valid"
        ]
        is True
    )

    assert (
        result["checks"][
            "funding_balance_valid"
        ]
        is True
    )

    # The same request remains invalid for the correct
    # independent reason: the fee consumes the entire
    # requested amount, leaving nothing for the recipient.
    assert (
        result["fee"][
            "recipient_amount_estimate"
        ]
        == "0"
    )

    assert (
        result["checks"][
            "recipient_amount_positive"
        ]
        is False
    )

    assert (
        result["checks"][
            "recipient_minimum_valid"
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
            destination_id="wd_not_reached",
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


def _approved_destination(
    *,
    status: str = "approved",
    chain: str = "TRX",
    currency: str = "USDT",
    memo: str = "",
):
    return {
        "destination_id": (
            "wd_0123456789abcdef"
            "0123456789abcdef"
        ),
        "owner_account_id": "arnold",
        "currency": currency,
        "chain": chain,
        "address": (
            "0x111111111111111111111111"
            "1111111111111111"
        ),
        "memo": memo,
        "label": "Approved wallet",
        "status": status,
        "verification_method": (
            "manual_admin_approval"
        ),
        "approved_by": "rootadmin",
        "approved_at": (
            "2026-08-15T12:30:16+00:00"
        ),
    }


def test_destination_binding_accepts_exact_approved_destination():
    base = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="TRX",
        amount=Decimal("5"),
    )

    result = bind_destination_to_preflight(
        preflight=base,
        destination=_approved_destination(),
        owner_account_id="arnold",
        currency="USDT",
    )

    assert result["preflight_valid"] is True
    assert result["executable"] is False

    assert (
        result["destination"]["status"]
        == "approved"
    )

    assert (
        result["destination"][
            "valid_for_preflight"
        ]
        is True
    )

    assert (
        result["checks"][
            "destination_approved"
        ]
        is True
    )


def test_destination_binding_rejects_candidate():
    base = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="TRX",
        amount=Decimal("5"),
    )

    result = bind_destination_to_preflight(
        preflight=base,
        destination=_approved_destination(
            status="candidate"
        ),
        owner_account_id="arnold",
        currency="USDT",
    )

    assert result["preflight_valid"] is False

    assert (
        result["checks"][
            "destination_approved"
        ]
        is False
    )

    assert (
        "destination_approved"
        in result["errors"]
    )


def test_destination_binding_rejects_wrong_chain():
    base = build_withdrawal_preflight(
        capabilities=_ready_capabilities(),
        chain="TRX",
        amount=Decimal("5"),
    )

    result = bind_destination_to_preflight(
        preflight=base,
        destination=_approved_destination(
            chain="ETH"
        ),
        owner_account_id="arnold",
        currency="USDT",
    )

    assert result["preflight_valid"] is False

    assert (
        result["checks"][
            "destination_chain_match"
        ]
        is False
    )


def test_destination_binding_requires_memo_for_tag_network():
    capabilities = build_withdrawal_capabilities(
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
        raw_chains=[
            {
                "chain": "TON",
                "name_en": "The Open Network",
                "is_disabled": 0,
                "is_deposit_disabled": 0,
                "is_withdraw_disabled": 0,
                "is_tag": 1,
                "decimal": "6",
            }
        ],
        raw_withdraw_status=[
            {
                "currency": "USDT",
                "withdraw_percent": "0%",
                "withdraw_fix": "0.3",
                "withdraw_day_limit": "100000",
                "withdraw_day_limit_remain": "50000",
                "withdraw_amount_mini": "1",
                "withdraw_eachtime_limit": "20000",
                "withdraw_fix_on_chains": {
                    "TON": "0.3",
                },
                "withdraw_percent_on_chains": {
                    "TON": "0%",
                },
            }
        ],
        owner_main_held=Decimal("3"),
        custody_liabilities=Decimal("3"),
    )

    base = build_withdrawal_preflight(
        capabilities=capabilities,
        chain="TON",
        amount=Decimal("5"),
    )

    assert (
        base["network"]["requires_memo"]
        is True
    )

    result = bind_destination_to_preflight(
        preflight=base,
        destination=_approved_destination(
            chain="TON",
            memo="",
        ),
        owner_account_id="arnold",
        currency="USDT",
    )

    assert result["preflight_valid"] is False

    assert (
        result["checks"][
            "destination_memo_valid"
        ]
        is False
    )


def _gate_eligibility_base_preflight():
    return {
        "status": "ready",
        "preflight_valid": True,
        "executable": False,
        "gate_write_performed": False,
        "checks": {
            "destination_approved": True,
        },
        "errors": [],
        "destination": {
            "destination_id": "wd_test_eth",
            "owner_account_id": "arnold",
            "currency": "USDT",
            "chain": "ETH",
            "address": (
                "0x4De063Bf69f6efb12bCbBb9B70C0E1BA96FD680a"
            ),
            "memo": "",
            "status": "approved",
        },
    }


def _gate_saved_address(
    *,
    verified="0",
    chain="ETH",
    address=None,
    tag="",
):
    return {
        "currency": "USDT",
        "chain": chain,
        "address": (
            address
            or "0x4De063Bf69f6efb12bCbBb9B70C0E1BA96FD680a"
        ),
        "name": "EQTY Treasury ERC20",
        "tag": tag,
        "verified": verified,
    }


def _gate_done_withdrawal(
    *,
    timestamp2,
    chain="ETH",
    address=None,
    memo="",
    block_number="25769009",
):
    return {
        "id": "w100395584",
        "currency": "USDT",
        "chain": chain,
        "address": (
            address
            or "0x4De063Bf69f6efb12bCbBb9B70C0E1BA96FD680a"
        ),
        "memo": memo,
        "status": "DONE",
        "timestamp2": str(timestamp2),
        "block_number": str(block_number),
        "txid": "0xtest",
    }


def test_gate_normal_saved_address_is_not_api_eligible_even_with_prior_use():
    now = 2_000_000

    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[
                _gate_saved_address(
                    verified="0"
                )
            ],
            withdrawals=[
                _gate_done_withdrawal(
                    timestamp2=(
                        now - 90000
                    )
                )
            ],
            now_timestamp=now,
        )
    )

    assert result["preflight_valid"] is False

    assert (
        result["checks"][
            "gate_saved_address_match"
        ]
        is True
    )

    assert (
        result["checks"][
            "gate_saved_address_verified"
        ]
        is False
    )

    assert (
        result["checks"][
            "gate_address_eligible"
        ]
        is False
    )

    assert (
        "gate_saved_address_verified"
        in result["errors"]
    )

    assert (
        "gate_address_eligible"
        in result["errors"]
    )

    evidence = result[
        "gate_address_eligibility"
    ]

    # Historical use remains useful audit evidence,
    # but it no longer authorizes an API withdrawal.
    assert (
        evidence["prior_withdrawal_id"]
        == "w100395584"
    )

    assert evidence["eligible"] is False
    assert evidence["eligible_via"] == ""


def test_gate_verified_saved_address_needs_no_history():
    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[
                _gate_saved_address(
                    verified="1"
                )
            ],
            withdrawals=[],
            now_timestamp=2_000_000,
        )
    )

    assert result["preflight_valid"] is True

    assert (
        result["checks"][
            "gate_saved_address_verified"
        ]
        is True
    )

    assert (
        result[
            "gate_address_eligibility"
        ]["eligible_via"]
        == "verified_address"
    )


def test_gate_saved_address_absent_fails_closed():
    now = 2_000_000

    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[],
            withdrawals=[
                _gate_done_withdrawal(
                    timestamp2=(
                        now - 90000
                    )
                )
            ],
            now_timestamp=now,
        )
    )

    assert result["preflight_valid"] is False

    assert (
        "gate_saved_address_match"
        in result["errors"]
    )

    assert (
        "gate_address_eligible"
        in result["errors"]
    )


def test_gate_prior_use_younger_than_24h_fails():
    now = 2_000_000

    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[
                _gate_saved_address(
                    verified="0"
                )
            ],
            withdrawals=[
                _gate_done_withdrawal(
                    timestamp2=(
                        now - 86399
                    )
                )
            ],
            now_timestamp=now,
        )
    )

    assert result["preflight_valid"] is False

    assert (
        result["checks"][
            "gate_saved_address_match"
        ]
        is True
    )

    assert (
        result["checks"][
            "gate_address_eligible"
        ]
        is False
    )


def test_gate_saved_address_wrong_chain_fails():
    now = 2_000_000

    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[
                _gate_saved_address(
                    chain="ARBEVM",
                    verified="1",
                )
            ],
            withdrawals=[],
            now_timestamp=now,
        )
    )

    assert result["preflight_valid"] is False

    assert (
        result["checks"][
            "gate_saved_address_match"
        ]
        is False
    )


def test_gate_evm_address_match_is_case_insensitive():
    now = 2_000_000

    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[
                _gate_saved_address(
                    verified="1",
                    address=(
                        "0x4de063bf69f6efb12bcbbb9b70c0e1ba96fd680a"
                    ),
                )
            ],
            withdrawals=[],
            now_timestamp=now,
        )
    )

    assert result["preflight_valid"] is True


def test_gate_address_book_policy_accepts_normal_saved_address():
    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[
                _gate_saved_address(
                    verified="0"
                )
            ],
            withdrawals=[],
            now_timestamp=2_000_000,
            address_policy="address_book",
        )
    )

    assert result["preflight_valid"] is True

    assert (
        result["checks"][
            "gate_saved_address_match"
        ]
        is True
    )

    # This remains the actual Gate fact.
    assert (
        result["checks"][
            "gate_saved_address_verified"
        ]
        is False
    )

    assert (
        result["checks"][
            "gate_address_policy_valid"
        ]
        is True
    )

    assert (
        result["checks"][
            "gate_address_eligible"
        ]
        is True
    )

    assert (
        "gate_saved_address_verified"
        not in result["errors"]
    )

    evidence = result[
        "gate_address_eligibility"
    ]

    assert (
        evidence["address_policy"]
        == "address_book"
    )

    assert (
        evidence["verification_required"]
        is False
    )

    assert evidence["eligible"] is True

    assert (
        evidence["eligible_via"]
        == "address_book"
    )


def test_gate_unknown_address_policy_fails_closed():
    result = (
        bind_gate_address_eligibility_to_preflight(
            preflight=(
                _gate_eligibility_base_preflight()
            ),
            saved_addresses=[
                _gate_saved_address(
                    verified="1"
                )
            ],
            withdrawals=[],
            now_timestamp=2_000_000,
            address_policy="something_invalid",
        )
    )

    assert result["preflight_valid"] is False

    assert (
        result["checks"][
            "gate_address_policy_valid"
        ]
        is False
    )

    assert (
        "gate_address_policy_valid"
        in result["errors"]
    )

    evidence = result[
        "gate_address_eligibility"
    ]

    assert (
        evidence["address_policy"]
        == "verification_free"
    )

    assert (
        evidence["address_policy_valid"]
        is False
    )

    assert (
        evidence["verification_required"]
        is True
    )
