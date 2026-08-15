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
