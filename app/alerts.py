from __future__ import annotations

import operator as operator_module
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import AlertEvent, AlertRule, Bot, BotSnapshot

OPERATORS: dict[str, Callable[[Decimal, Decimal], bool]] = {
    ">": operator_module.gt,
    ">=": operator_module.ge,
    "<": operator_module.lt,
    "<=": operator_module.le,
    "==": operator_module.eq,
    "!=": operator_module.ne,
}

METRIC_LABELS = {
    "pnl": "PnL",
    "pnl_rate": "ROI",
    "drawdown_pct": "drawdown",
    "floating_pnl": "floating PnL",
    "current_value": "current value",
    "liquidation_distance_pct": "liquidation distance",
    "stale_minutes": "data age",
}


def seed_default_rules(session: Session, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if session.scalar(select(AlertRule.id).limit(1)) is not None:
        return
    session.add_all(
        [
            AlertRule(
                name="Bot drawdown above limit",
                metric="drawdown_pct",
                operator=">=",
                threshold=Decimal(str(settings.default_drawdown_alert_pct)),
                cooldown_seconds=settings.alert_cooldown_seconds,
            ),
            AlertRule(
                name="Bot loss below limit",
                metric="pnl",
                operator="<=",
                threshold=Decimal(str(-abs(settings.default_loss_alert_usdt))),
                cooldown_seconds=settings.alert_cooldown_seconds,
            ),
            AlertRule(
                name="Futures liquidation distance low",
                metric="liquidation_distance_pct",
                operator="<=",
                threshold=Decimal(str(settings.default_liquidation_distance_pct)),
                cooldown_seconds=settings.alert_cooldown_seconds,
            ),
            AlertRule(
                name="Bot data is stale",
                metric="stale_minutes",
                operator=">=",
                threshold=Decimal(str(settings.stale_after_minutes)),
                cooldown_seconds=settings.alert_cooldown_seconds,
            ),
        ]
    )


def _bot_metric(session: Session, bot: Bot, metric: str, now: datetime) -> Decimal | None:
    if metric == "pnl":
        return bot.total_profit if bot.total_profit is not None else bot.pnl
    if metric == "pnl_rate":
        return bot.profit_rate if bot.profit_rate is not None else bot.pnl_rate
    if metric == "floating_pnl":
        return bot.floating_pnl
    if metric == "current_value":
        return bot.current_value
    if metric == "stale_minutes":
        seen = bot.last_seen_at
        if seen is None:
            return None
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        return Decimal(str(max(0, (now - seen).total_seconds() / 60)))
    if metric == "liquidation_distance_pct":
        if not bot.entry_price or not bot.estimated_liquidation_price or bot.entry_price == 0:
            return None
        return abs(bot.entry_price - bot.estimated_liquidation_price) / abs(bot.entry_price) * Decimal("100")
    if metric == "drawdown_pct":
        if bot.current_value is None:
            return None
        peak = session.scalar(
            select(BotSnapshot.current_value)
            .where(BotSnapshot.bot_id == bot.id, BotSnapshot.current_value.is_not(None))
            .order_by(BotSnapshot.current_value.desc())
            .limit(1)
        )
        if peak is None or peak <= 0:
            return Decimal("0")
        return max(Decimal("0"), (peak - bot.current_value) / peak * Decimal("100"))
    return None


def evaluate_alerts(session: Session, *, now: datetime | None = None) -> list[AlertEvent]:
    now = now or datetime.now(timezone.utc)
    rules = list(session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))))
    bots = list(session.scalars(select(Bot)))
    created: list[AlertEvent] = []

    for rule in rules:
        comparator = OPERATORS.get(rule.operator)
        if comparator is None:
            continue
        candidates = [bot for bot in bots if rule.bot_id is None or bot.id == rule.bot_id]
        for bot in candidates:
            value = _bot_metric(session, bot, rule.metric, now)
            if value is None or not comparator(value, rule.threshold):
                continue
            cutoff = now - timedelta(seconds=max(0, rule.cooldown_seconds))
            recent = session.scalar(
                select(AlertEvent.id)
                .where(
                    AlertEvent.rule_id == rule.id,
                    AlertEvent.bot_id == bot.id,
                    AlertEvent.triggered_at >= cutoff,
                )
                .limit(1)
            )
            if recent is not None:
                continue
            suffix = "%" if rule.metric.endswith("_pct") or rule.metric in {"pnl_rate", "stale_minutes"} else " USDT"
            if rule.metric == "stale_minutes":
                suffix = " min"
            label = METRIC_LABELS.get(rule.metric, rule.metric)
            event = AlertEvent(
                rule_id=rule.id,
                bot_id=bot.id,
                triggered_at=now,
                metric_value=value,
                message=(
                    f"{bot.strategy_name or bot.strategy_id} ({bot.market}) {label} "
                    f"is {value:.4f}{suffix}; rule {rule.operator} {rule.threshold}."
                ),
            )
            session.add(event)
            created.append(event)
    return created
