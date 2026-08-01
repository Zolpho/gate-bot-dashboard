from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


STRATEGY_LABELS = {
    "spot_grid": "Spot Grid",
    "futures_grid": "Futures Grid",
    "margin_grid": "Margin Grid",
    "infinite_grid": "Infinite Grid",
    "spot_martingale": "Spot Martingale",
    "contract_martingale": "Futures Martingale",
}


@dataclass(slots=True)
class NormalizedBot:
    strategy_id: str
    strategy_type: str
    strategy_name: str
    market: str
    status: str
    source_status: str
    invest_amount: Decimal | None = None
    pnl: Decimal | None = None
    pnl_rate: Decimal | None = None
    total_profit: Decimal | None = None
    profit_rate: Decimal | None = None
    grid_profit: Decimal | None = None
    floating_pnl: Decimal | None = None
    realized_pnl: Decimal | None = None
    current_value: Decimal | None = None
    arbitrage_count: int | None = None
    grid_count: int | None = None
    finished_rounds: int | None = None
    runtime_seconds: int | None = None
    price_range: str = ""
    price_floor: Decimal | None = None
    avg_cost: Decimal | None = None
    take_profit_price: Decimal | None = None
    estimated_liquidation_price: Decimal | None = None
    maintenance_margin_ratio: Decimal | None = None
    position_side: str = ""
    position_amount: Decimal | None = None
    quote_amount: Decimal | None = None
    entry_price: Decimal | None = None
    position_value: Decimal | None = None
    margin: Decimal | None = None
    stop_supported: bool = False
    created_at_gate: datetime | None = None
    base_info: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    position: dict[str, Any] = field(default_factory=dict)
    raw_list: dict[str, Any] = field(default_factory=dict)
    raw_detail: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        result = asdict(self)
        for key, value in list(result.items()):
            if isinstance(value, Decimal):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
        return result


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value.endswith("%"):
            value = value[:-1]
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def pick(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def normalize_status(status: str) -> str:
    lowered = (status or "running").lower()
    if lowered in {"running", "active", "working", "1"}:
        return "running"
    if lowered in {"stopped", "stop", "finished", "completed", "closed", "0"}:
        return "stopped"
    if lowered in {"paused", "pause"}:
        return "paused"
    if lowered in {"error", "failed", "failure"}:
        return "error"
    return lowered or "running"


def normalize_bot(list_item: Mapping[str, Any], detail: Mapping[str, Any] | None) -> NormalizedBot:
    detail = detail or {}
    base_info = detail.get("base_info") if isinstance(detail.get("base_info"), dict) else {}
    metrics = detail.get("metrics") if isinstance(detail.get("metrics"), dict) else {}
    position = detail.get("position") if isinstance(detail.get("position"), dict) else {}

    strategy_id = str(pick(detail, "strategy_id") or pick(list_item, "strategy_id") or "")
    strategy_type = str(pick(detail, "strategy_type") or pick(list_item, "strategy_type") or "unknown")
    source_status = str(pick(detail, "status") or pick(list_item, "status") or "running")

    invest = decimal_or_none(pick(base_info, "invest_amount", "investment", "total_invest"))
    if invest is None:
        invest = decimal_or_none(pick(list_item, "invest_amount"))

    list_pnl = decimal_or_none(pick(list_item, "pnl"))
    total_profit = decimal_or_none(pick(base_info, "total_profit", "pnl", "total_pnl"))
    if total_profit is None:
        total_profit = list_pnl

    list_pnl_rate = decimal_or_none(pick(list_item, "pnl_rate"))
    profit_rate = decimal_or_none(pick(base_info, "profit_rate", "pnl_rate", "roi"))
    if profit_rate is None:
        profit_rate = list_pnl_rate

    current_value = decimal_or_none(
        pick(base_info, "current_value", "strategy_value", "total_value", "equity")
    )
    if current_value is None and invest is not None and total_profit is not None:
        current_value = invest + total_profit

    strategy_name = str(
        pick(base_info, "strategy_name")
        or pick(list_item, "strategy_name")
        or STRATEGY_LABELS.get(strategy_type, strategy_type.replace("_", " ").title())
    )

    market = str(pick(detail, "market") or pick(list_item, "market") or "")

    normalized = NormalizedBot(
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        strategy_name=strategy_name,
        market=market,
        status=normalize_status(source_status),
        source_status=source_status,
        invest_amount=invest,
        pnl=list_pnl if list_pnl is not None else total_profit,
        pnl_rate=list_pnl_rate if list_pnl_rate is not None else profit_rate,
        total_profit=total_profit,
        profit_rate=profit_rate,
        grid_profit=decimal_or_none(pick(metrics, "grid_profit")),
        floating_pnl=decimal_or_none(pick(metrics, "floating_pnl", "unrealized_pnl", "unrealised_pnl")),
        realized_pnl=decimal_or_none(pick(metrics, "realized_pnl", "realised_pnl")),
        current_value=current_value,
        arbitrage_count=int_or_none(pick(metrics, "arbitrage_count", "arbitrage_times")),
        grid_count=int_or_none(pick(metrics, "grid_count", "grids")),
        finished_rounds=int_or_none(pick(metrics, "finished_rounds", "rounds")),
        runtime_seconds=int_or_none(pick(base_info, "running_duration", "runtime_seconds", "runtime")),
        price_range=str(pick(metrics, "price_range") or ""),
        price_floor=decimal_or_none(pick(metrics, "price_floor", "lower_price")),
        avg_cost=decimal_or_none(pick(metrics, "avg_cost", "average_cost")),
        take_profit_price=decimal_or_none(pick(metrics, "take_profit_price", "tp_price")),
        estimated_liquidation_price=decimal_or_none(
            pick(metrics, "estimated_liquidation_price", "liquidation_price", "liq_price")
        ),
        maintenance_margin_ratio=decimal_or_none(
            pick(metrics, "maintenance_margin_ratio", "maintenance_rate")
        ),
        position_side=str(pick(position, "side", "direction") or ""),
        position_amount=decimal_or_none(pick(position, "amount", "size")),
        quote_amount=decimal_or_none(pick(position, "quote_amount")),
        entry_price=decimal_or_none(pick(position, "entry_price", "avg_entry_price")),
        position_value=decimal_or_none(pick(position, "position_value", "value")),
        margin=decimal_or_none(pick(position, "margin")),
        stop_supported=bool(detail.get("stop_supported", False)),
        created_at_gate=parse_datetime(
            pick(base_info, "created_at", "create_time") or pick(list_item, "created_at")
        ),
        base_info=dict(base_info),
        metrics=dict(metrics),
        position=dict(position),
        raw_list=dict(list_item),
        raw_detail=dict(detail),
    )
    return normalized


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
