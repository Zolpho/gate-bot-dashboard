from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .accounts import GateAccountConfig


class TreasuryTransferValidationError(RuntimeError):
    pass


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def as_decimal(value: Any) -> Decimal | None:
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


def build_subaccount_to_main_preflight(
    *,
    source_account: GateAccountConfig,
    main_account_id: str,
    currency: str,
    amount: Decimal,
    spot_accounts: Any,
) -> dict[str, Any]:
    main_account_id = main_account_id.strip().lower()
    currency = currency.strip().upper()

    if source_account.id == main_account_id:
        raise TreasuryTransferValidationError(
            "Main account funds do not require a "
            "subaccount-to-main transfer"
        )

    if source_account.account_type != "subaccount":
        raise TreasuryTransferValidationError(
            f"Source account '{source_account.id}' must have "
            "account_type='subaccount'"
        )

    rows = (
        spot_accounts
        if isinstance(spot_accounts, list)
        else []
    )

    balance = next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and str(
                row.get("currency", "")
            ).upper() == currency
        ),
        {},
    )

    available = (
        as_decimal(balance.get("available"))
        or Decimal("0")
    )

    locked = (
        as_decimal(balance.get("locked"))
        or Decimal("0")
    )

    errors: list[str] = []

    if available < amount:
        errors.append(
            "Insufficient available balance: "
            f"requested {decimal_text(amount)} {currency}, "
            f"available {decimal_text(available)} {currency}"
        )

    return {
        "can_simulate": not errors,
        "source_account_id": source_account.id,
        "destination_account_id": main_account_id,
        "direction": "from",
        "currency": currency,
        "amount": decimal_text(amount),
        "available": decimal_text(available),
        "locked": decimal_text(locked),
        "remaining_after_transfer": (
            decimal_text(available - amount)
            if available >= amount
            else None
        ),
        "errors": errors,
    }
