from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from .alerts import evaluate_alerts
from .bot_adapter import NormalizedBot, dumps_json, normalize_bot
from .config import Settings, get_settings
from .db import session_scope
from .demo import advance_demo_data
from .gate_client import GateAPIError, GateClient
from .models import Bot, BotSnapshot, SyncRun

logger = logging.getLogger(__name__)


class BotCollector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    async def sync(self, *, trigger: str = "manual") -> dict[str, Any]:
        if self._lock.locked():
            return {"status": "skipped", "reason": "sync_already_running"}

        async with self._lock:
            started = datetime.now(timezone.utc)
            with session_scope() as session:
                run = SyncRun(started_at=started, status="running")
                session.add(run)
                session.flush()
                run_id = run.id

            try:
                if self.settings.demo_mode:
                    with session_scope() as session:
                        count = advance_demo_data(session, self.settings)
                        events = evaluate_alerts(session, now=started)
                    summary = {
                        "status": "success",
                        "mode": "demo",
                        "trigger": trigger,
                        "bot_count": count,
                        "detail_count": count,
                        "alerts_created": len(events),
                    }
                else:
                    if not self.settings.gate_configured:
                        raise RuntimeError(
                            "Gate credentials are not configured. Set GATE_API_KEY and GATE_API_SECRET, or enable DEMO_MODE."
                        )
                    summary = await self._sync_live(trigger=trigger, now=started)

                self._cleanup_snapshots(started)
                with session_scope() as session:
                    run = session.get(SyncRun, run_id)
                    if run:
                        run.finished_at = datetime.now(timezone.utc)
                        run.status = "success"
                        run.bot_count = int(summary.get("bot_count", 0))
                        run.detail_count = int(summary.get("detail_count", 0))
                        run.raw_summary_json = json.dumps(summary, default=str)
                return summary
            except Exception as exc:
                logger.exception("Gate bot sync failed")
                with session_scope() as session:
                    run = session.get(SyncRun, run_id)
                    if run:
                        run.finished_at = datetime.now(timezone.utc)
                        run.status = "error"
                        run.error = str(exc)
                        run.raw_summary_json = json.dumps(
                            {"status": "error", "mode": "demo" if self.settings.demo_mode else "live", "trigger": trigger},
                            default=str,
                        )
                return {"status": "error", "error": str(exc), "trigger": trigger}

    async def _sync_live(self, *, trigger: str, now: datetime) -> dict[str, Any]:
        detail_errors: list[dict[str, str]] = []
        async with GateClient(self.settings) as client:
            list_items, raw_pages = await client.list_all_running_bots()
            semaphore = asyncio.Semaphore(self.settings.gate_details_concurrency)

            async def fetch_detail(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
                strategy_id = str(item.get("strategy_id", ""))
                strategy_type = str(item.get("strategy_type", ""))
                if not strategy_id or not strategy_type:
                    detail_errors.append({"strategy_id": strategy_id, "error": "missing strategy identifier or type"})
                    return item, None
                try:
                    async with semaphore:
                        response = await client.get_bot_detail(strategy_id, strategy_type)
                    return item, response.data if isinstance(response.data, dict) else None
                except GateAPIError as exc:
                    detail_errors.append({"strategy_id": strategy_id, "error": str(exc)})
                    return item, None

            results = await asyncio.gather(*(fetch_detail(item) for item in list_items))

        normalized = [normalize_bot(item, detail) for item, detail in results]
        with session_scope() as session:
            seen_keys: set[tuple[str, str]] = set()
            for bot_data in normalized:
                if not bot_data.strategy_id:
                    continue
                seen_keys.add((bot_data.strategy_id, bot_data.strategy_type))
                self._upsert_bot(session, bot_data, now)

            known = list(session.scalars(select(Bot)))
            for bot in known:
                if (bot.strategy_id, bot.strategy_type) in seen_keys:
                    continue
                if bot.status == "running":
                    bot.missing_syncs += 1
                    if bot.missing_syncs >= self.settings.missing_bot_grace_syncs:
                        bot.status = "stopped"
                        bot.stopped_at = now

            events = evaluate_alerts(session, now=now)

        return {
            "status": "success",
            "mode": "live",
            "trigger": trigger,
            "bot_count": len(normalized),
            "detail_count": len(normalized) - len(detail_errors),
            "detail_errors": detail_errors,
            "page_count": len(raw_pages),
            "alerts_created": len(events),
            "captured_at": now.isoformat(),
        }

    @staticmethod
    def _upsert_bot(session, data: NormalizedBot, now: datetime) -> Bot:  # type: ignore[no-untyped-def]
        bot = session.scalar(
            select(Bot).where(
                Bot.strategy_id == data.strategy_id,
                Bot.strategy_type == data.strategy_type,
            )
        )
        if bot is None:
            bot = Bot(strategy_id=data.strategy_id, strategy_type=data.strategy_type, first_seen_at=now)
            session.add(bot)
            session.flush()

        fields = [
            "strategy_name", "market", "status", "source_status", "invest_amount", "pnl", "pnl_rate",
            "total_profit", "profit_rate", "grid_profit", "floating_pnl", "realized_pnl", "current_value",
            "arbitrage_count", "grid_count", "finished_rounds", "runtime_seconds", "price_range", "price_floor",
            "avg_cost", "take_profit_price", "estimated_liquidation_price", "maintenance_margin_ratio",
            "position_side", "position_amount", "quote_amount", "entry_price", "position_value", "margin",
            "stop_supported", "created_at_gate",
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
