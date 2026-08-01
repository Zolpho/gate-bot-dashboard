from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow

DECIMAL = Numeric(36, 12)


class Bot(Base):
    __tablename__ = "bots"
    __table_args__ = (
        UniqueConstraint("strategy_id", "strategy_type", name="uq_bot_strategy"),
        Index("ix_bots_status", "status"),
        Index("ix_bots_market", "market"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(255), default="")
    market: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="running")
    source_status: Mapped[str] = mapped_column(String(64), default="")

    invest_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    pnl: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    pnl_rate: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    total_profit: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    profit_rate: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    grid_profit: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    floating_pnl: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    realized_pnl: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    current_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)

    arbitrage_count: Mapped[Optional[int]] = mapped_column(Integer)
    grid_count: Mapped[Optional[int]] = mapped_column(Integer)
    finished_rounds: Mapped[Optional[int]] = mapped_column(Integer)
    runtime_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    price_range: Mapped[str] = mapped_column(String(255), default="")
    price_floor: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    avg_cost: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    take_profit_price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    estimated_liquidation_price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    maintenance_margin_ratio: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)

    position_side: Mapped[str] = mapped_column(String(32), default="")
    position_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    quote_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    position_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    margin: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)

    stop_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_syncs: Mapped[int] = mapped_column(Integer, default=0)
    created_at_gate: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    raw_list_json: Mapped[str] = mapped_column(Text, default="{}")
    raw_detail_json: Mapped[str] = mapped_column(Text, default="{}")

    snapshots: Mapped[list["BotSnapshot"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    alert_events: Mapped[list["AlertEvent"]] = relationship(back_populates="bot")


class BotSnapshot(Base):
    __tablename__ = "bot_snapshots"
    __table_args__ = (
        Index("ix_snapshot_bot_time", "bot_id", "captured_at"),
        Index("ix_snapshot_time", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running")

    invest_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    pnl: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    pnl_rate: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    total_profit: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    profit_rate: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    grid_profit: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    floating_pnl: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    realized_pnl: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    current_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    position_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    liquidation_price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    raw_metrics_json: Mapped[str] = mapped_column(Text, default="{}")

    bot: Mapped[Bot] = relationship(back_populates="snapshots")


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_started", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running")
    bot_count: Mapped[int] = mapped_column(Integer, default=0)
    detail_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    raw_summary_json: Mapped[str] = mapped_column(Text, default="{}")


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rule_enabled", "enabled"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(8), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(DECIMAL, nullable=False)
    bot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_event_time", "triggered_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False)
    bot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bots.id", ondelete="SET NULL"))
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metric_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    rule: Mapped[AlertRule] = relationship(back_populates="events")
    bot: Mapped[Optional[Bot]] = relationship(back_populates="alert_events")
