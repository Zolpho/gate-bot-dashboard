from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..metrics import as_utc, bot_to_dict, decimal_to_float
from ..models import AlertEvent, AlertIncident, AlertRule, Bot
from ..security import DashboardUser, require_account_access, require_user

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class RulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    metric: Literal[
        "pnl",
        "pnl_rate",
        "drawdown_pct",
        "floating_pnl",
        "current_value",
        "liquidation_distance_pct",
        "stale_minutes",
    ]
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    threshold: Decimal
    bot_id: int | None = None
    enabled: bool = True
    cooldown_seconds: int = Field(default=3600, ge=0, le=604800)


class RulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    threshold: Decimal | None = None
    enabled: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=604800)


def _rule_bot(db: Session, rule: AlertRule) -> Bot | None:
    return db.get(Bot, rule.bot_id) if rule.bot_id is not None else None


def _require_rule_access(user: DashboardUser, db: Session, rule: AlertRule) -> Bot | None:
    bot = _rule_bot(db, rule)
    if bot is None:
        if not user.is_super_admin:
            raise HTTPException(
                status_code=403,
                detail="Only a super admin may change a rule that applies to all bots",
            )
        return None
    require_account_access(user, bot.account_id)
    return bot


def rule_to_dict(rule: AlertRule, bot: Bot | None = None) -> dict:  # type: ignore[type-arg]
    return {
        "id": rule.id,
        "name": rule.name,
        "metric": rule.metric,
        "operator": rule.operator,
        "threshold": decimal_to_float(rule.threshold),
        "bot_id": rule.bot_id,
        "account_id": bot.account_id if bot else None,
        "account_name": bot.account.name if bot and bot.account else (bot.account_id if bot else None),
        "enabled": rule.enabled,
        "cooldown_seconds": rule.cooldown_seconds,
        "created_at": as_utc(rule.created_at).isoformat(),
        "updated_at": as_utc(rule.updated_at).isoformat(),
    }


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    rules = db.scalars(select(AlertRule).order_by(AlertRule.id.asc())).all()
    return {"items": [rule_to_dict(rule, _rule_bot(db, rule)) for rule in rules]}


@router.post("/rules")
def create_rule(
    payload: RulePayload,
    user: Annotated[DashboardUser, Depends(require_user)],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    bot: Bot | None = None
    if payload.bot_id is None:
        if not user.is_super_admin:
            raise HTTPException(
                status_code=403,
                detail="Account operators must select one of their own bots",
            )
    else:
        bot = db.get(Bot, payload.bot_id)
        if bot is None:
            raise HTTPException(status_code=404, detail="Bot not found")
        require_account_access(user, bot.account_id)

    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule_to_dict(rule, bot)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RulePatch,
    user: Annotated[DashboardUser, Depends(require_user)],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    bot = _require_rule_access(user, db, rule)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule_to_dict(rule, bot)


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    user: Annotated[DashboardUser, Depends(require_user)],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    _require_rule_access(user, db, rule)
    db.delete(rule)
    db.commit()
    return {"status": "deleted"}


def _incident_bot(
    db: Session,
    incident: AlertIncident,
) -> Bot | None:
    return (
        db.get(
            Bot,
            incident.bot_id,
        )
        if incident.bot_id is not None
        else None
    )


def _require_incident_access(
    user: DashboardUser,
    db: Session,
    incident: AlertIncident,
) -> Bot | None:
    bot = _incident_bot(
        db,
        incident,
    )

    if bot is None:
        if not user.is_super_admin:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Super-admin permission "
                    "is required"
                ),
            )

        return None

    require_account_access(
        user,
        bot.account_id,
    )

    return bot


def incident_to_dict(
    incident: AlertIncident,
    bot: Bot | None = None,
) -> dict:  # type: ignore[type-arg]
    recovered_at = (
        as_utc(
            incident.recovered_at
        ).isoformat()
        if incident.recovered_at
        else None
    )

    acknowledged_at = (
        as_utc(
            incident.acknowledged_at
        ).isoformat()
        if incident.acknowledged_at
        else None
    )

    last_notification_at = (
        as_utc(
            incident.last_notification_at
        ).isoformat()
        if incident.last_notification_at
        else None
    )

    return {
        "id": incident.id,
        "rule_id": incident.rule_id,
        "rule_name": incident.rule_name,
        "metric": incident.metric,
        "operator": incident.operator,
        "threshold": decimal_to_float(
            incident.threshold_value
        ),
        "bot_id": incident.bot_id,
        "account_id": (
            bot.account_id
            if bot
            else None
        ),
        "account_name": (
            bot.account.name
            if bot and bot.account
            else (
                bot.account_id
                if bot
                else None
            )
        ),
        "bot": (
            bot_to_dict(bot)
            if bot
            else None
        ),
        "trigger_value": decimal_to_float(
            incident.trigger_value
        ),
        "current_value": decimal_to_float(
            incident.current_value
        ),
        "worst_value": decimal_to_float(
            incident.worst_value
        ),
        "opened_at": as_utc(
            incident.opened_at
        ).isoformat(),
        "last_observed_at": as_utc(
            incident.last_observed_at
        ).isoformat(),
        "recovered_at": recovered_at,
        "acknowledged_at": acknowledged_at,
        "acknowledged_by": (
            incident.acknowledged_by
            or ""
        ),
        "last_notification_at": (
            last_notification_at
        ),
        "message": incident.message,
        "state": (
            "recovered"
            if incident.recovered_at
            else "open"
        ),
        "is_open": (
            incident.recovered_at
            is None
        ),
        "is_acknowledged": (
            incident.acknowledged_at
            is not None
        ),
    }


