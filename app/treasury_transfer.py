from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from .accounts import GateAccountConfig


class TreasuryTransferValidationError(RuntimeError):
    pass


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def gate_client_order_id(request_id: str) -> str:
    """Stable Gate-safe idempotency key derived from our request ID."""
    digest = hashlib.sha256(
        request_id.encode("utf-8")
    ).hexdigest()

    return f"treasury_{digest[:48]}"


def validate_transfer_amount(
    amount: Decimal,
) -> None:
    if not amount.is_finite() or amount <= 0:
        raise TreasuryTransferValidationError(
            "Transfer amount must be greater than zero"
        )

    exponent = amount.as_tuple().exponent
    decimal_places = (
        -exponent
        if exponent < 0
        else 0
    )

    if decimal_places > 8:
        raise TreasuryTransferValidationError(
            "Gate transfer amount supports at most "
            "8 decimal places"
        )


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


def live_transfer_confirmation_text(
    *,
    base_text: str,
    source_account_id: str,
    destination_account_id: str,
    currency: str,
    amount: Decimal,
) -> str:
    return (
        f"{base_text.strip()} "
        f"{source_account_id.strip().lower()} "
        f"{decimal_text(amount)} "
        f"{currency.strip().upper()} "
        f"TO "
        f"{destination_account_id.strip().lower()}"
    )


def build_gate_subaccount_transfer_payload(
    *,
    source_account: GateAccountConfig,
    currency: str,
    amount: Decimal,
    request_id: str,
) -> dict[str, str]:
    validate_transfer_amount(amount)

    if source_account.account_type != "subaccount":
        raise TreasuryTransferValidationError(
            f"Source account '{source_account.id}' must have "
            "account_type='subaccount'"
        )

    if not source_account.gate_uid:
        raise TreasuryTransferValidationError(
            f"Source account '{source_account.id}' has no Gate UID"
        )

    return {
        "sub_account": source_account.gate_uid,
        "sub_account_type": "spot",
        "currency": currency.strip().upper(),
        "amount": decimal_text(amount),
        "direction": "from",
        "client_order_id": gate_client_order_id(
            request_id
        ),
    }


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

    validate_transfer_amount(amount)

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
        "can_transfer": not errors,
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
