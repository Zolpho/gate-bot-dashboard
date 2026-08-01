from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select

from .accounts import AccountConfigError, GateAccountConfig, enabled_gate_accounts, load_gate_accounts
from .alerts import evaluate_alerts
from .bot_adapter import NormalizedBot, dumps_json, normalize_bot
from .config import Settings, get_settings
from .db import session_scope
from .demo import advance_demo_data
from .gate_client import GateAPIError, GateClient
from .models import Bot, BotSnapshot, GateAccount, SyncRun

logger = logging.getLogger(__name__)


class BotCollector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    async def sync(
        self,
        *,
        trigger: str = "manual",
        account_id: str | None = None,
    ) -> dict[str, Any]:
        if self._lock.locked():
            return {"status": "skipped", "reason": "sync_already_running"}

        async with self._lock:
            started = datetime.now(timezone.utc)
            aggregate_run_id = self._start_run(
                account_id=None,
                trigger=trigger,
                started=started,
            )
            try:
                if self.settings.demo_mode:
                    summary = self._sync_demo(trigger=trigger, now=started, account_id=account_id)
                else:
                    configured_accounts = load_gate_accounts()
                    self._reconcile_accounts(configured_accounts)
                    accounts = enabled_gate_accounts()
                    if account_id:
                        normalized_id = account_id.strip().lower()
                        accounts = tuple(item for item in accounts if item.id == normalized_id)
                        if not accounts:
                            raise AccountConfigError(
                                f"Unknown, disabled, or unconfigured Gate account: {account_id}"
                            )
                    if not accounts:
                        raise AccountConfigError(
                            "No enabled Gate accounts are configured. Create gate_accounts.json "
                            "or configure the legacy GATE_API_KEY and GATE_API_SECRET values."
                        )

                    semaphore = asyncio.Semaphore(self.settings.gate_account_concurrency)

                    async def sync_one(account: GateAccountConfig) -> dict[str, Any]:
                        async with semaphore:
                            return await self._sync_account(account, trigger=trigger, now=started)

                    account_results = list(await asyncio.gather(*(sync_one(account) for account in accounts)))

                    with session_scope() as session:
                        events = evaluate_alerts(session, now=started)

                    successes = [item for item in account_results if item["status"] == "success"]
                    failures = [item for item in account_results if item["status"] == "error"]
                    status = "success" if not failures else "partial" if successes else "error"
                    summary = {
                        "status": status,
                        "mode": "live",
                        "trigger": trigger,
                        "requested_account_id": account_id,
                        "account_count": len(account_results),
                        "successful_accounts": len(successes),
                        "failed_accounts": len(failures),
                        "bot_count": sum(int(item.get("bot_count", 0)) for item in successes),
                        "detail_count": sum(int(item.get("detail_count", 0)) for item in successes),
                        "alerts_created": len(events),
                        "accounts": account_results,
                        "captured_at": started.isoformat(),
                    }

                self._cleanup_snapshots(started)
                self._finish_run(aggregate_run_id, summary=summary)
                return summary
            except Exception as exc:
                logger.exception("Gate bot sync failed")
                summary = {
                    "status": "error",
                    "error": str(exc),
                    "mode": "demo" if self.settings.demo_mode else "live",
                    "trigger": trigger,
                    "requested_account_id": account_id,
                }
                self._finish_run(aggregate_run_id, summary=summary, error=str(exc))
                return summary

    @staticmethod
    def _start_run(*, account_id: str | None, trigger: str, started: datetime) -> int:
        with session_scope() as session:
            run = SyncRun(
                account_id=account_id,
                started_at=started,
                status="running",
                trigger=trigger,
            )
            session.add(run)
            session.flush()
            return run.id

    @staticmethod
    def _finish_run(run_id: int, *, summary: dict[str, Any], error: str = "") -> None:
        with session_scope() as session:
            run = session.get(SyncRun, run_id)
            if not run:
                return
            run.finished_at = datetime.now(timezone.utc)
            run.status = str(summary.get("status", "error"))
            run.bot_count = int(summary.get("bot_count", 0))
            run.detail_count = int(summary.get("detail_count", 0))
            run.error = error or str(summary.get("error", ""))
            run.raw_summary_json = json.dumps(summary, default=str)

    def _sync_demo(
        self,
        *,
        trigger: str,
        now: datetime,
        account_id: str | None,
    ) -> dict[str, Any]:
        with session_scope() as session:
            count = advance_demo_data(session, self.settings)
            events = evaluate_alerts(session, now=now)
            if account_id:
                count = session.scalar(
                    select(func.count(Bot.id)).where(Bot.account_id == account_id)
                ) or 0
        return {
            "status": "success",
            "mode": "demo",
            "trigger": trigger,
            "requested_account_id": account_id,
            "account_count": 2,
            "bot_count": count,
            "detail_count": count,
            "alerts_created": len(events),
            "captured_at": now.isoformat(),
        }

    @staticmethod
    def _reconcile_accounts(accounts: tuple[GateAccountConfig, ...]) -> None:
        now = datetime.now(timezone.utc)
        with session_scope() as session:
            configured_ids = {account.id for account in accounts}
            for account in accounts:
                row = session.get(GateAccount, account.id)
                if row is None:
                    row = GateAccount(id=account.id, name=account.name)
                    session.add(row)
                row.name = account.name
                row.account_type = account.account_type
                row.gate_uid = account.gate_uid
                row.enabled = account.enabled
                row.configured = account.configured
                if not account.enabled:
                    row.sync_status = "disabled"
                row.updated_at = now

            for row in session.scalars(select(GateAccount)).all():
                if row.id not in configured_ids and row.account_type != "demo":
                    row.enabled = False
                    row.configured = False
                    row.sync_status = "removed"
                    row.updated_at = now

    async def _sync_account(
        self,
        account: GateAccountConfig,
        *,
        trigger: str,
        now: datetime,
    ) -> dict[str, Any]:
        run_id = self._start_run(account_id=account.id, trigger=trigger, started=now)
        with session_scope() as session:
            account_row = session.get(GateAccount, account.id)
            if account_row:
                account_row.sync_status = "running"
                account_row.last_sync_at = now
                account_row.last_error = ""

        try:
            summary = await self._sync_live_account(account, now=now)
            finished = datetime.now(timezone.utc)
            self._finish_run(run_id, summary=summary)
            with session_scope() as session:
                account_row = session.get(GateAccount, account.id)
                if account_row:
                    account_row.sync_status = "success"
                    account_row.last_sync_at = finished
                    account_row.last_success_at = finished
                    account_row.last_error = ""
                    account_row.bot_count = int(summary.get("bot_count", 0))
            return summary
        except Exception as exc:
            logger.exception("Gate bot sync failed for account=%s", account.id)
            finished = datetime.now(timezone.utc)
            summary = {
                "status": "error",
                "account_id": account.id,
                "account_name": account.name,
                "trigger": trigger,
                "error": str(exc),
                "bot_count": 0,
                "detail_count": 0,
                "captured_at": now.isoformat(),
            }
            self._finish_run(run_id, summary=summary, error=str(exc))
            with session_scope() as session:
                account_row = session.get(GateAccount, account.id)
                if account_row:
                    account_row.sync_status = "error"
                    account_row.last_sync_at = finished
                    account_row.last_error = str(exc)
            return summary

    async def _sync_live_account(
        self,
        account: GateAccountConfig,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        detail_errors: list[dict[str, str]] = []
        async with GateClient(self.settings, account) as client:
            list_items, raw_pages = await client.list_all_running_bots()
            semaphore = asyncio.Semaphore(self.settings.gate_details_concurrency)

            async def fetch_detail(
                item: dict[str, Any],
            ) -> tuple[dict[str, Any], dict[str, Any] | None]:
                strategy_id = str(item.get("strategy_id", ""))
                strategy_type = str(item.get("strategy_type", ""))
                if not strategy_id or not strategy_type:
                    detail_errors.append(
                        {
                            "strategy_id": strategy_id,
                            "strategy_type": strategy_type,
                            "error": "missing strategy identifier or type",
                        }
                    )
                    return item, None
                try:
                    async with semaphore:
                        response = await client.get_bot_detail(strategy_id, strategy_type)
                    return item, response.data if isinstance(response.data, dict) else None
                except GateAPIError as exc:
                    detail_errors.append(
                        {
                            "strategy_id": strategy_id,
                            "strategy_type": strategy_type,
                            "error": str(exc),
                        }
                    )
                    return item, None

            results = await asyncio.gather(*(fetch_detail(item) for item in list_items))

        normalized = [normalize_bot(item, detail) for item, detail in results]
        with session_scope() as session:
            seen_keys: set[tuple[str, str]] = set()
            for bot_data in normalized:
                if not bot_data.strategy_id:
                    continue
                seen_keys.add((bot_data.strategy_id, bot_data.strategy_type))
                self._upsert_bot(session, account.id, bot_data, now)

            known = list(session.scalars(select(Bot).where(Bot.account_id == account.id)))
            for bot in known:
                if (bot.strategy_id, bot.strategy_type) in seen_keys:
                    continue
                if bot.status == "running":
                    bot.missing_syncs += 1
                    if bot.missing_syncs >= self.settings.missing_bot_grace_syncs:
                        bot.status = "stopped"
                        bot.stopped_at = now

        return {
            "status": "success",
            "account_id": account.id,
            "account_name": account.name,
            "bot_count": len(normalized),
            "detail_count": len(normalized) - len(detail_errors),
            "detail_errors": detail_errors,
            "page_count": len(raw_pages),
            "captured_at": now.isoformat(),
        }

    @staticmethod
    def _upsert_bot(
        session,  # type: ignore[no-untyped-def]
        account_id: str,
        data: NormalizedBot,
        now: datetime,
    ) -> Bot:
        bot = session.scalar(
            select(Bot).where(
                Bot.account_id == account_id,
                Bot.strategy_id == data.strategy_id,
                Bot.strategy_type == data.strategy_type,
            )
        )
        if bot is None:
            bot = Bot(
                account_id=account_id,
                strategy_id=data.strategy_id,
                strategy_type=data.strategy_type,
                first_seen_at=now,
            )
            session.add(bot)
            session.flush()

        fields = [
            "strategy_name",
            "market",
            "status",
            "source_status",
            "invest_amount",
            "pnl",
            "pnl_rate",
            "total_profit",
            "profit_rate",
            "grid_profit",
            "floating_pnl",
            "realized_pnl",
            "current_value",
            "arbitrage_count",
            "grid_count",
            "finished_rounds",
            "runtime_seconds",
            "price_range",
            "price_floor",
            "avg_cost",
            "take_profit_price",
            "estimated_liquidation_price",
            "maintenance_margin_ratio",
            "position_side",
            "position_amount",
            "quote_amount",
            "entry_price",
            "position_value",
            "margin",
            "stop_supported",
            "created_at_gate",
        ]
        for field in fields:
            setattr(bot, field, getattr(data, field))
        bot.last_seen_at = now
        bot.updated_at = now
        bot.missing_syncs = 0
        bot.stopped_at = None if data.status == "running" else bot.stopped_at
        bot.raw_list_json = dumps_json(data.raw_list)
        bot.raw_detail_json = dumps_json(data.raw_detail)

        session.add(
            BotSnapshot(
                bot_id=bot.id,
                captured_at=now,
                status=bot.status,
                invest_amount=bot.invest_amount,
                pnl=bot.pnl,
                pnl_rate=bot.pnl_rate,
                total_profit=bot.total_profit,
                profit_rate=bot.profit_rate,
                grid_profit=bot.grid_profit,
                floating_pnl=bot.floating_pnl,
                realized_pnl=bot.realized_pnl,
                current_value=bot.current_value,
                position_value=bot.position_value,
                liquidation_price=bot.estimated_liquidation_price,
                raw_metrics_json=dumps_json(data.metrics),
            )
        )
        return bot

    def _cleanup_snapshots(self, now: datetime) -> None:
        cutoff = now - timedelta(days=self.settings.snapshot_retention_days)
        with session_scope() as session:
            session.execute(delete(BotSnapshot).where(BotSnapshot.captured_at < cutoff))


collector = BotCollector()
