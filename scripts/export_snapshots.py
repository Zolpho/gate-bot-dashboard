#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select

from app.db import session_scope
from app.models import Bot, BotSnapshot


def main() -> None:
    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)
    output = export_dir / "gate_bot_snapshots.csv"
    with session_scope() as session, output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "account_id", "account_name", "strategy_id", "strategy_type", "strategy_name", "market", "captured_at", "status",
            "invest_amount", "current_value", "total_profit", "profit_rate", "grid_profit",
            "floating_pnl", "realized_pnl", "position_value", "liquidation_price",
        ])
        rows = session.execute(
            select(BotSnapshot, Bot).join(Bot, Bot.id == BotSnapshot.bot_id).order_by(BotSnapshot.captured_at)
        )
        for snapshot, bot in rows:
            writer.writerow([
                bot.account_id, bot.account.name if bot.account else bot.account_id, bot.strategy_id, bot.strategy_type, bot.strategy_name, bot.market, snapshot.captured_at,
                snapshot.status, snapshot.invest_amount, snapshot.current_value, snapshot.total_profit,
                snapshot.profit_rate, snapshot.grid_profit, snapshot.floating_pnl, snapshot.realized_pnl,
                snapshot.position_value, snapshot.liquidation_price,
            ])
    print(output.resolve())


if __name__ == "__main__":
    main()
