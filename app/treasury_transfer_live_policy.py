from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .config import Settings


@dataclass(frozen=True)
class TreasuryTransferPolicyDecision:
    allowed: bool
    reason: str
    message: str
    details: dict[str, Any]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "message": self.message,
            **self.details,
        }


def _decision(
    *,
    allowed: bool,
    reason: str,
    message: str,
    **details: Any,
) -> TreasuryTransferPolicyDecision:
    return TreasuryTransferPolicyDecision(
        allowed=allowed,
        reason=reason,
        message=message,
        details=details,
    )


def evaluate_live_transfer_policy(
    *,
    settings: Settings,
    source_account_id: str,
    currency: str,
    requested_amount: Decimal,
    available_amount: Decimal,
) -> TreasuryTransferPolicyDecision:
    source_account_id = (
        source_account_id.strip().lower()
    )

    currency = currency.strip().upper()

    if not settings.treasury_transfers_live_armed:
        return _decision(
            allowed=False,
            reason="live_not_armed",
            message=(
                "Live Treasury transfers are not armed."
            ),
            source_account_id=source_account_id,
            currency=currency,
        )

    if not (
        settings
        .treasury_transfers_live_account_allowed(
            source_account_id
        )
    ):
        return _decision(
            allowed=False,
            reason="source_account_not_live_enabled",
            message=(
                "This source account is not enabled "
                "for live Treasury transfers."
            ),
            source_account_id=source_account_id,
            currency=currency,
        )

    if requested_amount <= 0:
        return _decision(
            allowed=False,
            reason="invalid_amount",
            message=(
                "Transfer amount must be greater "
                "than zero."
            ),
            source_account_id=source_account_id,
            currency=currency,
        )

    # There is deliberately no static transfer ceiling here.
    # The hard economic ceiling is the freshly-read available
    # balance. Additional Treasury policy limits can be layered
    # on separately before wider rollout.
    if requested_amount > available_amount:
        return _decision(
            allowed=False,
            reason="insufficient_available_balance",
            message=(
                "Requested transfer exceeds the "
                "currently available balance."
            ),
            source_account_id=source_account_id,
            currency=currency,
            requested_amount=str(requested_amount),
            available_amount=str(available_amount),
        )

    return _decision(
        allowed=True,
        reason="allowed",
        message=(
            "Live Treasury transfer passed the "
            "execution safety policy."
        ),
        source_account_id=source_account_id,
        currency=currency,
        requested_amount=str(requested_amount),
        available_amount=str(available_amount),
    )
