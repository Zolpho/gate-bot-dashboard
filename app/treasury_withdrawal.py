from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .deposits import normalize_currency_chains


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None

    if not result.is_finite():
        return None

    return result


def _decimal_text(
    value: Decimal | None,
) -> str | None:
    if value is None:
        return None

    text = format(value, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent

    return (
        -exponent
        if exponent < 0
        else 0
    )


def _chain_key(value: Any) -> str:
    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(value or "").upper(),
    )


def _text_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    result: dict[str, str] = {}

    for key, raw in value.items():
        normalized = _chain_key(key)

        if normalized:
            result[normalized] = str(
                raw or ""
            ).strip()

    return result


def _spot_balance(
    spot_accounts: Any,
    currency: str,
) -> tuple[Decimal, Decimal]:
    rows = (
        spot_accounts
        if isinstance(spot_accounts, list)
        else []
    )

    row = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(
                item.get("currency") or ""
            ).upper()
            == currency
        ),
        {},
    )

    available = (
        _decimal(row.get("available"))
        or Decimal("0")
    )

    locked = (
        _decimal(row.get("locked"))
        or Decimal("0")
    )

    return available, locked


def _withdrawal_precision(
    value: Any,
) -> int | None:
    text = str(value or "").strip()

    if not text.isdigit():
        return None

    precision = int(text)

    if precision < 0 or precision > 36:
        return None

    return precision


def _percent_fraction(
    value: Any,
) -> Decimal | None:
    text = str(value or "").strip()

    # Gate currently documents and returns percentage
    # withdrawal fees with an explicit "%" suffix.
    # Refuse ambiguous values instead of guessing.
    if not text.endswith("%"):
        return None

    percent = _decimal(
        text[:-1].strip()
    )

    if percent is None or percent < 0:
        return None

    return percent / Decimal("100")


def normalize_withdraw_status(
    raw_status: Any,
    *,
    currency: str,
) -> dict[str, Any]:
    symbol = currency.strip().upper()

    rows = (
        raw_status
        if isinstance(raw_status, list)
        else []
    )

    row = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(
                item.get("currency") or ""
            ).upper()
            == symbol
        ),
        None,
    )

    if row is None:
        return {
            "available": False,
            "currency": symbol,
            "minimum": None,
            "maximum_per_withdrawal": None,
            "daily_limit": None,
            "daily_limit_remaining": None,
            "fixed_fee": None,
            "percent_fee": None,
            "fixed_fee_on_chains": {},
            "percent_fee_on_chains": {},
        }

    return {
        "available": True,
        "currency": symbol,
        "minimum": _decimal_text(
            _decimal(
                row.get("withdraw_amount_mini")
            )
        ),
        "maximum_per_withdrawal": _decimal_text(
            _decimal(
                row.get("withdraw_eachtime_limit")
            )
        ),
        "daily_limit": _decimal_text(
            _decimal(
                row.get("withdraw_day_limit")
            )
        ),
        "daily_limit_remaining": _decimal_text(
            _decimal(
                row.get(
                    "withdraw_day_limit_remain"
                )
            )
        ),
        "fixed_fee": (
            str(
                row.get("withdraw_fix") or ""
            ).strip()
            or None
        ),
        "percent_fee": (
            str(
                row.get("withdraw_percent") or ""
            ).strip()
            or None
        ),
        "fixed_fee_on_chains": _text_map(
            row.get("withdraw_fix_on_chains")
        ),
        "percent_fee_on_chains": _text_map(
            row.get(
                "withdraw_percent_on_chains"
            )
        ),
    }


