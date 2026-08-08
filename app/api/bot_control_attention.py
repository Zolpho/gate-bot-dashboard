from __future__ import annotations

from typing import Annotated

from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from sqlalchemy import select

from ..db import session_scope
from ..models import (
    BotControlAttentionReview,
    BotControlOperationLock,
    BotControlRequest,
)

from ..bot_control_attention import (
    build_attention_queue,
)
from ..security import (
    DashboardUser,
    require_account_access,
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


@router.post("/attention/{request_id}/review")
def review_bot_control_attention(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    request_id = str(request_id or "").strip()

    if not request_id:
        raise HTTPException(
            status_code=400,
            detail="Request ID is required",
        )

    with session_scope() as db:
        request_row = db.scalar(
            select(BotControlRequest)
            .where(
                BotControlRequest.request_id
                == request_id
            )
            .limit(1)
        )

        if request_row is None:
            raise HTTPException(
                status_code=404,
                detail="Bot Control request not found",
            )

        require_account_access(
            user,
            request_row.account_id,
        )

        held_lock = db.scalar(
            select(BotControlOperationLock.id)
            .where(
                BotControlOperationLock
                .owner_request_id == request_id,
                BotControlOperationLock.state
                == "held",
            )
            .limit(1)
        )

        if held_lock is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This request still has a held "
                    "operation lock and cannot be "
                    "marked reviewed."
                ),
            )

        now = datetime.now(timezone.utc)

        review = db.scalar(
            select(BotControlAttentionReview)
            .where(
                BotControlAttentionReview
                .request_id == request_id
            )
            .limit(1)
        )

        if review is None:
            review = BotControlAttentionReview(
                request_id=request_id,
                account_id=request_row.account_id,
                reviewed_by=user.username,
                reviewed_at=now,
            )
            db.add(review)
        else:
            review.account_id = request_row.account_id
            review.reviewed_by = user.username
            review.reviewed_at = now

        db.flush()

        return {
            "status": "reviewed",
            "request_id": request_id,
            "account_id": request_row.account_id,
            "reviewed_by": user.username,
            "reviewed_at": now.isoformat(),
        }
