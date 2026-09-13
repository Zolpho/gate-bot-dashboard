from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool, model_validator

from ..account_action_policy import (
    CAPABILITIES,
    AccountActionPolicyError,
    list_account_action_policies,
    list_account_action_policy_events,
    update_account_action_policy,
)
from ..accounts import AccountConfigError, enabled_gate_accounts
from ..bot_control import (
    BotControlConfigError,
    enabled_bot_control_accounts,
)
from ..config import Settings, get_settings
from ..security import (
    DashboardUser,
    PasswordChangeError,
    change_dashboard_user_password,
    require_super_admin,
    require_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)
    confirm_password: str = Field(min_length=12, max_length=1024)

    @model_validator(mode="after")
    def passwords_match(self) -> PasswordChangeRequest:
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match")
        return self


class AccountActionPolicyUpdateRequest(BaseModel):
    transfers_enabled: StrictBool | None = None
    withdrawals_enabled: StrictBool | None = None
    trading_enabled: StrictBool | None = None
    reason: str = Field(
        default="",
        max_length=1000,
    )

    @model_validator(mode="after")
    def at_least_one_capability(
        self,
    ) -> AccountActionPolicyUpdateRequest:
        if (
            self.transfers_enabled is None
            and self.withdrawals_enabled is None
            and self.trading_enabled is None
        ):
            raise ValueError(
                "At least one account policy capability "
                "must be provided"
            )

        return self


def _policy_account_or_404(
    account_id: str,
) -> str:
    normalized = str(
        account_id or ""
    ).strip().lower()

    if not normalized:
        raise HTTPException(
            status_code=404,
            detail="Gate account not found",
        )

    known = {
        item["account_id"]
        for item in list_account_action_policies()
    }

    if normalized not in known:
        raise HTTPException(
            status_code=404,
            detail="Gate account not found",
        )

    return normalized


@router.get("/me")
def current_user(user: Annotated[DashboardUser, Depends(require_user)]):  # type: ignore[no-untyped-def]
    return {"user": user.safe_dict()}


@router.get("/capabilities")
def capabilities(
    user: Annotated[DashboardUser, Depends(require_user)],
):  # type: ignore[no-untyped-def]
    try:
        monitor_accounts = enabled_gate_accounts()
        control_accounts = enabled_bot_control_accounts()
    except (AccountConfigError, BotControlConfigError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Credential configuration error: {exc}",
        ) from exc

    control_ids = {
        account.id
        for account in control_accounts
    }

    visible_accounts = [
        account
        for account in monitor_accounts
        if (
            user.is_super_admin
            or user.can_manage(account.id)
        )
    ]

    settings = get_settings()

    account_capabilities = [
        {
            "account_id": account.id,
            "account_name": account.name,
            "monitor": True,
            "bot_control": account.id in control_ids,
            "bot_control_live": bool(
                account.id in control_ids
                and settings.bot_control_live_armed
                and settings.bot_control_live_account_allowed(
                    account.id
                )
            ),
            "treasury": False,
        }
        for account in visible_accounts
    ]

    return {
        "user": user.safe_dict(),
        "modes": {
            "monitor": bool(account_capabilities),
            "bot_control": any(
                item["bot_control"]
                for item in account_capabilities
            ),
            "treasury": False,
        },
        "accounts": account_capabilities,
    }


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    user: Annotated[DashboardUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):  # type: ignore[no-untyped-def]
    try:
        change_dashboard_user_password(
            user,
            payload.current_password,
            payload.new_password,
            settings=settings,
        )
    except PasswordChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "changed",
        "message": "Password changed successfully",
        "user": user.safe_dict(),
    }

@router.get("/account-policies")
def account_action_policies(
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
):  # type: ignore[no-untyped-def]
    """
    Rootadmin read model for all Wallet-account policies.

    This is local authorization state only. Reading it never
    performs a Gate write.
    """

    return {
        "capabilities": list(CAPABILITIES),
        "items": list_account_action_policies(),
        "gate_write_performed": False,
    }


@router.get(
    "/account-policies/{account_id}/events"
)
def account_action_policy_history(
    account_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
    ),
):  # type: ignore[no-untyped-def]
    """
    Rootadmin-only immutable policy history.
    """

    normalized = _policy_account_or_404(
        account_id
    )

    return {
        "account_id": normalized,
        "items": (
            list_account_action_policy_events(
                normalized,
                limit=limit,
            )
        ),
        "limit": limit,
        "gate_write_performed": False,
    }


@router.patch(
    "/account-policies/{account_id}"
)
def change_account_action_policy(
    account_id: str,
    payload: AccountActionPolicyUpdateRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_super_admin),
    ],
):  # type: ignore[no-untyped-def]
    """
    Rootadmin-only local policy mutation.

    This changes durable dashboard authorization state only.
    It does not call Gate and does not itself enable any Gate
    write.
    """

    normalized = _policy_account_or_404(
        account_id
    )

    try:
        result = update_account_action_policy(
            normalized,
            username=user.username,
            transfers_enabled=(
                payload.transfers_enabled
            ),
            withdrawals_enabled=(
                payload.withdrawals_enabled
            ),
            trading_enabled=(
                payload.trading_enabled
            ),
            reason=payload.reason.strip(),
            metadata={
                "source": "rootadmin_policy_api",
                "auth_source": user.auth_source,
            },
        )
    except AccountActionPolicyError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "status": (
            "updated"
            if result["changed"]
            else "unchanged"
        ),
        **result,
        "gate_write_performed": False,
    }
