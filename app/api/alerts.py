from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..metrics import as_utc, bot_to_dict, decimal_to_float
from ..models import AlertEvent, AlertRule, Bot

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class RulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    metric: Literal["pnl", "pnl_rate", "drawdown_pct", "floating_pnl", "current_value", "liquidation_distance_pct", "stale_minutes"]
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


def rule_to_dict(rule: AlertRule) -> dict:  # type: ignore[type-arg]
    return {
        "id": rule.id,
        "name": rule.name,
        "metric": rule.metric,
        "operator": rule.operator,
        "threshold": decimal_to_float(rule.threshold),
        "bot_id": rule.bot_id,
        "enabled": rule.enabled,
        "cooldown_seconds": rule.cooldown_seconds,
        "created_at": as_utc(rule.created_at).isoformat(),
        "updated_at": as_utc(rule.updated_at).isoformat(),
    }


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    rules = db.scalars(select(AlertRule).order_by(AlertRule.id.asc())).all()
    return {"items": [rule_to_dict(rule) for rule in rules]}


@router.post("/rules")
def create_rule(payload: RulePayload, db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    if payload.bot_id is not None and db.get(Bot, payload.bot_id) is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule_to_dict(rule)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RulePatch, db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule_to_dict(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "deleted"}


@router.get("/events")
def list_events(
    unacknowledged_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    stmt = select(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(limit)
    if unacknowledged_only:
        stmt = stmt.where(AlertEvent.acknowledged_at.is_(None))
    events = db.scalars(stmt).all()
    result = []
    for event in events:
        bot = db.get(Bot, event.bot_id) if event.bot_id else None
        result.append(
            {
                "id": event.id,
                "rule_id": event.rule_id,
                "bot_id": event.bot_id,
                "bot": bot_to_dict(bot) if bot else None,
                "triggered_at": as_utc(event.triggered_at).isoformat(),
                "metric_value": decimal_to_float(event.metric_value),
                "message": event.message,
                "acknowledged_at": as_utc(event.acknowledged_at).isoformat() if event.acknowledged_at else None,
            }
        )
    return {"items": result}


@router.post("/events/{event_id}/acknowledge")
def acknowledge_event(event_id: int, db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    event = db.get(AlertEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Alert event not found")
    event.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "acknowledged", "id": event.id}
