from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..accounts import AccountConfigError, enabled_gate_accounts, get_gate_account, safe_account_config
from ..collector import collector
from ..config import get_settings
from ..db import get_db
from ..gate_client import GateAPIError, GateClient
from ..metrics import account_to_dict
from ..models import Bot, GateAccount

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


@router.get("/health")
def health(request: Request):  # type: ignore[no-untyped-def]
    config_error = ""
    accounts: list[dict] = []  # type: ignore[type-arg]
    try:
        accounts = safe_account_config()
    except AccountConfigError as exc:
        config_error = str(exc)
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

    return {
        "status": "ok" if not config_error else "degraded",
        "mode": "demo" if settings.demo_mode else "live",
        "gate_configured": settings.demo_mode or enabled_count > 0,
        "configured_account_count": len(accounts),
        "enabled_account_count": enabled_count,
        "account_config_error": config_error,
        "accounts": accounts,
        "collector_running": collector_running,
        "poll_seconds": settings.poll_seconds,
        "allow_bot_stop": settings.allow_bot_stop,
        "snapshot_retention_days": settings.snapshot_retention_days,
        "gate_accounts_file": str(settings.gate_accounts_file),
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
async def account_snapshot(account_id: str | None = None):  # type: ignore[no-untyped-def]
    if settings.demo_mode:
        return {
            "mode": "demo",
            "account_id": account_id,
            "message": "Account endpoints are not called in demo mode.",
        }

    try:
        if account_id:
            selected = (_account_config_or_http(account_id.strip().lower()),)
        else:
            selected = enabled_gate_accounts()
    except AccountConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not selected:
        raise HTTPException(status_code=503, detail="No enabled Gate accounts are configured")

    async def fetch(account):  # type: ignore[no-untyped-def]
        async with GateClient(settings, account) as client:
            snapshot = await client.account_snapshot()
        return {
            "account": account.safe_dict(),
            "snapshot": snapshot,
        }

    results = await asyncio.gather(*(fetch(account) for account in selected))
    return {
        "mode": "live",
        "account_count": len(results),
        "items": results,
    }


@router.get("/recommendations")
async def recommendations(
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
        return {"mode": "demo", "account_id": account_id, "items": []}

    try:
        if account_id:
            account = _account_config_or_http(account_id.strip().lower())
        else:
            accounts = enabled_gate_accounts()
            if not accounts:
                raise AccountConfigError("No enabled Gate accounts are configured")
            account = accounts[0]
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
        "account": account.safe_dict(),
        "gate": response.raw,
    }
