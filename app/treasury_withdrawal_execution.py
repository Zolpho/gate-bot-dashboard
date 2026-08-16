from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


WITHDRAW_ORDER_ID_RE = re.compile(
    r"^[0-9A-Za-z_.-]{1,32}$"
)


class TreasuryWithdrawalExecutionError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WithdrawalStatusDecision:
    gate_status: str
    request_status: str
    outcome: str
    confidence: str
    terminal: bool
    success: bool
    requires_reconciliation: bool
    summary: str


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal amount is invalid"
        ) from exc

    if (
        not result.is_finite()
        or result <= 0
    ):
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal amount must be positive"
        )

    return result


def _decimal_text(value: Any) -> str:
    amount = _decimal(value)

    text = format(amount, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def gate_withdraw_order_id(
    request_id: str,
) -> str:
    normalized = str(
        request_id or ""
    ).strip()

    if not normalized:
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal request ID is missing"
        )

    # Exactly 32 characters:
    # "wd_" + 29 lowercase hexadecimal characters.
    value = (
        "wd_"
        + hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()[:29]
    )

    if not WITHDRAW_ORDER_ID_RE.fullmatch(
        value
    ):
        raise TreasuryWithdrawalExecutionError(
            "Generated Gate withdraw_order_id "
            "is invalid"
        )

    return value


def build_gate_withdrawal_payload(
    request: dict[str, Any],
) -> dict[str, str]:
    request_id = str(
        request.get("request_id") or ""
    ).strip()

    currency = str(
        request.get("currency") or ""
    ).strip().upper()

    chain = str(
        request.get("chain") or ""
    ).strip()

    address = str(
        request.get("address") or ""
    ).strip()

    memo = str(
        request.get("memo") or ""
    )

    if not currency:
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal currency is missing"
        )

    if not chain:
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal chain is missing"
        )

    if not address:
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal address is missing"
        )

    return {
        "withdraw_order_id": (
            gate_withdraw_order_id(
                request_id
            )
        ),
        "currency": currency,
        "address": address,
        "amount": _decimal_text(
            request.get("amount")
        ),
        "memo": memo,
        "chain": chain,
    }


def withdrawal_execution_confirmation_text(
    request: dict[str, Any],
) -> str:
    request_id = str(
        request.get("request_id") or ""
    ).strip()

    owner = str(
        request.get("owner_account_id") or ""
    ).strip().lower()

    destination_id = str(
        request.get("destination_id") or ""
    ).strip()

    currency = str(
        request.get("currency") or ""
    ).strip().upper()

    chain = str(
        request.get("chain") or ""
    ).strip()

    amount = _decimal_text(
        request.get("amount")
    )

    if (
        not request_id
        or not owner
        or not destination_id
        or not currency
        or not chain
    ):
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal confirmation cannot be built "
            "from incomplete request data"
        )

    ref = hashlib.sha256(
        request_id.encode("utf-8")
    ).hexdigest()[:16]

    result = (
        "LIVE WITHDRAWAL "
        f"{owner} {currency} {amount} "
        f"{chain} TO {destination_id} "
        f"REF {ref}"
    )

    if len(result) > 255:
        raise TreasuryWithdrawalExecutionError(
            "Withdrawal confirmation exceeds "
            "255 characters"
        )

    return result


def _positive_block_number(
    value: Any,
) -> bool:
    try:
        return int(str(value or "0").strip()) > 0
    except (TypeError, ValueError):
        return False


def classify_withdrawal_status(
    status: Any,
    *,
    block_number: Any = None,
) -> WithdrawalStatusDecision:
    normalized = str(
        status or ""
    ).strip().upper()

    if normalized == "DONE":
        if _positive_block_number(
            block_number
        ):
            return WithdrawalStatusDecision(
                gate_status=normalized,
                request_status=(
                    "withdrawal_done_unsettled"
                ),
                outcome="success",
                confidence="definitive",
                terminal=True,
                success=True,
                requires_reconciliation=False,
                summary=(
                    "Gate confirmed the external "
                    "withdrawal completed on-chain."
                ),
            )

        return WithdrawalStatusDecision(
            gate_status=normalized,
            request_status=(
                "withdrawal_reconciling"
            ),
            outcome="pending",
            confidence="pending",
            terminal=False,
            success=False,
            requires_reconciliation=True,
            summary=(
                "Gate reports DONE but no positive "
                "block number proves on-chain "
                "completion yet."
            ),
        )

    if normalized in {
        "CANCEL",
        "REJECT",
        "INVALID",
    }:
        return WithdrawalStatusDecision(
            gate_status=normalized,
            request_status="withdrawal_failed",
            outcome="failed",
            confidence="definitive",
            terminal=True,
            success=False,
            requires_reconciliation=False,
            summary=(
                "Gate confirmed the external "
                "withdrawal did not complete."
            ),
        )

    # FAIL is explicitly non-terminal in Gate's
    # withdrawal history semantics.
    if normalized in {
        "REQUEST",
        "MANUAL",
        "BCODE",
        "EXTPEND",
        "FAIL",
        "VERIFY",
        "PROCES",
        "PEND",
        "DMOVE",
        "REVIEW",
        "CANCELPEND",
        "FVERIFY",
        "LOCKED",
    }:
        return WithdrawalStatusDecision(
            gate_status=normalized,
            request_status=(
                "withdrawal_reconciling"
            ),
            outcome="pending",
            confidence="pending",
            terminal=False,
            success=False,
            requires_reconciliation=True,
            summary=(
                "Gate withdrawal remains "
                "non-definitive."
            ),
        )

    return WithdrawalStatusDecision(
        gate_status=normalized,
        request_status="withdrawal_reconciling",
        outcome="inconclusive",
        confidence="inconclusive",
        terminal=False,
        success=False,
        requires_reconciliation=True,
        summary=(
            "Gate returned an unknown or empty "
            "withdrawal status."
        ),
    )

def _flatten_records(
    value: Any,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        # A ledger/withdrawal record is identifiable by
        # one of these record-specific fields.
        if (
            "withdraw_order_id" in value
            or "withdraw_id" in value
            or "status" in value
            and "currency" in value
        ):
            return [value]

        result: list[dict[str, Any]] = []

        for child in value.values():
            if isinstance(
                child,
                (dict, list),
            ):
                result.extend(
                    _flatten_records(child)
                )

        return result

    if isinstance(value, list):
        result = []

        for child in value:
            result.extend(
                _flatten_records(child)
            )

        return result

    return []


def select_withdrawal_record(
    raw: Any,
    *,
    withdraw_order_id: str,
) -> dict[str, Any] | None:
    expected = str(
        withdraw_order_id or ""
    ).strip()

    if not WITHDRAW_ORDER_ID_RE.fullmatch(
        expected
    ):
        raise TreasuryWithdrawalExecutionError(
            "Invalid Gate withdraw_order_id"
        )

    matches = [
        item
        for item in _flatten_records(raw)
        if str(
            item.get("withdraw_order_id")
            or ""
        ).strip()
        == expected
    ]

    if not matches:
        return None

    if len(matches) != 1:
        raise TreasuryWithdrawalExecutionError(
            "Gate returned multiple withdrawal "
            "records for one withdraw_order_id"
        )

    return matches[0]
