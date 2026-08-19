from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..accounts import AccountConfigError, enabled_gate_accounts, get_gate_account, safe_account_config
from ..config import get_settings
from ..db import get_db
from ..gate_client import GateAPIError, GateClient
from ..metrics import account_to_dict
from ..models import Bot, GateAccount, SyncRun
from ..treasury import safe_treasury_config
from ..security import (
    DashboardUser,
    UserConfigError,
    require_account_access,
    require_user,
    safe_user_config,
)

router = APIRouter(prefix="/api", tags=["system"])
settings = get_settings()


def _account_config_or_http(account_id: str):  # type: ignore[no-untyped-def]
    account = get_gate_account(account_id)
    if account is None or not account.enabled or not account.configured:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown, disabled, or unconfigured Gate account: {account_id}",
        )
    return account


def _accounts_for_user(user: DashboardUser, requested_account_id: str | None):  # type: ignore[no-untyped-def]
    if requested_account_id:
        normalized = require_account_access(user, requested_account_id)
        return (_account_config_or_http(normalized),)

    accounts = enabled_gate_accounts()
    if user.is_super_admin:
        return accounts
    allowed = tuple(account for account in accounts if user.can_manage(account.id))
    if not allowed:
        raise HTTPException(status_code=403, detail="No configured Gate account is assigned to this user")
    return allowed


@router.get("/health")
def health(
    request: Request,
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    config_error = ""
    accounts: list[dict] = []  # type: ignore[type-arg]
    try:
        accounts = safe_account_config()
    except AccountConfigError as exc:
        config_error = str(exc)

    user_config_error = ""
    try:
        users = safe_user_config(settings)
    except UserConfigError as exc:
        user_config_error = str(exc)
        users = {
            "configured": False,
            "user_count": 0,
            "enabled_user_count": 0,
            "legacy_super_admin_enabled": settings.legacy_admin_enabled,
        }

    enabled_count = sum(
        1
        for account in accounts
        if account["enabled"] and account["configured"]
    )
    collection_task = getattr(
        request.app.state,
        "collection_task",
        None,
    )
    collector_running = bool(
        collection_task is not None
        and not collection_task.done()
    )

    latest_collection = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.account_id.is_(None),
            SyncRun.trigger.in_(("startup", "scheduler")),
        )
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )

    latest_success = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.account_id.is_(None),
            SyncRun.trigger.in_(("startup", "scheduler")),
            SyncRun.status.in_(("success", "partial")),
        )
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )

    def utc_value(value):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    last_collection_at = utc_value(
        latest_collection.finished_at or latest_collection.started_at
        if latest_collection
        else None
    )
    last_success_at = utc_value(
        latest_success.finished_at or latest_success.started_at
        if latest_success
        else None
    )

    collection_age_seconds = None
    if last_success_at is not None:
        collection_age_seconds = max(
            0,
            int(
                (
                    datetime.now(timezone.utc)
                    - last_success_at
                ).total_seconds()
            ),
        )

    # Five minutes is already the configured stale-data boundary here,
    # while three polling intervals protects installations using a larger
    # polling value.
    freshness_limit_seconds = max(
        settings.stale_after_minutes * 60,
        settings.poll_seconds * 3,
    )

    collector_fresh = (
        collection_age_seconds is None
        or collection_age_seconds
        <= freshness_limit_seconds
    )
    collector_healthy = (
        collector_running
        and collector_fresh
    )

    treasury = safe_treasury_config()
    treasury_config_error = str(
        treasury.get("config_error") or ""
    )

    degraded = bool(
        config_error
        or user_config_error
        or treasury_config_error
        or not collector_healthy
    )

    return {
        "status": "degraded" if degraded else "ok",
        "mode": "demo" if settings.demo_mode else "live",
        "gate_configured": settings.demo_mode or enabled_count > 0,
        "configured_account_count": len(accounts),
        "enabled_account_count": enabled_count,
        "account_config_error": config_error,
        "accounts": accounts,
        "collector_running": collector_running,
        "collector_healthy": collector_healthy,
        "last_collection_at": (
            last_collection_at.isoformat()
            if last_collection_at
            else None
        ),
        "last_collection_success_at": (
            last_success_at.isoformat()
            if last_success_at
            else None
        ),
        "collection_age_seconds": collection_age_seconds,
        "collection_freshness_limit_seconds": freshness_limit_seconds,
        "poll_seconds": settings.poll_seconds,
        "allow_bot_stop": settings.allow_bot_stop,
        "bot_stop_simulation": settings.bot_stop_simulation,
        "allow_bot_create": settings.allow_bot_create,
        "bot_create_simulation": settings.bot_create_simulation,

        # Treasury live-write flags report the actual runtime
        # arming state. Production normally remains disarmed.
        "treasury_configured": bool(
            treasury.get("configured")
        ),
        "treasury_main_account": (
            settings.treasury_main_account
        ),
        "treasury_phase": "T2B_TRANSFER_CONTROL",
        "treasury_transfer_simulation_enabled": True,
        "treasury_transfers_enabled": bool(
            treasury.get(
                "transfers_enabled",
                False,
            )
        ),
        "treasury_withdrawals_enabled": bool(
            settings.treasury_withdrawals_live_armed
        ),
        "treasury_config_error": treasury_config_error,

        "snapshot_retention_days": settings.snapshot_retention_days,
        "action_auth": users,
        "user_config_error": user_config_error,
        "cors_origins": settings.cors_origin_list,
    }


