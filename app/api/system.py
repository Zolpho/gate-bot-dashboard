from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..collector import collector
from ..config import get_settings
from ..gate_client import GateAPIError, GateClient

router = APIRouter(prefix="/api", tags=["system"])
settings = get_settings()


@router.get("/health")
def health():  # type: ignore[no-untyped-def]
    return {
        "status": "ok",
        "mode": "demo" if settings.demo_mode else "live",
        "gate_configured": settings.gate_configured,
        "collector_running": collector.running,
        "poll_seconds": settings.poll_seconds,
        "allow_bot_stop": settings.allow_bot_stop,
        "snapshot_retention_days": settings.snapshot_retention_days,
    }


@router.get("/account")
async def account_snapshot():  # type: ignore[no-untyped-def]
    if settings.demo_mode:
        return {"mode": "demo", "message": "Account endpoints are not called in demo mode."}
    if not settings.gate_configured:
        raise HTTPException(status_code=503, detail="Gate API credentials are not configured")
    async with GateClient(settings) as client:
        return await client.account_snapshot()


@router.get("/recommendations")
async def recommendations(
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
        return {"mode": "demo", "items": []}
    if not settings.gate_configured:
        raise HTTPException(status_code=503, detail="Gate API credentials are not configured")
    try:
        async with GateClient(settings) as client:
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
    return response.raw
