from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import Bot, BotSnapshot


def _d(value: float) -> Decimal:
    return Decimal(f"{value:.8f}")


def seed_demo_data(session: Session, settings: Settings | None = None) -> list[Bot]:
    settings = settings or get_settings()
    existing = list(session.scalars(select(Bot)))
    if existing:
        return existing

    rng = random.Random(settings.demo_seed)
    now = datetime.now(timezone.utc)
    specs: list[dict[str, Any]] = [
        {
            "strategy_id": "demo-spot-001",
            "strategy_type": "spot_grid",
            "strategy_name": "ETH Range Grid",
            "market": "ETH_USDT",
            "invest": 1500.0,
            "pnl": 128.74,
            "rate": 8.5827,
            "grid": 89.30,
            "floating": 39.44,
            "count": 146,
            "range": "2,650 – 3,850",
            "grids": 40,
            "side": "neutral",
            "entry": 3168.0,
            "liq": None,
        },
        {
            "strategy_id": "demo-futures-002",
            "strategy_type": "futures_grid",
            "strategy_name": "BTC Long Futures Grid",
            "market": "BTC_USDT",
            "invest": 1000.0,
            "pnl": -74.80,
            "rate": -7.48,
            "grid": 42.15,
            "floating": -116.95,
            "count": 92,
            "range": "95,000 – 124,000",
            "grids": 32,
            "side": "long",
            "entry": 108500.0,
            "liq": 93410.0,
        },
        {
            "strategy_id": "demo-marti-003",
            "strategy_type": "spot_martingale",
            "strategy_name": "SOL Spot Martingale",
            "market": "SOL_USDT",
            "invest": 750.0,
            "pnl": 36.61,
            "rate": 4.8813,
            "grid": None,
            "floating": 11.25,
            "count": 18,
            "range": "",
            "grids": None,
            "side": "long",
            "entry": 173.8,
            "liq": None,
        },
    ]
    bots: list[Bot] = []
    for i, spec in enumerate(specs):
        created = now - timedelta(days=14 - i * 2)
        bot = Bot(
            strategy_id=spec["strategy_id"],
            strategy_type=spec["strategy_type"],
            strategy_name=spec["strategy_name"],
            market=spec["market"],
            status="running",
            source_status="running",
            invest_amount=_d(spec["invest"]),
            pnl=_d(spec["pnl"]),
            pnl_rate=_d(spec["rate"]),
            total_profit=_d(spec["pnl"]),
            profit_rate=_d(spec["rate"]),
            grid_profit=_d(spec["grid"]) if spec["grid"] is not None else None,
            floating_pnl=_d(spec["floating"]),
            realized_pnl=_d(spec["pnl"] - spec["floating"]),
            current_value=_d(spec["invest"] + spec["pnl"]),
            arbitrage_count=spec["count"],
            grid_count=spec["grids"],
            finished_rounds=spec["count"] if "martingale" in spec["strategy_type"] else None,
            runtime_seconds=int((now - created).total_seconds()),
            price_range=spec["range"],
            position_side=spec["side"],
            position_amount=_d(0.01 * (i + 1)),
            entry_price=_d(spec["entry"]),
            estimated_liquidation_price=_d(spec["liq"]) if spec["liq"] else None,
            stop_supported=True,
            created_at_gate=created,
            first_seen_at=created,
            last_seen_at=now,
            raw_list_json='{"demo":true}',
            raw_detail_json='{"demo":true,"base_info":{},"metrics":{},"position":{}}',
        )
        session.add(bot)
        session.flush()
        bots.append(bot)

        points = 14 * 24
        for hour in range(points):
            captured = created + timedelta(hours=hour)
            if captured > now:
                break
            progress = (captured - created).total_seconds() / max(1, (now - created).total_seconds())
            base_pnl = spec["pnl"] * progress
            wave = math.sin(hour / (8.0 + i * 2)) * (18 + i * 5)
            noise = rng.uniform(-4, 4)
            pnl = base_pnl + wave + noise
            current = spec["invest"] + pnl
            session.add(
                BotSnapshot(
                    bot_id=bot.id,
                    captured_at=captured,
                    status="running",
                    invest_amount=_d(spec["invest"]),
                    pnl=_d(pnl),
                    pnl_rate=_d(pnl / spec["invest"] * 100),
                    total_profit=_d(pnl),
                    profit_rate=_d(pnl / spec["invest"] * 100),
                    grid_profit=_d(max(0, pnl * 0.65)) if spec["grid"] is not None else None,
                    floating_pnl=_d(pnl * 0.35),
                    realized_pnl=_d(pnl * 0.65),
                    current_value=_d(current),
                    position_value=_d(max(0, current * 0.8)),
                    liquidation_price=_d(spec["liq"]) if spec["liq"] else None,
                    raw_metrics_json='{"demo":true}',
                )
            )
    return bots


def advance_demo_data(session: Session, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    bots = seed_demo_data(session, settings)
    now = datetime.now(timezone.utc)
    rng = random.Random(settings.demo_seed + int(now.timestamp() // max(15, settings.poll_seconds)))
    for bot in bots:
        delta = Decimal(str(rng.uniform(-8, 11)))
        previous = bot.total_profit or Decimal("0")
        pnl = previous + delta
        bot.total_profit = pnl
        bot.pnl = pnl
        bot.current_value = (bot.invest_amount or Decimal("0")) + pnl
        if bot.invest_amount:
            bot.profit_rate = pnl / bot.invest_amount * Decimal("100")
            bot.pnl_rate = bot.profit_rate
        bot.floating_pnl = (bot.floating_pnl or Decimal("0")) + delta * Decimal("0.45")
        bot.realized_pnl = pnl - (bot.floating_pnl or Decimal("0"))
        bot.arbitrage_count = (bot.arbitrage_count or 0) + (1 if rng.random() > 0.45 else 0)
        bot.runtime_seconds = (bot.runtime_seconds or 0) + settings.poll_seconds
        bot.last_seen_at = now
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
                raw_metrics_json='{"demo":true}',
            )
        )
    return len(bots)
