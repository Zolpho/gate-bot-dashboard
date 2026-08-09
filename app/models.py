from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow

DECIMAL = Numeric(36, 12)


class GateAccount(Base):
    __tablename__ = "gate_accounts"
    __table_args__ = (
        Index("ix_gate_accounts_enabled", "enabled"),
        Index("ix_gate_accounts_sync_status", "sync_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(64), default="subaccount")
    gate_uid: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    configured: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_status: Mapped[str] = mapped_column(String(32), default="never")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    bot_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    bots: Mapped[list["Bot"]] = relationship(back_populates="account")
    sync_runs: Mapped[list["SyncRun"]] = relationship(back_populates="account")


class Bot(Base):
    __tablename__ = "bots"
    __table_args__ = (
        UniqueConstraint("account_id", "strategy_id", "strategy_type", name="uq_bot_account_strategy"),
        Index("ix_bots_account_status", "account_id", "status"),
        Index("ix_bots_status", "status"),
        Index("ix_bots_market", "market"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("gate_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
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

    account: Mapped[GateAccount] = relationship(back_populates="bots")
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
    __table_args__ = (
        Index("ix_sync_started", "started_at"),
        Index("ix_sync_account_started", "account_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("gate_accounts.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running")
    trigger: Mapped[str] = mapped_column(String(32), default="scheduler")
    bot_count: Mapped[int] = mapped_column(Integer, default=0)
    detail_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    raw_summary_json: Mapped[str] = mapped_column(Text, default="{}")

    account: Mapped[Optional[GateAccount]] = relationship(back_populates="sync_runs")


DEPOSIT_AMOUNT = Numeric(48, 24)


class DepositAddress(Base):
    __tablename__ = "deposit_addresses"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "currency", "chain", "address", "memo",
            name="uq_deposit_address_account_currency_chain_address_memo",
        ),
        Index("ix_deposit_addresses_account_currency", "account_id", "currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("gate_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(32), nullable=False)
    chain: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    memo: Mapped[str] = mapped_column(Text, default="")
    payment_name: Mapped[str] = mapped_column(String(128), default="")
    contract_address: Mapped[str] = mapped_column(Text, default="")
    minimum_deposit_amount: Mapped[str] = mapped_column(String(128), default="")
    minimum_confirmations: Mapped[Optional[int]] = mapped_column(Integer)
    deposit_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")


class DepositRecord(Base):
    __tablename__ = "deposit_records"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "gate_deposit_id", name="uq_deposit_account_gate_id"
        ),
        Index("ix_deposits_account_time", "account_id", "deposited_at"),
        Index("ix_deposits_account_status", "account_id", "status"),
        Index("ix_deposits_txid", "txid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("gate_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gate_deposit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    txid: Mapped[str] = mapped_column(Text, default="")
    reference_id: Mapped[str] = mapped_column(String(128), default="")
    currency: Mapped[str] = mapped_column(String(32), nullable=False)
    chain: Mapped[str] = mapped_column(String(64), default="")
    amount: Mapped[Decimal] = mapped_column(DEPOSIT_AMOUNT, nullable=False, default=Decimal("0"))
    address: Mapped[str] = mapped_column(Text, default="")
    memo: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    refund_status: Mapped[str] = mapped_column(String(32), default="")
    deposited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")


class DepositSyncState(Base):
    __tablename__ = "deposit_sync_states"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("gate_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), default="never")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_reconciliation_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    window_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    window_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)


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


TREASURY_AMOUNT = Numeric(48, 24)


class TreasuryTransferRequest(Base):
    __tablename__ = "treasury_transfer_requests"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            name="uq_treasury_transfer_request_id",
        ),
        Index(
            "ix_treasury_transfer_source_created",
            "source_account_id",
            "created_at",
        ),
        Index(
            "ix_treasury_transfer_status_created",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    source_account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    destination_account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Gate's eventual main-account API uses direction="from"
    # for subaccount -> main. T2A does not call that endpoint.
    direction: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="from",
    )

    currency: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        TREASURY_AMOUNT,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="simulated",
    )

    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    request_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )

    response_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )

    client_order_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )

    gate_transfer_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )

    gate_status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
    )

    gate_label: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )

    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    simulation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    write_performed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )


class BotControlRequest(Base):
    __tablename__ = "bot_control_requests"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            name="uq_bot_control_request_id",
        ),
        Index(
            "ix_bot_control_account_created",
            "account_id",
            "created_at",
        ),
        Index(
            "ix_bot_control_user_created",
            "username",
            "created_at",
        ),
        Index(
            "ix_bot_control_status_created",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="spot_grid_create",
    )

    account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="reserved",
    )

    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    request_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )

    response_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )

    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    gate_status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
    )

    gate_label: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )

    strategy_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )


class BotControlAttentionReview(Base):
    __tablename__ = "bot_control_attention_reviews"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            name="uq_bot_control_attention_review_request",
        ),
        Index(
            "ix_bot_control_attention_review_account",
            "account_id",
            "reviewed_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    reviewed_by: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class BotControlReconciliation(Base):
    __tablename__ = "bot_control_reconciliations"
    __table_args__ = (
        Index(
            "ix_bot_control_reconcile_request_created",
            "request_id",
            "created_at",
        ),
        Index(
            "ix_bot_control_reconcile_account_created",
            "account_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    outcome: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    confidence: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="inconclusive",
    )

    strategy_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )

    gate_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    details_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class BotControlOperationLock(Base):
    __tablename__ = "bot_control_operation_locks"
    __table_args__ = (
        UniqueConstraint(
            "lock_key",
            name="uq_bot_control_operation_lock_key",
        ),
        Index(
            "ix_bot_control_lock_account_action",
            "account_id",
            "action",
        ),
        Index(
            "ix_bot_control_lock_owner_request",
            "owner_request_id",
        ),
        Index(
            "ix_bot_control_lock_strategy",
            "account_id",
            "strategy_type",
            "strategy_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    lock_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    lock_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    strategy_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )

    strategy_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )

    market: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )

    intent_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )

    owner_request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="held",
    )

    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    cooldown_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )


class BotControlLockResolution(Base):
    __tablename__ = "bot_control_lock_resolutions"
    __table_args__ = (
        Index(
            "ix_bot_control_lock_resolution_request_created",
            "request_id",
            "created_at",
        ),
        Index(
            "ix_bot_control_lock_resolution_account_created",
            "account_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    resolution_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    reconciliation_id: Mapped[Optional[int]] = mapped_column(
        Integer,
    )

    reconciliation_outcome: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )

    reconciliation_confidence: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="",
    )

    lock_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )

    prior_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="",
    )

    prior_lock_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )

    resulting_lock_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class BotControlRateLimitEvent(Base):
    __tablename__ = "bot_control_rate_limit_events"
    __table_args__ = (
        Index(
            "ix_bot_control_rate_user_action_time",
            "username",
            "action",
            "created_at",
        ),
        Index(
            "ix_bot_control_rate_account_action_time",
            "account_id",
            "action",
            "created_at",
        ),
        Index(
            "ix_bot_control_rate_created",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

