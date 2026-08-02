from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AlertEvent, Bot, BotSnapshot, GateAccount, SyncRun


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _sum(values: Iterable[Decimal | None]) -> Decimal:
    return sum((value for value in values if value is not None), Decimal("0"))


def _bot_profit(bot: Bot) -> Decimal | None:
    return bot.total_profit if bot.total_profit is not None else bot.pnl


def account_to_dict(
    account: GateAccount,
    bots: list[Bot] | None = None,
    *,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": account.id,
        "name": account.name,
        "account_type": account.account_type,
        "enabled": account.enabled,
        "configured": account.configured,
        "sync_status": account.sync_status,
        "last_sync_at": as_utc(account.last_sync_at).isoformat() if account.last_sync_at else None,
        "last_success_at": as_utc(account.last_success_at).isoformat() if account.last_success_at else None,
        "bot_count": account.bot_count,
        "updated_at": as_utc(account.updated_at).isoformat(),
    }
    if include_sensitive:
        result["gate_uid"] = account.gate_uid
        result["last_error"] = account.last_error

    if bots is not None:
        running = [bot for bot in bots if bot.status == "running"]
        invest = _sum(bot.invest_amount for bot in running)
        current = _sum(bot.current_value for bot in running)
        pnl = _sum(_bot_profit(bot) for bot in running)
        result["portfolio"] = {
            "tracked": len(bots),
            "running": len(running),
            "invest_amount": float(invest),
            "current_value": float(current),
            "pnl": float(pnl),
            "roi_pct": float(pnl / invest * Decimal("100")) if invest else None,
        }
    return result