@router.get("/accounts")
def accounts(db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    rows = db.scalars(select(GateAccount).order_by(GateAccount.name.asc())).all()
    bots = db.scalars(select(Bot)).all()
    bots_by_account: dict[str, list[Bot]] = {}
    for bot in bots:
        bots_by_account.setdefault(bot.account_id, []).append(bot)
    return {
        "items": [account_to_dict(row, bots_by_account.get(row.id, [])) for row in rows]
    }


@router.get("/account")
async def account_snapshot(
    user: Annotated[DashboardUser, Depends(require_user)],
    account_id: str | None = None,
):  # type: ignore[no-untyped-def]
    if settings.demo_mode:
        return {
            "mode": "demo",
            "account_id": account_id,
            "authorized_user": user.safe_dict(),
            "message": "Account endpoints are not called in demo mode.",
        }

    try:
        selected = _accounts_for_user(user, account_id)
    except AccountConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def fetch(account):  # type: ignore[no-untyped-def]
        async with GateClient(settings, account) as client:
            snapshot = await client.account_snapshot()
        return {
            "account": account.safe_dict(include_uid=True),
            "snapshot": snapshot,
        }

    results = await asyncio.gather(*(fetch(account) for account in selected))
    return {
        "mode": "live",
        "account_count": len(results),
        "authorized_user": user.safe_dict(),
        "items": results,
    }


@router.get("/recommendations")
async def recommendations(
    user: Annotated[DashboardUser, Depends(require_user)],
    account_id: str | None = None,
    market: str | None = None,
    strategy_type: str | None = None,
    direction: str | None = None,
    invest_amount: str | None = None,
    scene: str | None = None,
    limit: int = Query(default=10, ge=1, le=10),
    max_drawdown_lte: str | None = None,
    backtest_apr_gte: str | None = None,
):  # type: ignore[no-untyped-def]
    if settings.demo_mode:
        return {
            "mode": "demo",
            "account_id": account_id,
            "authorized_user": user.safe_dict(),
            "items": [],
        }

    try:
        selected = _accounts_for_user(user, account_id)
        if len(selected) != 1:
            raise HTTPException(
                status_code=400,
                detail="Select one account before requesting recommendations",
            )
        account = selected[0]
    except AccountConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        async with GateClient(settings, account) as client:
            response = await client.get_strategy_recommendations(
                market=market,
                strategy_type=strategy_type,
                direction=direction,
                invest_amount=invest_amount,
                scene=scene,
                limit=limit,
                max_drawdown_lte=max_drawdown_lte,
                backtest_apr_gte=backtest_apr_gte,
            )
    except GateAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "account": account.safe_dict(include_uid=True),
        "authorized_user": user.safe_dict(),
        "gate": response.raw,
    }
