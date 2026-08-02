from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..security import DashboardUser, require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def current_user(user: Annotated[DashboardUser, Depends(require_user)]):  # type: ignore[no-untyped-def]
    return {"user": user.safe_dict()}