def bot_to_dict(bot: Bot, *, include_raw: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    last_seen = as_utc(bot.last_seen_at)
    stale_seconds = int((now - last_seen).total_seconds()) if last_seen else None
    account_name = bot.account.name if bot.account is not None else bot.account_id
    result: dict[str, Any] = {
        "id": bot.id,
        "account_id": bot.account_id,
        "account_name": account_name,
        "strategy_id": bot.strategy_id,
        "strategy_type": bot.strategy_type,
        "strategy_name": bot.strategy_name,
        "market": bot.market,
        "status": bot.status,
        "source_status": bot.source_status,
        "invest_amount": decimal_to_float(bot.invest_amount),
        "pnl": decimal_to_float(bot.pnl),
        "pnl_rate": decimal_to_float(bot.pnl_rate),
        "total_profit": decimal_to_float(bot.total_profit),
        "profit_rate": decimal_to_float(bot.profit_rate),
        "grid_profit": decimal_to_float(bot.grid_profit),
        "floating_pnl": decimal_to_float(bot.floating_pnl),
        "realized_pnl": decimal_to_float(bot.realized_pnl),
        "current_value": decimal_to_float(bot.current_value),
        "arbitrage_count": bot.arbitrage_count,
        "grid_count": bot.grid_count,
        "finished_rounds": bot.finished_rounds,
        "runtime_seconds": bot.runtime_seconds,
        "price_range": bot.price_range,
        "price_floor": decimal_to_float(bot.price_floor),
        "avg_cost": decimal_to_float(bot.avg_cost),
        "take_profit_price": decimal_to_float(bot.take_profit_price),
        "estimated_liquidation_price": decimal_to_float(bot.estimated_liquidation_price),
        "maintenance_margin_ratio": decimal_to_float(bot.maintenance_margin_ratio),
        "position_side": bot.position_side,
        "position_amount": decimal_to_float(bot.position_amount),
        "quote_amount": decimal_to_float(bot.quote_amount),
        "entry_price": decimal_to_float(bot.entry_price),
        "position_value": decimal_to_float(bot.position_value),
        "margin": decimal_to_float(bot.margin),
        "stop_supported": bot.stop_supported,
        "created_at_gate": as_utc(bot.created_at_gate).isoformat() if bot.created_at_gate else None,
        "first_seen_at": as_utc(bot.first_seen_at).isoformat(),
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "stopped_at": as_utc(bot.stopped_at).isoformat() if bot.stopped_at else None,
        "updated_at": as_utc(bot.updated_at).isoformat(),
        "stale_seconds": stale_seconds,
    }
    if include_raw:
        detail = json_loads(bot.raw_detail_json, {})
        result["base_info"] = detail.get("base_info", {}) if isinstance(detail, dict) else {}
        result["metrics"] = detail.get("metrics", {}) if isinstance(detail, dict) else {}
        result["position"] = detail.get("position", {}) if isinstance(detail, dict) else {}
        result["raw_list"] = json_loads(bot.raw_list_json, {})
        result["raw_detail"] = detail
    return result


def snapshot_to_dict(snapshot: BotSnapshot) -> dict[str, Any]:
    return {
        "captured_at": as_utc(snapshot.captured_at).isoformat(),
        "status": snapshot.status,
        "invest_amount": decimal_to_float(snapshot.invest_amount),
        "pnl": decimal_to_float(snapshot.pnl),
        "pnl_rate": decimal_to_float(snapshot.pnl_rate),
        "total_profit": decimal_to_float(snapshot.total_profit),
        "profit_rate": decimal_to_float(snapshot.profit_rate),
        "grid_profit": decimal_to_float(snapshot.grid_profit),
        "floating_pnl": decimal_to_float(snapshot.floating_pnl),
        "realized_pnl": decimal_to_float(snapshot.realized_pnl),
        "current_value": decimal_to_float(snapshot.current_value),
        "position_value": decimal_to_float(snapshot.position_value),
        "liquidation_price": decimal_to_float(snapshot.liquidation_price),
    }


def sync_to_dict(run: SyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "account_id": run.account_id,
        "account_name": run.account.name if run.account else None,
        "started_at": as_utc(run.started_at).isoformat(),
        "finished_at": as_utc(run.finished_at).isoformat() if run.finished_at else None,
        "status": run.status,
        "trigger": run.trigger,
        "bot_count": run.bot_count,
        "detail_count": run.detail_count,
        "error": run.error,
        "summary": json_loads(run.raw_summary_json, {}),
    }


def calculate_drawdown(points: list[tuple[datetime, Decimal]]) -> dict[str, float | None]:
    if not points:
        return {"max_drawdown_pct": None, "current_drawdown_pct": None, "peak_value": None}
    peak = points[0][1]
    max_drawdown = Decimal("0")
    current_drawdown = Decimal("0")
    for _, value in points:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (peak - value) / peak * Decimal("100")
            max_drawdown = max(max_drawdown, drawdown)
            current_drawdown = drawdown
    return {
        "max_drawdown_pct": float(max_drawdown),
        "current_drawdown_pct": float(current_drawdown),
        "peak_value": float(peak),
    }


def overview(session: Session, account_id: str | None = None) -> dict[str, Any]:
    all_bots = list(session.scalars(select(Bot).order_by(Bot.pnl.desc().nullslast())))
    bots = [bot for bot in all_bots if not account_id or bot.account_id == account_id]
    running = [bot for bot in bots if bot.status == "running"]
    stopped = [bot for bot in bots if bot.status == "stopped"]
    paused = [bot for bot in bots if bot.status == "paused"]

    total_invest = _sum(bot.invest_amount for bot in running)
    total_value = _sum(bot.current_value for bot in running)
    total_pnl = _sum(_bot_profit(bot) for bot in running)
    total_grid_profit = _sum(bot.grid_profit for bot in running)
    total_floating = _sum(bot.floating_pnl for bot in running)
    roi = (total_pnl / total_invest * Decimal("100")) if total_invest else None

    sync_stmt = select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)
    if account_id:
        sync_stmt = sync_stmt.where(SyncRun.account_id == account_id)
    else:
        sync_stmt = sync_stmt.where(SyncRun.account_id.is_(None))
    latest_sync = session.scalar(sync_stmt)
    if latest_sync is None and not account_id:
        latest_sync = session.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))

    alert_stmt = select(func.count(AlertEvent.id)).where(AlertEvent.acknowledged_at.is_(None))
    if account_id:
        alert_stmt = alert_stmt.join(Bot, Bot.id == AlertEvent.bot_id).where(Bot.account_id == account_id)
    unacked_alerts = session.scalar(alert_stmt) or 0

    best = max(
        running,
        key=lambda bot: bot.profit_rate or bot.pnl_rate or Decimal("-Infinity"),
        default=None,
    )
    worst = min(
        running,
        key=lambda bot: bot.profit_rate or bot.pnl_rate or Decimal("Infinity"),
        default=None,
    )

    history_7d = portfolio_history(
        session,
        datetime.now(timezone.utc) - timedelta(days=7),
        account_id=account_id,
    )

    def period_change(hours: int) -> dict[str, float | None]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        candidates = [
            point
            for point in history_7d
            if datetime.fromisoformat(point["captured_at"]) >= cutoff
        ]
        if len(candidates) < 2:
            return {"pnl_change": None, "value_change": None, "value_change_pct": None}
        first, last = candidates[0], candidates[-1]
        value_change = last["current_value"] - first["current_value"]
        return {
            "pnl_change": last["pnl"] - first["pnl"],
            "value_change": value_change,
            "value_change_pct": (
                value_change / first["current_value"] * 100 if first["current_value"] else None
            ),
        }

    accounts = list(session.scalars(select(GateAccount).order_by(GateAccount.name.asc())))
    bots_by_account: dict[str, list[Bot]] = defaultdict(list)
    for bot in all_bots:
        bots_by_account[bot.account_id].append(bot)

    selected_account = next((item for item in accounts if item.id == account_id), None)
    return {
        "account_id": account_id,
        "selected_account": account_to_dict(selected_account, bots_by_account[account_id]) if selected_account else None,
        "totals": {
            "invest_amount": float(total_invest),
            "current_value": float(total_value),
            "pnl": float(total_pnl),
            "roi_pct": float(roi) if roi is not None else None,
            "grid_profit": float(total_grid_profit),
            "floating_pnl": float(total_floating),
        },
        "periods": {"24h": period_change(24), "7d": period_change(24 * 7)},
        "counts": {
            "all": len(bots),
            "running": len(running),
            "stopped": len(stopped),
            "paused": len(paused),
            "other": len(bots) - len(running) - len(stopped) - len(paused),
        },
        "best_bot": bot_to_dict(best) if best else None,
        "worst_bot": bot_to_dict(worst) if worst else None,
        "latest_sync": sync_to_dict(latest_sync) if latest_sync else None,
        "unacknowledged_alerts": unacked_alerts,
        "accounts": [account_to_dict(account, bots_by_account[account.id]) for account in accounts],
    }