@router.get("/incidents")
def list_incidents(
    state: Literal[
        "open",
        "history",
        "all",
    ] = "open",
    account_id: str | None = None,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    stmt = select(
        AlertIncident
    )

    if state == "open":
        stmt = stmt.where(
            AlertIncident.recovered_at.is_(None)
        )

    elif state == "history":
        stmt = stmt.where(
            AlertIncident.recovered_at.is_not(None)
        )

    if account_id:
        normalized_account_id = (
            account_id
            .strip()
            .lower()
        )

        stmt = (
            stmt
            .join(
                Bot,
                Bot.id
                == AlertIncident.bot_id,
            )
            .where(
                Bot.account_id
                == normalized_account_id
            )
        )

    stmt = (
        stmt
        .order_by(
            AlertIncident.opened_at.desc(),
            AlertIncident.id.desc(),
        )
        .limit(
            limit
        )
    )

    incidents = db.scalars(
        stmt
    ).all()

    result = []

    for incident in incidents:
        bot = _incident_bot(
            db,
            incident,
        )

        result.append(
            incident_to_dict(
                incident,
                bot,
            )
        )

    return {
        "items": result,
        "state": state,
        "account_id": (
            account_id.strip().lower()
            if account_id
            else None
        ),
        "limit": limit,
    }


@router.post(
    "/incidents/{incident_id}/acknowledge"
)
def acknowledge_incident(
    incident_id: int,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    incident = db.get(
        AlertIncident,
        incident_id,
    )

    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Alert incident not found",
        )

    bot = _require_incident_access(
        user,
        db,
        incident,
    )

    # Acknowledgement means "an operator has seen this
    # incident". It is independent from recovery.
    #
    # Preserve the first acknowledgement identity/time
    # if the endpoint is called repeatedly.
    if incident.acknowledged_at is None:
        incident.acknowledged_at = (
            datetime.now(
                timezone.utc
            )
        )

        incident.acknowledged_by = (
            user.username
        )

        db.commit()
        db.refresh(
            incident
        )

    return {
        "status": "acknowledged",
        "id": incident.id,
        "incident": incident_to_dict(
            incident,
            bot,
        ),
    }


@router.get("/events")
def list_events(
    unacknowledged_only: bool = False,
    account_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    stmt = select(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(limit)
    if unacknowledged_only:
        stmt = stmt.where(AlertEvent.acknowledged_at.is_(None))
    if account_id:
        stmt = stmt.join(Bot, Bot.id == AlertEvent.bot_id).where(
            Bot.account_id == account_id.strip().lower()
        )
    events = db.scalars(stmt).all()
    result = []
    for event in events:
        bot = db.get(Bot, event.bot_id) if event.bot_id else None
        result.append(
            {
                "id": event.id,
                "rule_id": event.rule_id,
                "bot_id": event.bot_id,
                "account_id": bot.account_id if bot else None,
                "bot": bot_to_dict(bot) if bot else None,
                "triggered_at": as_utc(event.triggered_at).isoformat(),
                "metric_value": decimal_to_float(event.metric_value),
                "message": event.message,
                "acknowledged_at": (
                    as_utc(event.acknowledged_at).isoformat()
                    if event.acknowledged_at
                    else None
                ),
            }
        )
    return {"items": result}


@router.post("/events/{event_id}/acknowledge")
def acknowledge_event(
    event_id: int,
    user: Annotated[DashboardUser, Depends(require_user)],
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    event = db.get(AlertEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Alert event not found")
    if event.bot_id is None:
        if not user.is_super_admin:
            raise HTTPException(status_code=403, detail="Super-admin permission is required")
    else:
        bot = db.get(Bot, event.bot_id)
        if bot is None:
            if not user.is_super_admin:
                raise HTTPException(status_code=403, detail="Super-admin permission is required")
        else:
            require_account_access(user, bot.account_id)
    event.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "acknowledged", "id": event.id}