def build_withdrawal_capabilities(
    *,
    owner_account_id: str,
    main_account_id: str,
    currency: str,
    spot_accounts: Any,
    raw_chains: Any,
    raw_withdraw_status: Any,
    owner_main_held: Decimal,
    custody_liabilities: Decimal,
    main_spot_accounts: Any = None,
) -> dict[str, Any]:
    owner = owner_account_id.strip().lower()
    main = main_account_id.strip().lower()
    symbol = currency.strip().upper()

    available, locked = _spot_balance(
        spot_accounts,
        symbol,
    )

    if owner == main:
        main_available = available
        main_locked = locked
    else:
        (
            main_available,
            main_locked,
        ) = _spot_balance(
            main_spot_accounts,
            symbol,
        )

    owner_main_held = Decimal(
        owner_main_held
    )

    custody_liabilities = Decimal(
        custody_liabilities
    )

    positive_owner_main_held = max(
        Decimal("0"),
        owner_main_held,
    )

    third_party_liabilities = max(
        Decimal("0"),
        custody_liabilities
        - positive_owner_main_held,
    )

    custody_liquidity_shortfall = max(
        Decimal("0"),
        custody_liabilities
        - main_available,
    )

    if owner == main:
        raw_economic = (
            main_available
            - third_party_liabilities
        )

        economic_available = max(
            Decimal("0"),
            raw_economic,
        )

        accounting_shortfall = max(
            Decimal("0"),
            -raw_economic,
        )

        owner_liquid_main_held = Decimal("0")

        withdrawal_funding_available = (
            economic_available
        )

        availability_model = (
            "main_physical_minus_third_party_"
            "main_held_liabilities"
        )

    else:
        raw_economic = (
            available
            + owner_main_held
        )

        economic_available = max(
            Decimal("0"),
            raw_economic,
        )

        accounting_shortfall = max(
            Decimal("0"),
            -raw_economic,
        )

        main_after_other_liabilities = max(
            Decimal("0"),
            main_available
            - third_party_liabilities,
        )

        owner_liquid_main_held = min(
            positive_owner_main_held,
            main_after_other_liabilities,
        )

        withdrawal_funding_available = (
            available
            + owner_liquid_main_held
        )

        availability_model = (
            "owner_subaccount_available_plus_"
            "owner_main_held"
        )

    status = normalize_withdraw_status(
        raw_withdraw_status,
        currency=symbol,
    )

    fixed_by_chain = status[
        "fixed_fee_on_chains"
    ]

    percent_by_chain = status[
        "percent_fee_on_chains"
    ]

    chains = []

    for chain in normalize_currency_chains(
        raw_chains
    ):
        key = _chain_key(
            chain.get("chain")
        )

        fixed_fee = (
            fixed_by_chain.get(key)
            if key in fixed_by_chain
            else status["fixed_fee"]
        )

        percent_fee = (
            percent_by_chain.get(key)
            if key in percent_by_chain
            else status["percent_fee"]
        )

        chains.append(
            {
                **chain,
                "fixed_fee": fixed_fee,
                "percent_fee": percent_fee,
                "fixed_fee_source": (
                    "chain"
                    if key in fixed_by_chain
                    else "currency"
                ),
                "percent_fee_source": (
                    "chain"
                    if key in percent_by_chain
                    else "currency"
                ),
                "capability_ready": bool(
                    chain.get(
                        "withdraw_enabled"
                    )
                    and status["available"]
                ),
            }
        )

    return {
        "owner_account_id": owner,
        "main_account_id": main,
        "currency": symbol,
        "availability": {
            "model": availability_model,
            "source_spot_available": (
                _decimal_text(available)
            ),
            "source_spot_locked": (
                _decimal_text(locked)
            ),
            "owner_main_held": (
                _decimal_text(
                    owner_main_held
                )
            ),
            "owner_liquid_main_held": (
                _decimal_text(
                    owner_liquid_main_held
                )
            ),
            "economic_available": (
                _decimal_text(
                    economic_available
                )
            ),
            "withdrawal_funding_available": (
                _decimal_text(
                    withdrawal_funding_available
                )
            ),
            "accounting_shortfall": (
                _decimal_text(
                    accounting_shortfall
                )
            ),
            **(
                {
                    "main_spot_available": (
                        _decimal_text(main_available)
                    ),
                    "main_spot_locked": (
                        _decimal_text(main_locked)
                    ),
                    "custody_liabilities": (
                        _decimal_text(
                            custody_liabilities
                        )
                    ),
                    "third_party_liabilities": (
                        _decimal_text(
                            third_party_liabilities
                        )
                    ),
                    "custody_liquidity_shortfall": (
                        _decimal_text(
                            custody_liquidity_shortfall
                        )
                    ),
                }
                if owner == main
                else {}
            ),
        },
        "gate_limits": {
            "status_available": (
                status["available"]
            ),
            "minimum": status["minimum"],
            "maximum_per_withdrawal": (
                status[
                    "maximum_per_withdrawal"
                ]
            ),
            "daily_limit": (
                status["daily_limit"]
            ),
            "daily_limit_remaining": (
                status[
                    "daily_limit_remaining"
                ]
            ),
        },
        "chains": chains,
    }


