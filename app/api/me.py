from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..accounts import AccountConfigError, get_gate_account
from ..balances import build_account_balance_payload
from ..config import Settings, get_settings
from ..db import get_db
from ..gate_client import GateAPIError, GateClient
from ..models import Bot, GateAccount
from ..security import DashboardUser, require_user, resolve_authorized_account

router = APIRouter(prefix="/api/me", tags=["private account"])

_balance_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_balance_locks: dict[str, asyncio.Lock] = {}


def _bot_summary(db: Session, account_id: str) -> dict[str, Any]:
    bots = list(db.scalars(select(Bot).where(Bot.account_id == account_id)))
    running = [bot for bot in bots if bot.status == "running"]
    invest = sum((bot.invest_amount or Decimal("0") for bot in running), Decimal("0"))
    current = sum((bot.current_value or Decimal("0") for bot in running), Decimal("0"))
    pnl = sum(
        (
            bot.total_profit
            if bot.total_profit is not None
            else (bot.pnl or Decimal("0"))
            for bot in running
        ),
        Decimal("0"),
    )
    return {
        "invest_amount": float(invest),
        "current_value": float(current),
        "pnl": float(pnl),
        "running_bots": len(running),
        "tracked_bots": len(bots),
    }


def _demo_balance(account_id: str, display_name: str, bot_summary: dict[str, Any], settings: Settings) -> dict[str, Any]:
    current_value = Decimal(str(bot_summary.get("current_value") or 0))
    available_usdt = Decimal("500")
    return build_account_balance_payload(
        account_id=account_id,
        display_name=display_name,
        total_balance={
            "total": {"amount": str(current_value + available_usdt), "currency": "USDT"},
            "details": {
                "spot": {"amount": str(available_usdt), "currency": "USDT"},
                "quant": {"amount": str(current_value), "currency": "USDT"},
            },
        },
        spot_accounts=[
            {"currency": "USDT", "available": str(available_usdt), "locked": "0"},
        ],
        spot_tickers=[],
        bot_summary=bot_summary,
        dust_usdt=Decimal(str(settings.balance_dust_usdt)),
        source="demo",
    )


async def _fetch_live_balance(
    *,
    account_id: str,
    display_name: str,
    bot_summary: dict[str, Any],
    settings: Settings,
    force_refresh: bool,
) -> dict[str, Any]:
    now = time.monotonic()
    cached = _balance_cache.get(account_id)
    if (
        not force_refresh
        and cached is not None
        and now - cached[0] < settings.balance_cache_seconds
    ):
        result = dict(cached[1])
        result["cache"] = {"hit": True, "ttl_seconds": settings.balance_cache_seconds}
        return result

    lock = _balance_locks.setdefault(account_id, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _balance_cache.get(account_id)
        if (
            not force_refresh
            and cached is not None
            and now - cached[0] < settings.balance_cache_seconds
        ):
            result = dict(cached[1])
            result["cache"] = {"hit": True, "ttl_seconds": settings.balance_cache_seconds}
            return result

        try:
            account = get_gate_account(account_id)
        except AccountConfigError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if account is None or not account.enabled or not account.configured:
            raise HTTPException(
                status_code=503,
                detail=f"Gate credentials are not configured for account {account_id}",
            )

        try:
            async with GateClient(settings, account) as client:
                total_response, spot_response, ticker_response = await asyncio.gather(
                    client.get_total_balance("USDT"),
                    client.list_spot_accounts(),
                    client.list_spot_tickers(),
                )
        except (GateAPIError, AccountConfigError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        payload = build_account_balance_payload(
            account_id=account_id,
            display_name=display_name,
            total_balance=total_response.data,
            spot_accounts=spot_response.data,
            spot_tickers=ticker_response.data,
            bot_summary=bot_summary,
            dust_usdt=Decimal(str(settings.balance_dust_usdt)),
            source="gate",
        )
        payload["cache"] = {"hit": False, "ttl_seconds": settings.balance_cache_seconds}
        _balance_cache[account_id] = (time.monotonic(), payload)
        return payload


@router.get("/balance")
async def my_balance(
    user: Annotated[DashboardUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    account_id: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    selected_account_id = resolve_authorized_account(user, account_id)
    if selected_account_id is None:
        raise HTTPException(
            status_code=400,
            detail="Select one account before loading a private balance",
        )

    account_row = db.get(GateAccount, selected_account_id)
    display_name = account_row.name if account_row is not None else selected_account_id
    bot_summary = _bot_summary(db, selected_account_id)

    if settings.demo_mode:
        payload = _demo_balance(selected_account_id, display_name, bot_summary, settings)
        payload["authorized_user"] = user.safe_dict()
        payload["cache"] = {"hit": False, "ttl_seconds": 0}
        return payload

    payload = await _fetch_live_balance(
        account_id=selected_account_id,
        display_name=display_name,
        bot_summary=bot_summary,
        settings=settings,
        force_refresh=refresh,
    )
    payload["authorized_user"] = user.safe_dict()
    return payload
