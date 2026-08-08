from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from ..bot_control_attention import (
    build_attention_queue,
)
from ..security import (
    DashboardUser,
    require_user,
)


router = APIRouter(
    prefix="/api/bot-control",
    tags=["bot-control"],
)


@router.get("/attention")
def get_bot_control_attention(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):
    account_ids = (
        None
        if user.is_super_admin
        else set(user.account_ids)
    )

    return build_attention_queue(
        account_ids=account_ids,
        limit=limit,
    )