def build_withdrawal_preflight(
    *,
    capabilities: dict[str, Any],
    chain: str,
    amount: Decimal,
) -> dict[str, Any]:
    amount = Decimal(amount)

    requested_chain = str(
        chain or ""
    ).strip()

    amount_positive = bool(
        amount.is_finite()
        and amount > 0
    )

    selected_chain = next(
        (
            item
            for item in (
                capabilities.get("chains")
                or []
            )
            if isinstance(item, dict)
            and _chain_key(
                item.get("chain")
            )
            == _chain_key(requested_chain)
        ),
        None,
    )

    gate_limits = (
        capabilities.get("gate_limits")
        or {}
    )

    availability = (
        capabilities.get("availability")
        or {}
    )

    gate_status_available = bool(
        gate_limits.get("status_available")
    )

    chain_known = (
        selected_chain is not None
    )

    chain_available = bool(
        selected_chain
        and selected_chain.get(
            "capability_ready"
        )
    )

    precision = (
        _withdrawal_precision(
            selected_chain.get("decimal")
        )
        if selected_chain
        else None
    )

    precision_valid = bool(
        amount_positive
        and precision is not None
        and _decimal_places(amount)
        <= precision
    )

    minimum = _decimal(
        gate_limits.get("minimum")
    )

    maximum = _decimal(
        gate_limits.get(
            "maximum_per_withdrawal"
        )
    )

    daily_remaining = _decimal(
        gate_limits.get(
            "daily_limit_remaining"
        )
    )

    minimum_valid = bool(
        amount_positive
        and minimum is not None
        and amount >= minimum
    )

    maximum_valid = bool(
        amount_positive
        and maximum is not None
        and amount <= maximum
    )

    daily_limit_valid = bool(
        amount_positive
        and daily_remaining is not None
        and amount <= daily_remaining
    )

    fixed_fee = (
        _decimal(
            selected_chain.get("fixed_fee")
        )
        if selected_chain
        else None
    )

    percent_fraction = (
        _percent_fraction(
            selected_chain.get(
                "percent_fee"
            )
        )
        if selected_chain
        else None
    )

    fee_known = bool(
        fixed_fee is not None
        and fixed_fee >= 0
        and percent_fraction is not None
        and percent_fraction >= 0
    )

    estimated_fee = None

    if fee_known:
        estimated_fee = (
            fixed_fee
            + (
                amount
                * percent_fraction
            )
        )

    # Gate exposes the withdrawal minimum and chain fee
    # separately. Fail closed when the estimated amount
    # remaining after the fee would be zero/negative or
    # below Gate's advertised minimum.
    #
    # This is intentionally an estimate because Gate's
    # public API documentation does not explicitly define
    # the minimum-vs-fee arithmetic.
    recipient_amount_estimate = None
    recipient_amount_positive = False
    recipient_minimum_valid = False

    if (
        amount_positive
        and estimated_fee is not None
    ):
        recipient_amount_estimate = (
            amount - estimated_fee
        )

        recipient_amount_positive = bool(
            recipient_amount_estimate > 0
        )

        recipient_minimum_valid = bool(
            minimum is not None
            and recipient_amount_estimate
            >= minimum
        )

    # Gate withdrawal `amount` is the gross custody
    # debit. The withdrawal fee is deducted inside that
    # amount before recipient delivery.
    #
    # This is independently supported by the production
    # canary:
    # - Gate account-book debit: 50 USDT
    # - Gate withdrawal fee:    1.04 USDT
    # - on-chain recipient:     48.96 USDT
    #
    # Keep the historical field name for API/database
    # compatibility. Existing persisted snapshots remain
    # immutable.
    conservative_funding_required = (
        amount
        if (
            amount_positive
            and estimated_fee is not None
        )
        else None
    )

    economic_available = _decimal(
        availability.get(
            "economic_available"
        )
    )

    funding_available = _decimal(
        availability.get(
            "withdrawal_funding_available"
        )
    )

    source_available = (
        _decimal(
            availability.get(
                "source_spot_available"
            )
        )
        or Decimal("0")
    )

    owner_liquid_main_held = (
        _decimal(
            availability.get(
                "owner_liquid_main_held"
            )
        )
        or Decimal("0")
    )

    economic_balance_valid = bool(
        conservative_funding_required
        is not None
        and economic_available is not None
        and economic_available
        >= conservative_funding_required
    )

    funding_balance_valid = bool(
        conservative_funding_required
        is not None
        and funding_available is not None
        and funding_available
        >= conservative_funding_required
    )

    owner = str(
        capabilities.get(
            "owner_account_id"
        )
        or ""
    ).lower()

    main = str(
        capabilities.get(
            "main_account_id"
        )
        or ""
    ).lower()

    if (
        conservative_funding_required
        is None
    ):
        minimum_jit_transfer = None

    elif owner == main:
        minimum_jit_transfer = Decimal("0")

    else:
        minimum_jit_transfer = max(
            Decimal("0"),
            conservative_funding_required
            - owner_liquid_main_held,
        )

    jit_required = bool(
        minimum_jit_transfer is not None
        and minimum_jit_transfer > 0
    )

    jit_source_balance_valid = bool(
        minimum_jit_transfer is not None
        and (
            owner == main
            or source_available
            >= minimum_jit_transfer
        )
    )

    checks = {
        "amount_positive": amount_positive,
        "gate_status_available": (
            gate_status_available
        ),
        "chain_known": chain_known,
        "chain_available": chain_available,
        "precision_known": (
            precision is not None
        ),
        "precision_valid": precision_valid,
        "minimum_known": (
            minimum is not None
        ),
        "minimum_valid": minimum_valid,
        "maximum_known": (
            maximum is not None
        ),
        "maximum_valid": maximum_valid,
        "daily_limit_known": (
            daily_remaining is not None
        ),
        "daily_limit_valid": (
            daily_limit_valid
        ),
        "fee_known": fee_known,
        "recipient_amount_positive": (
            recipient_amount_positive
        ),
        "recipient_minimum_valid": (
            recipient_minimum_valid
        ),
        "economic_balance_valid": (
            economic_balance_valid
        ),
        "funding_balance_valid": (
            funding_balance_valid
        ),
        "jit_source_balance_valid": (
            jit_source_balance_valid
        ),
    }

    required_checks = (
        "amount_positive",
        "gate_status_available",
        "chain_known",
        "chain_available",
        "precision_known",
        "precision_valid",
        "minimum_known",
        "minimum_valid",
        "maximum_known",
        "maximum_valid",
        "daily_limit_known",
        "daily_limit_valid",
        "fee_known",
        "recipient_amount_positive",
        "recipient_minimum_valid",
        "economic_balance_valid",
        "funding_balance_valid",
        "jit_source_balance_valid",
    )

    preflight_valid = all(
        checks[name]
        for name in required_checks
    )

    errors = [
        name
        for name in required_checks
        if not checks[name]
    ]

    return {
        "status": (
            "ready"
            if preflight_valid
            else "invalid"
        ),
        "preflight_valid": preflight_valid,

        # T2C.1B deliberately cannot execute.
        "executable": False,
        "execution_block_reason": (
            "withdrawal_execution_not_enabled"
        ),
        "gate_write_performed": False,

        "owner_account_id": owner,
        "main_account_id": main,
        "currency": capabilities.get(
            "currency"
        ),

        "request": {
            "chain": requested_chain,
            "amount": _decimal_text(
                amount
            ),
        },

        "network": (
            {
                "chain": selected_chain.get(
                    "chain"
                ),
                "name": selected_chain.get(
                    "name"
                ),
                "withdraw_enabled": (
                    selected_chain.get(
                        "withdraw_enabled"
                    )
                ),
                "requires_memo": bool(
                    selected_chain.get(
                        "requires_memo"
                    )
                ),
                "withdrawal_precision": (
                    precision
                ),
            }
            if selected_chain
            else None
        ),

        "limits": {
            "minimum": (
                _decimal_text(minimum)
            ),
            "maximum_per_withdrawal": (
                _decimal_text(maximum)
            ),
            "daily_limit_remaining": (
                _decimal_text(
                    daily_remaining
                )
            ),
        },

        "fee": {
            "fixed_fee": (
                _decimal_text(fixed_fee)
            ),
            "percent_fee": (
                selected_chain.get(
                    "percent_fee"
                )
                if selected_chain
                else None
            ),
            "estimated_fee": (
                _decimal_text(
                    estimated_fee
                )
            ),
            "recipient_amount_estimate": (
                _decimal_text(
                    recipient_amount_estimate
                )
            ),
            "estimate_only": True,
            "semantics_verified": False,
        },

        "funding": {
            "economic_available": (
                _decimal_text(
                    economic_available
                )
            ),
            "withdrawal_funding_available": (
                _decimal_text(
                    funding_available
                )
            ),
            "source_spot_available": (
                _decimal_text(
                    source_available
                )
            ),
            "owner_main_held": (
                availability.get(
                    "owner_main_held"
                )
            ),
            "owner_liquid_main_held": (
                _decimal_text(
                    owner_liquid_main_held
                )
            ),
            "conservative_funding_required": (
                _decimal_text(
                    conservative_funding_required
                )
            ),
            "jit_required": jit_required,
            "minimum_jit_transfer": (
                _decimal_text(
                    minimum_jit_transfer
                )
            ),
        },

        "checks": checks,
        "errors": errors,

        "destination": {
            "status": "not_in_scope",
            "phase": "T2C2",
        },
    }


