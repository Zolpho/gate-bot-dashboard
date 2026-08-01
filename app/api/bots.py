from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, session_scope
from ..gate_client import GateAPIError, GateClient
from ..metrics import bot_to_dict, calculate_drawdown, snapshot_to_dict
from ..models import Bot, BotSnapshot

router = APIRouter(prefix="/api/bots", tags=["bots"])
settings = get_settings()


class StopRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)


@router.get("")
def list_bots(
    status: str | None = None,
    strategy_type: str | None = None,
    market: str | None = None,
    search: str | None = None,
    sort: Literal["pnl", "roi", "name", "market", "updated"] = "pnl",
    direction: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    stmt = select(Bot)
    if status:
        stmt = stmt.where(Bot.status == status)
    if strategy_type:
        stmt = stmt.where(Bot.strategy_type == strategy_type)
    if market:
        stmt = stmt.where(Bot.market == market)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(Bot.strategy_name.ilike(term), Bot.market.ilike(term), Bot.strategy_id.ilike(term))
        )
    columns = {
        "pnl": Bot.total_profit,
        "roi": Bot.profit_rate,
        "name": Bot.strategy_name,
        "market": Bot.market,
        "updated": Bot.updated_at,
    }
    column = columns[sort]
    stmt = stmt.order_by(column.asc().nullslast() if direction == "asc" else column.desc().nullslast())
    bots = db.scalars(stmt).all()
    types = sorted({bot.strategy_type for bot in db.scalars(select(Bot)).all()})
    markets = sorted({bot.market for bot in db.scalars(select(Bot)).all() if bot.market})
    return {"items": [bot_to_dict(bot) for bot in bots], "filters": {"strategy_types": types, "markets": markets}}


@router.get("/{bot_id}")
def get_bot(bot_id: int, db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    bot = db.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    points = db.scalars(
        select(BotSnapshot).where(BotSnapshot.bot_id == bot.id).order_by(BotSnapshot.captured_at.asc())
    ).all()
    drawdown_points = [
        (snapshot.captured_at, snapshot.current_value)
        for snapshot in points
        if snapshot.current_value is not None
    ]
    return {"bot": bot_to_dict(bot, include_raw=True), "analytics": calculate_drawdown(drawdown_points)}


@router.get("/{bot_id}/history")
def get_bot_history(
    bot_id: int,
    hours: int = Query(default=168, ge=1, le=24 * 365),
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    if not db.get(Bot, bot_id):
        raise HTTPException(status_code=404, detail="Bot not found")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    snapshots = db.scalars(
        select(BotSnapshot)
        .where(BotSnapshot.bot_id == bot_id, BotSnapshot.captured_at >= since)
        .order_by(BotSnapshot.captured_at.asc())
    ).all()
    points = [(snapshot.captured_at, snapshot.current_value) for snapshot in snapshots if snapshot.current_value is not None]
    return {"hours": hours, "items": [snapshot_to_dict(snapshot) for snapshot in snapshots], "analytics": calculate_drawdown(points)}


@router.post("/{bot_id}/stop")
async def stop_bot(bot_id: int, request: StopRequest):  # type: ignore[no-untyped-def]
    if not settings.allow_bot_stop:
        raise HTTPException(status_code=403, detail="Bot stopping is disabled by ALLOW_BOT_STOP")
    if request.confirmation != settings.bot_stop_confirmation_text:
        raise HTTPException(status_code=400, detail="Invalid confirmation text")
    with session_scope() as db:
        bot = db.get(Bot, bot_id)
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        if not bot.stop_supported:
            raise HTTPException(status_code=409, detail="Gate reports that this bot does not support stop")
        strategy_id = bot.strategy_id
        strategy_type = bot.strategy_type
    try:
        async with GateClient(settings) as client:
            response = await client.stop_bot(strategy_id, strategy_type)
    except GateAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "submitted", "gate": response.raw}