def portfolio_history(
    session: Session,
    since: datetime,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        select(BotSnapshot, Bot)
        .join(Bot, Bot.id == BotSnapshot.bot_id)
        .where(BotSnapshot.captured_at >= since)
        .order_by(BotSnapshot.captured_at.asc(), BotSnapshot.id.asc())
    )
    if account_id:
        stmt = stmt.where(Bot.account_id == account_id)

    # Keep only the latest snapshot for each bot within each minute. This avoids
    # inflating portfolio totals when POLL_SECONDS is less than 60.
    latest_per_bot_minute: dict[tuple[str, int], BotSnapshot] = {}
    for snapshot, bot in session.execute(stmt).all():
        captured = as_utc(snapshot.captured_at)
        if captured is None:
            continue
        minute = captured.replace(second=0, microsecond=0).isoformat()
        latest_per_bot_minute[(minute, bot.id)] = snapshot

    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "invest_amount": Decimal("0"),
            "current_value": Decimal("0"),
            "pnl": Decimal("0"),
            "bots": set(),
        }
    )
    for (minute, bot_id), snapshot in latest_per_bot_minute.items():
        bucket = buckets[minute]
        bucket["bots"].add(bot_id)
        bucket["invest_amount"] += snapshot.invest_amount or Decimal("0")
        bucket["current_value"] += snapshot.current_value or Decimal("0")
        bucket["pnl"] += (
            snapshot.total_profit
            if snapshot.total_profit is not None
            else (snapshot.pnl or Decimal("0"))
        )

    result: list[dict[str, Any]] = []
    for timestamp, bucket in sorted(buckets.items()):
        invest = bucket["invest_amount"]
        pnl = bucket["pnl"]
        result.append(
            {
                "captured_at": timestamp,
                "invest_amount": float(invest),
                "current_value": float(bucket["current_value"]),
                "pnl": float(pnl),
                "roi_pct": float(pnl / invest * Decimal("100")) if invest else None,
                "bot_count": len(bucket["bots"]),
            }
        )
    return result