def _withdrawal_address_key(
    value: Any,
) -> tuple[str, str]:
    text = str(value or "").strip()

    # EVM addresses are hexadecimal and case-insensitive.
    # Preserve exact case semantics for non-EVM address
    # formats such as Base58.
    if (
        len(text) == 42
        and text.startswith(("0x", "0X"))
    ):
        payload = text[2:]

        if all(
            char in "0123456789abcdefABCDEF"
            for char in payload
        ):
            return ("evm", text.lower())

    return ("exact", text)


def bind_gate_address_eligibility_to_preflight(
    *,
    preflight: dict[str, Any],
    saved_addresses: Any,
    withdrawals: Any,
    now_timestamp: int,
    address_policy: str = "verification_free",
    minimum_age_seconds: int = 86400,
    history_window_seconds: int = 2592000,
) -> dict[str, Any]:
    """
    Bind read-only Gate address-book and prior-use
    evidence to an existing destination-bound preflight.

    No persistence and no Gate write is performed.
    """
    destination = (
        preflight.get("destination")
        if isinstance(
            preflight.get("destination"),
            dict,
        )
        else {}
    )

    currency = str(
        destination.get("currency") or ""
    ).strip().upper()

    chain = str(
        destination.get("chain") or ""
    ).strip().upper()

    address = str(
        destination.get("address") or ""
    ).strip()

    memo = str(
        destination.get("memo") or ""
    ).strip()

    address_key = _withdrawal_address_key(
        address
    )

    saved_rows = (
        saved_addresses
        if isinstance(saved_addresses, list)
        else []
    )

    saved_matches = []

    for row in saved_rows:
        if not isinstance(row, dict):
            continue

        row_currency = str(
            row.get("currency") or ""
        ).strip().upper()

        row_chain = str(
            row.get("chain") or ""
        ).strip().upper()

        row_address_key = (
            _withdrawal_address_key(
                row.get("address")
            )
        )

        row_tag = str(
            row.get("tag") or ""
        ).strip()

        if (
            row_currency == currency
            and _chain_key(row_chain)
            == _chain_key(chain)
            and row_address_key == address_key
            and row_tag == memo
        ):
            saved_matches.append(row)

    saved_address_match = bool(
        saved_matches
    )

    saved_verified = any(
        str(
            row.get("verified") or ""
        ).strip() == "1"
        for row in saved_matches
    )

    withdrawal_rows = (
        withdrawals
        if isinstance(withdrawals, list)
        else []
    )

    matching_done = []

    for row in withdrawal_rows:
        if not isinstance(row, dict):
            continue

        row_currency = str(
            row.get("currency") or ""
        ).strip().upper()

        row_chain = str(
            row.get("chain") or ""
        ).strip().upper()

        row_address_key = (
            _withdrawal_address_key(
                row.get("address")
            )
        )

        row_memo = str(
            row.get("memo") or ""
        ).strip()

        status = str(
            row.get("status") or ""
        ).strip().upper()

        if (
            row_currency != currency
            or _chain_key(row_chain)
            != _chain_key(chain)
            or row_address_key != address_key
            or row_memo != memo
            or status != "DONE"
        ):
            continue

        try:
            completed_at = int(
                str(
                    row.get("timestamp2")
                    or "0"
                )
            )
        except (TypeError, ValueError):
            completed_at = 0

        try:
            block_number = int(
                str(
                    row.get("block_number")
                    or "0"
                )
            )
        except (TypeError, ValueError):
            block_number = 0

        if (
            completed_at <= 0
            or block_number <= 0
        ):
            continue

        matching_done.append(
            (
                completed_at,
                block_number,
                row,
            )
        )

    matching_done.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    prior_row = (
        matching_done[0][2]
        if matching_done
        else None
    )

    prior_completed_at = (
        matching_done[0][0]
        if matching_done
        else 0
    )

    prior_block_number = (
        matching_done[0][1]
        if matching_done
        else 0
    )

    prior_age_seconds = (
        max(
            0,
            int(now_timestamp)
            - prior_completed_at,
        )
        if prior_completed_at
        else None
    )

    prior_use_qualified = bool(
        prior_row is not None
        and prior_age_seconds is not None
        and prior_age_seconds
        >= int(minimum_age_seconds)
    )

    requested_address_policy = str(
        address_policy or ""
    ).strip().lower()

    allowed_address_policies = {
        "verification_free",
        "address_book",
    }

    address_policy_valid = (
        requested_address_policy
        in allowed_address_policies
    )

    # Unknown/missing policy is evaluated using the
    # stricter mode and is also explicitly invalid.
    effective_address_policy = (
        requested_address_policy
        if address_policy_valid
        else "verification_free"
    )

    verification_required = (
        effective_address_policy
        == "verification_free"
    )

    gate_address_eligible = bool(
        saved_address_match
        and (
            saved_verified
            if verification_required
            else True
        )
    )

    # These are visible facts. In address_book mode a
    # normal saved address may legitimately have
    # gate_saved_address_verified=False.
    eligibility_checks = {
        "gate_saved_address_match": (
            saved_address_match
        ),
        "gate_saved_address_verified": (
            saved_verified
        ),
        "gate_address_policy_valid": (
            address_policy_valid
        ),
        "gate_address_eligible": (
            gate_address_eligible
        ),
    }

    # Only policy-required checks participate in
    # validity/errors.
    required_eligibility_checks = {
        "gate_saved_address_match": (
            saved_address_match
        ),
        "gate_address_policy_valid": (
            address_policy_valid
        ),
        "gate_address_eligible": (
            gate_address_eligible
        ),
    }

    if verification_required:
        required_eligibility_checks[
            "gate_saved_address_verified"
        ] = saved_verified

    checks = {
        **dict(
            preflight.get("checks")
            or {}
        ),
        **eligibility_checks,
    }

    errors = list(
        preflight.get("errors")
        or []
    )

    for name, passed in (
        required_eligibility_checks.items()
    ):
        if (
            not passed
            and name not in errors
        ):
            errors.append(name)

    base_valid = bool(
        preflight.get("preflight_valid")
    )

    preflight_valid = bool(
        base_valid
        and all(
            required_eligibility_checks.values()
        )
    )

    if not gate_address_eligible:
        eligible_via = ""

    elif verification_required:
        eligible_via = "verified_address"

    else:
        eligible_via = "address_book"

    evidence = {
        "saved_address_matches": len(
            saved_matches
        ),
        "saved_address_verified": (
            saved_verified
        ),
        "address_policy": (
            effective_address_policy
        ),
        "address_policy_valid": (
            address_policy_valid
        ),
        "verification_required": (
            verification_required
        ),
        "eligible": (
            gate_address_eligible
        ),
        "eligible_via": eligible_via,
        "minimum_age_seconds": int(
            minimum_age_seconds
        ),
        "history_window_seconds": int(
            history_window_seconds
        ),
        "prior_withdrawal_id": (
            prior_row.get("id")
            if prior_row
            else None
        ),
        "prior_withdrawal_timestamp2": (
            str(prior_completed_at)
            if prior_completed_at
            else None
        ),
        "prior_withdrawal_age_seconds": (
            prior_age_seconds
        ),
        "prior_withdrawal_block_number": (
            str(prior_block_number)
            if prior_block_number
            else None
        ),
        "prior_withdrawal_txid": (
            prior_row.get("txid")
            if prior_row
            else None
        ),
        "gate_write_performed": False,
    }

    return {
        **preflight,
        "status": (
            "ready"
            if preflight_valid
            else "invalid"
        ),
        "preflight_valid": (
            preflight_valid
        ),
        "executable": False,
        "execution_block_reason": (
            "withdrawal_execution_not_enabled"
        ),
        "gate_write_performed": False,
        "checks": checks,
        "errors": errors,
        "gate_address_eligibility": (
            evidence
        ),
    }


