from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

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
    require_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)
    confirm_password: str = Field(min_length=12, max_length=1024)

    @model_validator(mode="after")
    def passwords_match(self) -> "PasswordChangeRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match")
        return self


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

    account_capabilities = [
        {
            "account_id": account.id,
            "account_name": account.name,
            "monitor": True,
            "bot_control": account.id in control_ids,
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
