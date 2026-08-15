from __future__ import annotations

from decimal import Decimal
from typing import Any


def compact_decimal(
    value: Any,
) -> str:
    decimal_value = Decimal(
        str(value)
    )

    text = format(
        decimal_value,
        "f",
    )

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text


def withdrawal_reservation_confirmation_text(
    request_id: str,
) -> str:
    return (
        "RESERVE WITHDRAWAL "
        + request_id
    )


def withdrawal_confirmation_text(
    request: dict[str, Any],
) -> str:
    return " ".join(
        (
            "CONFIRM WITHDRAWAL",
            str(request["request_id"]),
            str(
                request["owner_account_id"]
            ),
            str(request["currency"]),
            compact_decimal(
                request["amount"]
            ),
            str(request["chain"]),
            str(request["destination_id"]),
        )
    )


def withdrawal_cancel_confirmation_text(
    request_id: str,
) -> str:
    return (
        "CANCEL WITHDRAWAL "
        + request_id
    )


def destination_snapshot_mismatches(
    request: dict[str, Any],
    preflight: dict[str, Any],
) -> list[str]:
    destination = dict(
        preflight.get("destination")
        or {}
    )

    checks = {
        "destination_id": (
            str(request["destination_id"]),
            str(
                destination.get(
                    "destination_id"
                )
                or ""
            ),
        ),
        "owner_account_id": (
            str(
                request["owner_account_id"]
            ).lower(),
            str(
                destination.get(
                    "owner_account_id"
                )
                or ""
            ).lower(),
        ),
        "currency": (
            str(
                request["currency"]
            ).upper(),
            str(
                destination.get("currency")
                or ""
            ).upper(),
        ),
        "chain": (
            str(
                request["chain"]
            ).upper(),
            str(
                destination.get("chain")
                or ""
            ).upper(),
        ),
        "address": (
            str(request["address"]),
            str(
                destination.get("address")
                or ""
            ),
        ),
        "memo": (
            str(request.get("memo") or ""),
            str(
                destination.get("memo")
                or ""
            ),
        ),
    }

    return [
        field
        for field, (
            expected,
            actual,
        ) in checks.items()
        if expected != actual
    ]


def withdrawal_hold_on_main_confirmation_text(
    request_id: str,
) -> str:
    normalized = str(
        request_id or ""
    ).strip()

    if not normalized:
        raise ValueError(
            "Withdrawal request ID is required"
        )

    return (
        "HOLD WITHDRAWAL FUNDS ON MAIN "
        + normalized
    )
