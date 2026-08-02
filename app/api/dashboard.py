from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..collector import collector
from ..db import get_db
from ..metrics import overview, portfolio_history, sync_to_dict
from ..models import SyncRun
from ..security import DashboardUser, require_user, resolve_authorized_account

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/overview")
def get_overview(
    account_id: str | None = None,
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    return overview(db, account_id=account_id.strip().lower() if account_id else None)


@router.get("/portfolio/history")
def get_portfolio_history(
    hours: int = Query(default=168, ge=1, le=24 * 365),
    account_id: str | None = None,
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    normalized_id = account_id.strip().lower() if account_id else None
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return {
        "hours": hours,
        "account_id": normalized_id,
        "items": portfolio_history(db, since, account_id=normalized_id),
    }


@router.post("/sync")
async def sync_now(
    user: Annotated[DashboardUser, Depends(require_user)],
    account_id: str | None = None,
):  # type: ignore[no-untyped-def]
    authorized_account = resolve_authorized_account(user, account_id)
    result = await collector.sync(trigger="manual", account_id=authorized_account)
    result["authorized_user"] = user.username
    return result


@router.get("/sync-runs")
def list_sync_runs(
    limit: int = Query(default=20, ge=1, le=200),
    account_id: str | None = None,
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    stmt = (
        select(SyncRun)
        .options(selectinload(SyncRun.account))
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    )
    if account_id:
        stmt = stmt.where(SyncRun.account_id == account_id.strip().lower())
    runs = db.scalars(stmt).all()
    return {"items": [sync_to_dict(run) for run in runs]}
