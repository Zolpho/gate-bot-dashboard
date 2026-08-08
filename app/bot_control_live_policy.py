from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .config import Settings


@dataclass(frozen=True)
class LivePolicyDecision:
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
) -> LivePolicyDecision:
    return LivePolicyDecision(
        allowed=allowed,
        reason=reason,
        message=message,
        details=details,
    )


def evaluate_live_account_policy(
    *,
    settings: Settings,
    account_id: str,
    action: str,
) -> LivePolicyDecision:
    if not settings.bot_control_live_armed:
        return _decision(
            allowed=False,
            reason="live_not_armed",
            message=(
                "Live Bot Control is not armed."
            ),
            account_id=account_id,
            action=action,
        )

    if not settings.bot_control_live_account_allowed(
        account_id
    ):
        return _decision(
            allowed=False,
            reason="account_not_live_enabled",
            message=(
                "This account is not enabled for "
                "live Bot Control."
            ),
            account_id=account_id,
            action=action,
        )

    return _decision(
        allowed=True,
        reason="allowed",
        message=(
            "Account passed the live execution policy."
        ),
        account_id=account_id,
        action=action,
    )


def evaluate_live_create_policy(
    *,
    settings: Settings,
    account_id: str,
    market: str,
    quote_currency: str,
    requested_investment: Decimal,
    available_quote: Decimal,
) -> LivePolicyDecision:
    account_decision = (
        evaluate_live_account_policy(
            settings=settings,
            account_id=account_id,
            action="spot_grid_create",
        )
    )

    if not account_decision.allowed:
        return account_decision

    if requested_investment <= 0:
        return _decision(
            allowed=False,
            reason="invalid_investment",
            message=(
                "Investment must be greater than zero."
            ),
            account_id=account_id,
            market=market,
            quote_currency=quote_currency,
        )

    # Permanent investment rule:
    #
    # There is deliberately NO static fiat/USDT cap
    # and NO fixed percentage cap.
    #
    # The maximum is the currently available balance
    # of the market's actual quote currency.
    if requested_investment > available_quote:
        return _decision(
            allowed=False,
            reason="insufficient_available_quote_balance",
            message=(
                "Requested investment exceeds the "
                "currently available quote-currency "
                "balance."
            ),
            account_id=account_id,
            market=market,
            quote_currency=quote_currency,
            requested_investment=str(
                requested_investment
            ),
            available_quote=str(
                available_quote
            ),
            maximum_investment=str(
                available_quote
            ),
        )

    return _decision(
        allowed=True,
        reason="allowed",
        message=(
            "Live Spot Grid request passed the "
            "execution safety policy."
        ),
        account_id=account_id,
        market=market,
        quote_currency=quote_currency,
        requested_investment=str(
            requested_investment
        ),
        available_quote=str(
            available_quote
        ),
        maximum_investment=str(
            available_quote
        ),
        market_restriction=False,
        static_investment_cap=False,
    )


def evaluate_live_stop_policy(
    *,
    settings: Settings,
    account_id: str,
    market: str | None,
    strategy_id: str,
) -> LivePolicyDecision:
    account_decision = (
        evaluate_live_account_policy(
            settings=settings,
            account_id=account_id,
            action="bot_stop",
        )
    )

    if not account_decision.allowed:
        return account_decision

    if not strategy_id:
        return _decision(
            allowed=False,
            reason="missing_strategy_id",
            message=(
                "Live Stop requires a strategy ID."
            ),
            account_id=account_id,
        )

    return _decision(
        allowed=True,
        reason="allowed",
        message=(
            "Live Bot Stop passed the execution "
            "safety policy."
        ),
        account_id=account_id,
        market=market,
        strategy_id=strategy_id,
    )
