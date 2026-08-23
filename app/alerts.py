from __future__ import annotations

import operator as operator_module
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import (
    AlertEvent,
    AlertIncident,
    AlertRule,
    Bot,
    BotSnapshot,
)

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
        rate = (
            bot.profit_rate
            if bot.profit_rate is not None
            else bot.pnl_rate
        )
        return rate * Decimal("100") if rate is not None else None
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



def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def _open_incident(
    session: Session,
    *,
    rule_id: int,
    bot_id: int,
) -> AlertIncident | None:
    return session.scalar(
        select(AlertIncident)
        .where(
            AlertIncident.rule_id == rule_id,
            AlertIncident.bot_id == bot_id,
            AlertIncident.recovered_at.is_(None),
        )
        .order_by(
            AlertIncident.opened_at.desc(),
            AlertIncident.id.desc(),
        )
        .limit(1)
    )


def _worst_metric_value(
    *,
    operator: str,
    threshold: Decimal,
    previous: Decimal | None,
    current: Decimal,
) -> Decimal:
    if previous is None:
        return current

    if operator in {">", ">="}:
        return max(
            previous,
            current,
        )

    if operator in {"<", "<="}:
        return min(
            previous,
            current,
        )

    # Equality / inequality have no natural monotonic
    # direction. Retain whichever observation is farther
    # away from the configured threshold.
    previous_distance = abs(
        previous - threshold
    )

    current_distance = abs(
        current - threshold
    )

    if current_distance > previous_distance:
        return current

    return previous


def _recover_incident(
    incident: AlertIncident,
    *,
    recovered_at: datetime,
    current_value: Decimal | None,
) -> None:
    incident.current_value = current_value
    incident.last_observed_at = recovered_at
    incident.recovered_at = recovered_at


def _alert_message(
    *,
    rule: AlertRule,
    bot: Bot,
    value: Decimal,
) -> str:
    account_name = (
        bot.account.name
        if bot.account
        else bot.account_id
    )

    if rule.metric == "stale_minutes":
        threshold_text = (
            format(
                rule.threshold,
                "f",
            )
            .rstrip("0")
            .rstrip(".")
            or "0"
        )

        return (
            f"[{account_name}] "
            f"{bot.strategy_name or bot.strategy_id} · "
            f"Strategy {bot.strategy_id} · "
            f"{bot.market} data stale for "
            f"{max(0, int(value))} min; "
            f"threshold {rule.operator} "
            f"{threshold_text} min."
        )

    suffix = (
        "%"
        if (
            rule.metric.endswith("_pct")
            or rule.metric == "pnl_rate"
        )
        else " USDT"
    )

    label = METRIC_LABELS.get(
        rule.metric,
        rule.metric,
    )

    return (
        f"[{account_name}] "
        f"{bot.strategy_name or bot.strategy_id} "
        f"({bot.market}) {label} "
        f"is {value:.4f}{suffix}; "
        f"rule {rule.operator} "
        f"{rule.threshold}."
    )



def evaluate_alerts(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[AlertEvent]:
    """
    Evaluate enabled alert rules.

    AlertIncident is the durable lifecycle record.

    AlertEvent remains the legacy/audit notification
    record for an incident opening. One continuous
    breach therefore creates exactly one AlertEvent,
    regardless of rule cooldown.

    Recovery does not create an AlertEvent in this
    stage because the current event API/UI cannot yet
    distinguish recovery timeline records from open
    alerts.
    """

    now = _as_utc(
        now
        or datetime.now(
            timezone.utc
        )
    )

    rules = list(
        session.scalars(
            select(AlertRule).where(
                AlertRule.enabled.is_(True)
            )
        )
    )

    bots = list(
        session.scalars(
            select(Bot)
        )
    )

    created: list[AlertEvent] = []

    for rule in rules:
        comparator = OPERATORS.get(
            rule.operator
        )

        if comparator is None:
            continue

        candidates = [
            bot
            for bot in bots
            if (
                rule.bot_id is None
                or bot.id == rule.bot_id
            )
        ]

        for bot in candidates:
            incident = _open_incident(
                session,
                rule_id=rule.id,
                bot_id=bot.id,
            )

            # A stopped strategy is expected to stop
            # receiving fresh Gate observations.
            #
            # If a stale incident was already open,
            # stopping the strategy resolves that data
            # freshness incident instead of leaving it
            # permanently open.
            if (
                rule.metric == "stale_minutes"
                and bot.status != "running"
            ):
                if incident is not None:
                    _recover_incident(
                        incident,
                        recovered_at=now,
                        current_value=None,
                    )

                continue

            value = _bot_metric(
                session,
                bot,
                rule.metric,
                now,
            )

            if value is None:
                # Unknown is not equivalent to healthy.
                # Do not silently recover an incident
                # when the metric cannot be evaluated.
                continue

            breached = comparator(
                value,
                rule.threshold,
            )

            # stale_minutes has additional evidence
            # available: last_seen_at.
            #
            # If Gate delivered a fresh observation
            # after this incident opened, the previous
            # stale period recovered at that observation,
            # even when no evaluator invocation happened
            # during the brief fresh period.
            if (
                breached
                and incident is not None
                and rule.metric == "stale_minutes"
                and bot.last_seen_at is not None
            ):
                last_seen = _as_utc(
                    bot.last_seen_at
                )

                opened_at = _as_utc(
                    incident.opened_at
                )

                if last_seen > opened_at:
                    _recover_incident(
                        incident,
                        recovered_at=last_seen,
                        current_value=Decimal("0"),
                    )

                    incident = None

            if not breached:
                if incident is not None:
                    _recover_incident(
                        incident,
                        recovered_at=now,
                        current_value=value,
                    )

                continue

            if incident is not None:
                incident.current_value = value

                incident.worst_value = (
                    _worst_metric_value(
                        operator=incident.operator,
                        threshold=(
                            incident.threshold_value
                        ),
                        previous=(
                            incident.worst_value
                        ),
                        current=value,
                    )
                )

                incident.last_observed_at = now

                # Do not create another AlertEvent.
                # cooldown_seconds will later govern
                # notification/reminder delivery.
                continue

            message = _alert_message(
                rule=rule,
                bot=bot,
                value=value,
            )

            incident = AlertIncident(
                rule_id=rule.id,
                bot_id=bot.id,
                rule_name=rule.name,
                metric=rule.metric,
                operator=rule.operator,
                threshold_value=rule.threshold,
                trigger_value=value,
                current_value=value,
                worst_value=value,
                opened_at=now,
                last_observed_at=now,
                recovered_at=None,
                acknowledged_at=None,
                acknowledged_by="",
                # The opening AlertEvent is the first
                # dashboard notification/audit signal.
                last_notification_at=now,
                message=message,
            )

            session.add(
                incident
            )

            event = AlertEvent(
                rule_id=rule.id,
                bot_id=bot.id,
                triggered_at=now,
                metric_value=value,
                message=message,
            )

            session.add(
                event
            )

            created.append(
                event
            )

    return created
