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
) -> dict[str, Any]:
    owner = owner_account_id.strip().lower()
    main = main_account_id.strip().lower()
    symbol = currency.strip().upper()

    available, locked = _spot_balance(
        spot_accounts,
        symbol,
    )

    owner_main_held = Decimal(
        owner_main_held
    )
    custody_liabilities = Decimal(
        custody_liabilities
    )

    if owner == main:
        third_party_liabilities = max(
            Decimal("0"),
            custody_liabilities
            - owner_main_held,
        )

        raw_economic = (
            available
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

        availability_model = (
            "main_physical_minus_third_party_"
            "main_held_liabilities"
        )

    else:
        third_party_liabilities = Decimal("0")

        economic_available = (
            available
            + owner_main_held
        )

        accounting_shortfall = Decimal("0")

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
            "economic_available": (
                _decimal_text(
                    economic_available
                )
            ),
            "accounting_shortfall": (
                _decimal_text(
                    accounting_shortfall
                )
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
