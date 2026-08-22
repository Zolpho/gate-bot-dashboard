from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..accounts import AccountConfigError
from ..bot_control import (
    BotControlConfigError,
    get_bot_control_account,
)
from ..config import get_settings
from ..db import get_db, session_scope
from ..gate_client import GateAPIError, GateClient
from ..metrics import bot_to_dict, calculate_drawdown, snapshot_to_dict
from ..models import Bot, BotArchive, BotSnapshot, GateAccount
from ..security import DashboardUser, require_account_access, require_user

router = APIRouter(prefix="/api/bots", tags=["bots"])
settings = get_settings()


class StopRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)


@router.get("")
def list_bots(
    account_id: str | None = None,
    status: str | None = None,
    strategy_type: str | None = None,
    market: str | None = None,
    search: str | None = None,
    sort: Literal["pnl", "roi", "name", "market", "updated"] = "pnl",
    direction: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    stmt = select(Bot).options(
        selectinload(Bot.account),
        selectinload(Bot.archive),
    )
    if account_id:
        stmt = stmt.where(Bot.account_id == account_id.strip().lower())
    if status:
        stmt = stmt.where(Bot.status == status)
    if strategy_type:
        stmt = stmt.where(Bot.strategy_type == strategy_type)
    if market:
        stmt = stmt.where(Bot.market == market)
    if search:
        term = f"%{search}%"
        stmt = stmt.join(GateAccount, GateAccount.id == Bot.account_id).where(
            or_(
                Bot.strategy_name.ilike(term),
                Bot.market.ilike(term),
                Bot.strategy_id.ilike(term),
                Bot.account_id.ilike(term),
                GateAccount.name.ilike(term),
            )
        )
    columns = {
        "pnl": Bot.total_profit,
        "roi": Bot.profit_rate,
        "name": Bot.strategy_name,
        "market": Bot.market,
        "updated": Bot.updated_at,
    }
    column = columns[sort]
    stmt = stmt.order_by(
        column.asc().nullslast() if direction == "asc" else column.desc().nullslast()
    )
    bots = db.scalars(stmt).all()

    filter_stmt = select(Bot)
    if account_id:
        filter_stmt = filter_stmt.where(Bot.account_id == account_id.strip().lower())
    filter_bots = db.scalars(filter_stmt).all()
    types = sorted({bot.strategy_type for bot in filter_bots})
    markets = sorted({bot.market for bot in filter_bots if bot.market})
    accounts = db.scalars(select(GateAccount).order_by(GateAccount.name.asc())).all()
    return {
        "items": [bot_to_dict(bot) for bot in bots],
        "filters": {
            "strategy_types": types,
            "markets": markets,
            "accounts": [{"id": account.id, "name": account.name} for account in accounts],
        },
    }


@router.get("/{bot_id}")
def get_bot(bot_id: int, db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    bot = db.scalar(
        select(Bot).options(
            selectinload(Bot.account),
            selectinload(Bot.archive),
        ).where(Bot.id == bot_id)
    )
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    points = db.scalars(
        select(BotSnapshot)
        .where(BotSnapshot.bot_id == bot.id)
        .order_by(BotSnapshot.captured_at.asc())
    ).all()
    drawdown_points = [
        (snapshot.captured_at, snapshot.current_value)
        for snapshot in points
        if snapshot.current_value is not None
    ]
    return {
        "bot": bot_to_dict(bot, include_raw=False),
        "analytics": calculate_drawdown(drawdown_points),
        "raw_data_requires_auth": True,
    }


@router.get("/{bot_id}/raw")
def get_bot_raw(
    bot_id: int,
    user: Annotated[DashboardUser, Depends(require_user)],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    bot = db.scalar(
        select(Bot).options(
            selectinload(Bot.account),
            selectinload(Bot.archive),
        ).where(Bot.id == bot_id)
    )
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    require_account_access(user, bot.account_id)
    return {
        "bot": bot_to_dict(bot, include_raw=True),
        "authorization": user.safe_dict(),
    }


def _archive_bot_or_404(
    db: Session,
    bot_id: int,
) -> Bot:
    bot = db.scalar(
        select(Bot)
        .options(
            selectinload(Bot.account),
            selectinload(Bot.archive),
        )
        .where(
            Bot.id == bot_id
        )
    )

    if not bot:
        raise HTTPException(
            status_code=404,
            detail="Bot not found",
        )

    return bot


@router.post("/{bot_id}/archive")
def archive_bot(
    bot_id: int,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    """
    Archive a stopped bot in local dashboard state only.

    This route never calls Gate and never modifies the
    canonical bot status.
    """

    bot = _archive_bot_or_404(
        db,
        bot_id,
    )

    require_account_access(
        user,
        bot.account_id,
    )

    if (
        str(
            bot.status or ""
        ).strip().lower()
        != "stopped"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Only stopped bots can be archived."
            ),
        )

    if bot.archive is None:
        bot.archive = BotArchive(
            bot_id=bot.id,
            account_id=bot.account_id,
            archived_at=datetime.now(
                timezone.utc
            ),
            archived_by=user.username,
        )

        db.add(
            bot.archive
        )

        db.flush()

    return {
        "status": "archived",
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "gate_write_performed": False,
        "bot": bot_to_dict(
            bot,
            include_raw=False,
        ),
    }


@router.post("/{bot_id}/restore")
def restore_bot(
    bot_id: int,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    """
    Restore a locally archived bot.

    Restore is account-authorized but intentionally does
    not depend on Gate status.
    """

    bot = _archive_bot_or_404(
        db,
        bot_id,
    )

    require_account_access(
        user,
        bot.account_id,
    )

    archive = bot.archive

    if archive is not None:
        db.delete(
            archive
        )

        db.flush()

    return {
        "status": "restored",
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "gate_write_performed": False,
    }


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
    points = [
        (snapshot.captured_at, snapshot.current_value)
        for snapshot in snapshots
        if snapshot.current_value is not None
    ]
    return {
        "hours": hours,
        "items": [snapshot_to_dict(snapshot) for snapshot in snapshots],
        "analytics": calculate_drawdown(points),
    }


@router.post("/{bot_id}/stop")
async def stop_bot(
    bot_id: int,
    request: StopRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    raise HTTPException(
        status_code=410,
        detail=(
            "Legacy Stop endpoint is disabled. "
            "Use the audited Bot Control Stop workflow."
        ),
    )

