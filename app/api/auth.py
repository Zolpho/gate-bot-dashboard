from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

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
