from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collector import collector
from ..db import get_db
from ..metrics import overview, portfolio_history, sync_to_dict
from ..models import SyncRun

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    return overview(db)


@router.get("/portfolio/history")
def get_portfolio_history(
    hours: int = Query(default=168, ge=1, le=24 * 365),
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return {"hours": hours, "items": portfolio_history(db, since)}


@router.post("/sync")
async def sync_now():  # type: ignore[no-untyped-def]
    return await collector.sync(trigger="manual")


@router.get("/sync-runs")
def list_sync_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    runs = db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit)).all()
    return {"items": [sync_to_dict(run) for run in runs]}