def bind_destination_to_preflight(
    *,
    preflight: dict[str, Any],
    destination: dict[str, Any],
    owner_account_id: str,
    currency: str,
) -> dict[str, Any]:
    """
    Bind a locally registered withdrawal destination to an
    otherwise read-only Gate/funding preflight.

    This performs no persistence and no Gate operation.
    """
    owner = str(
        owner_account_id or ""
    ).strip().lower()

    symbol = str(
        currency or ""
    ).strip().upper()

    destination_owner = str(
        destination.get("owner_account_id")
        or ""
    ).strip().lower()

    destination_currency = str(
        destination.get("currency")
        or ""
    ).strip().upper()

    destination_chain = str(
        destination.get("chain")
        or ""
    ).strip().upper()

    destination_status = str(
        destination.get("status")
        or ""
    ).strip().lower()

    destination_memo = str(
        destination.get("memo")
        or ""
    ).strip()

    network = (
        preflight.get("network")
        if isinstance(
            preflight.get("network"),
            dict,
        )
        else {}
    )

    preflight_chain = str(
        network.get("chain")
        or ""
    ).strip().upper()

    requires_memo = bool(
        network.get("requires_memo")
    )

    destination_checks = {
        "destination_owner_match": (
            destination_owner == owner
        ),
        "destination_currency_match": (
            destination_currency == symbol
        ),
        "destination_chain_match": (
            bool(destination_chain)
            and bool(preflight_chain)
            and _chain_key(destination_chain)
            == _chain_key(preflight_chain)
        ),
        "destination_approved": (
            destination_status == "approved"
        ),
        "destination_memo_valid": (
            bool(destination_memo)
            if requires_memo
            else True
        ),
    }

    existing_checks = dict(
        preflight.get("checks")
        or {}
    )

    checks = {
        **existing_checks,
        **destination_checks,
    }

    destination_errors = [
        name
        for name, passed
        in destination_checks.items()
        if not passed
    ]

    errors = list(
        preflight.get("errors")
        or []
    )

    for error in destination_errors:
        if error not in errors:
            errors.append(error)

    destination_valid = all(
        destination_checks.values()
    )

    base_valid = bool(
        preflight.get("preflight_valid")
    )

    preflight_valid = bool(
        base_valid
        and destination_valid
    )

    return {
        **preflight,
        "status": (
            "ready"
            if preflight_valid
            else "invalid"
        ),
        "preflight_valid": preflight_valid,

        # T2C.2B is still deliberately non-executable.
        "executable": False,
        "execution_block_reason": (
            "withdrawal_execution_not_enabled"
        ),
        "gate_write_performed": False,

        "checks": checks,
        "errors": errors,

        "destination": {
            "destination_id": (
                destination.get(
                    "destination_id"
                )
            ),
            "owner_account_id": (
                destination_owner
            ),
            "currency": (
                destination_currency
            ),
            "chain": destination_chain,
            "address": destination.get(
                "address"
            ),
            "memo": destination.get(
                "memo"
            ),
            "label": destination.get(
                "label"
            ),
            "status": destination_status,
            "verification_method": (
                destination.get(
                    "verification_method"
                )
            ),
            "approved_by": (
                destination.get(
                    "approved_by"
                )
            ),
            "approved_at": (
                destination.get(
                    "approved_at"
                )
            ),
            "requires_memo": requires_memo,
            "valid_for_preflight": (
                destination_valid
            ),
        },
    }
