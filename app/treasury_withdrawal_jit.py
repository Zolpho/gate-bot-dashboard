from __future__ import annotations

import hashlib
from typing import Any

from .treasury_transfer import (
    TreasuryTransferValidationError,
    as_decimal,
    validate_transfer_amount,
)


class TreasuryWithdrawalJitPlanError(
    RuntimeError
):
    pass


def withdrawal_jit_transfer_request_id(
    withdrawal_request_id: str,
) -> str:
    """
    Stable local child request ID.

    This does NOT create a Treasury transfer request and
    does NOT perform a Gate operation.
    """
    normalized = str(
        withdrawal_request_id or ""
    ).strip()

    if not normalized:
        raise TreasuryWithdrawalJitPlanError(
            "Withdrawal request ID is required "
            "for JIT linkage"
        )

    digest = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()

    return (
        "withdrawal-jit-"
        + digest
    )


def withdrawal_jit_preparation_confirmation_text(
    request_id: str,
) -> str:
    return (
        "PREPARE WITHDRAWAL JIT "
        + request_id
    )


def build_withdrawal_jit_plan(
    *,
    request: dict[str, Any],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a read-only JIT preview from the CURRENT
    withdrawal preflight.

    The amount is deliberately a preview. A later live
    execution phase MUST calculate it again from another
    fresh preflight immediately before any Gate write.
    """
    funding = preflight.get("funding")

    if not isinstance(funding, dict):
        raise TreasuryWithdrawalJitPlanError(
            "Current withdrawal preflight has no "
            "valid funding snapshot"
        )

    jit_required = funding.get(
        "jit_required"
    )

    if not isinstance(jit_required, bool):
        raise TreasuryWithdrawalJitPlanError(
            "Current withdrawal preflight has no "
            "valid JIT-required flag"
        )

    jit_amount = as_decimal(
        funding.get(
            "minimum_jit_transfer"
        )
    )

    if (
        jit_amount is None
        or jit_amount < 0
    ):
        raise TreasuryWithdrawalJitPlanError(
            "Current withdrawal preflight has no "
            "valid minimum JIT transfer amount"
        )

    source_account_id = str(
        request.get(
            "owner_account_id"
        )
        or ""
    ).strip().lower()

    custody_account_id = str(
        request.get(
            "custody_account_id"
        )
        or ""
    ).strip().lower()

    currency = str(
        request.get("currency")
        or ""
    ).strip().upper()

    if not source_account_id:
        raise TreasuryWithdrawalJitPlanError(
            "Withdrawal economic owner is missing"
        )

    if not custody_account_id:
        raise TreasuryWithdrawalJitPlanError(
            "Withdrawal custody account is missing"
        )

    if not currency:
        raise TreasuryWithdrawalJitPlanError(
            "Withdrawal currency is missing"
        )

    child_request_id = None

    if jit_required:
        if (
            source_account_id
            == custody_account_id
        ):
            raise TreasuryWithdrawalJitPlanError(
                "Main-account withdrawal cannot require "
                "a subaccount-to-main JIT transfer"
            )

        if jit_amount <= 0:
            raise TreasuryWithdrawalJitPlanError(
                "JIT-required withdrawal must have a "
                "positive minimum JIT transfer amount"
            )

        try:
            validate_transfer_amount(
                jit_amount
            )

        except TreasuryTransferValidationError as exc:
            raise TreasuryWithdrawalJitPlanError(
                "Current JIT amount is not compatible "
                "with the Gate internal-transfer amount "
                f"rules: {exc}"
            ) from exc

        child_request_id = (
            withdrawal_jit_transfer_request_id(
                str(request["request_id"])
            )
        )

    elif jit_amount != 0:
        raise TreasuryWithdrawalJitPlanError(
            "Withdrawal preflight says JIT is not "
            "required but minimum JIT amount is non-zero"
        )

    return {
        "jit_required": jit_required,
        "jit_amount_preview": format(
            jit_amount,
            "f",
        ),
        "jit_transfer_request_id": (
            child_request_id
        ),
        "source_account_id": (
            source_account_id
        ),
        "custody_account_id": (
            custody_account_id
        ),
        "currency": currency,
        "derived_from_fresh_preflight": True,
        "amount_is_execution_authority": False,
        "gate_write_performed": False,
        "transfer_audit_created": False,
    }


def _compact_jit_amount(
    value: Any,
) -> str:
    amount = as_decimal(value)

    if amount is None:
        raise TreasuryWithdrawalJitPlanError(
            "JIT amount could not be parsed"
        )

    text = format(amount, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def withdrawal_jit_execution_confirmation_text(
    *,
    request: dict[str, Any],
    plan: dict[str, Any],
) -> str:
    """
    Bind the money-moving confirmation to the freshly
    calculated source/currency/amount/custody intent.

    The short REF is derived from the immutable withdrawal
    request ID while keeping the complete confirmation below
    the API request field's 255-character ceiling.
    """
    request_id = str(
        request.get("request_id") or ""
    ).strip()

    if not request_id:
        raise TreasuryWithdrawalJitPlanError(
            "Withdrawal request ID is missing"
        )

    source = str(
        plan.get("source_account_id") or ""
    ).strip().lower()

    custody = str(
        plan.get("custody_account_id") or ""
    ).strip().lower()

    currency = str(
        plan.get("currency") or ""
    ).strip().upper()

    amount = _compact_jit_amount(
        plan.get("jit_amount_preview")
    )

    if not source or not custody or not currency:
        raise TreasuryWithdrawalJitPlanError(
            "JIT execution intent is incomplete"
        )

    ref = hashlib.sha256(
        request_id.encode("utf-8")
    ).hexdigest()[:16]

    prefix = (
        "LIVE WITHDRAWAL JIT"
        if plan.get("jit_required")
        else "READY WITHDRAWAL NO-JIT"
    )

    return " ".join(
        (
            prefix,
            source,
            currency,
            amount,
            "TO",
            custody,
            "REF",
            ref,
        )
    )


def classify_jit_transfer_status(
    status: Any,
) -> dict[str, Any]:
    """
    Map the child internal-transfer lifecycle onto the
    parent withdrawal lifecycle.

    Anything not definitively successful or definitively
    failed stays reconciliation-required and keeps the
    withdrawal custody lock.
    """
    normalized = str(
        status or ""
    ).strip().lower()

    if normalized == "success":
        return {
            "withdrawal_status": "jit_ready",
            "terminal": False,
            "release_withdrawal_lock": False,
            "requires_reconciliation": False,
            "action": "jit_ready",
        }

    if normalized in {
        "failed",
        "rejected",
        "blocked",
        "preflight_failed",
    }:
        return {
            "withdrawal_status": "jit_failed",
            "terminal": True,
            "release_withdrawal_lock": True,
            "requires_reconciliation": False,
            "action": "jit_failed",
        }

    return {
        "withdrawal_status": "jit_reconciling",
        "terminal": False,
        "release_withdrawal_lock": False,
        "requires_reconciliation": True,
        "action": "jit_reconciling",
    }
