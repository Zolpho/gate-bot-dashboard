from __future__ import annotations

from decimal import Decimal

from app.bot_adapter import normalize_bot


def test_normalize_flexible_gate_maps() -> None:
    item = {
        "strategy_id": "123",
        "strategy_type": "futures_grid",
        "strategy_name": "BTC grid",
        "market": "BTC_USDT",
        "status": "running",
        "pnl": "12.5",
        "pnl_rate": "2.5",
        "invest_amount": "500",
        "created_at": "1700000000",
    }
    detail = {
        "strategy_id": "123",
        "strategy_type": "futures_grid",
        "market": "BTC_USDT",
        "status": "running",
        "stop_supported": True,
        "base_info": {"total_profit": "15", "profit_rate": "3", "running_duration": "3600"},
        "metrics": {"grid_profit": "7", "floating_pnl": "8", "grid_count": "20", "estimated_liquidation_price": "90000"},
        "position": {"side": "long", "amount": "0.01", "entry_price": "100000"},
    }
    bot = normalize_bot(item, detail)
    assert bot.strategy_id == "123"
    assert bot.total_profit == Decimal("15")
    assert bot.current_value == Decimal("515")
    assert bot.grid_count == 20
    assert bot.position_side == "long"
    assert bot.stop_supported is True

def test_spot_position_value_is_derived_from_amount_and_entry_price() -> None:
    item = {
        "strategy_id": "5264184",
        "strategy_type": "spot_grid",
        "strategy_name": "EQTY/USDT Spot Grid",
        "market": "EQTY_USDT",
        "status": "running",
    }

    detail = {
        "strategy_id": "5264184",
        "strategy_type": "spot_grid",
        "market": "EQTY_USDT",
        "status": "running",
        "position": {
            "amount": "177833.34518",
            "entry_price": "0.001801",
        },
    }

    bot = normalize_bot(item, detail)

    assert bot.position_amount == Decimal(
        "177833.34518"
    )
    assert bot.entry_price == Decimal(
        "0.001801"
    )
    assert bot.position_value == Decimal(
        "320.27785466918"
    )
    assert bot.to_jsonable()["position_value"] == (
        "320.27785466918"
    )

