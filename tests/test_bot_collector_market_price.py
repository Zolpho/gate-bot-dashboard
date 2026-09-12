from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.collector as collector_module
from app.collector import BotCollector
from app.db import Base
from app.gate_client import GateAPIError, GateResponse
from app.metrics import bot_range_state
from app.models import Bot, GateAccount


def _list_item(
    strategy_id: str,
    *,
    market: str = "EQTY_USDT",
    strategy_type: str = "spot_grid",
) -> dict:
    return {
        "strategy_id": strategy_id,
        "strategy_type": strategy_type,
        "strategy_name": f"Bot {strategy_id}",
        "market": market,
        "status": "running",
        "invest_amount": "100",
        "pnl": "1",
        "pnl_rate": "0.01",
    }


def _detail(
    strategy_id: str,
    *,
    market: str = "EQTY_USDT",
    strategy_type: str = "spot_grid",
) -> dict:
    return {
        "strategy_id": strategy_id,
        "strategy_type": strategy_type,
        "status": "running",
        "market": market,
        "base_info": {
            "strategy_name": f"Bot {strategy_id}",
            "invest_amount": "100",
            "total_profit": "1",
            "profit_rate": "0.01",
            "running_duration": 120,
        },
        "metrics": {
            "price_range": "0.001500-0.002500",
            "grid_profit": "0.5",
            "arbitrage_count": 1,
            "grid_count": 10,
        },
        "position": {},
        "stop_supported": True,
    }


class FakeGateClient:
    list_items: list[dict] = []
    details: dict[str, dict] = {}
    ticker_calls: list[str] = []
    ticker_mode = "success"

    def __init__(
        self,
        settings=None,
        account=None,
    ) -> None:
        self.settings = settings
        self.account = account

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        _exc_type,
        _exc,
        _tb,
    ):
        return False

    async def list_all_running_bots(self):
        return (
            list(self.list_items),
            [
                {
                    "items": list(
                        self.list_items
                    )
                }
            ],
        )

    async def get_bot_detail(
        self,
        strategy_id: str,
        strategy_type: str,
    ) -> GateResponse:
        del strategy_type

        detail = self.details[
            strategy_id
        ]

        return GateResponse(
            data=detail,
            status_code=200,
            headers={},
            raw=detail,
        )

    async def list_spot_tickers(
        self,
        currency_pair: str | None = None,
    ) -> GateResponse:
        market = str(
            currency_pair or ""
        ).upper()

        type(self).ticker_calls.append(
            market
        )

        if self.ticker_mode == "error":
            raise GateAPIError(
                "simulated ticker read failure"
            )

        data = [
            {
                "currency_pair": market,
                "last": (
                    "0.002600"
                    if market == "EQTY_USDT"
                    else "65000"
                ),
            }
        ]

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )


def _database():
    engine = create_engine(
        "sqlite:///:memory:"
    )

    Base.metadata.create_all(
        engine
    )

    factory = sessionmaker(
        bind=engine
    )

    db = factory()

    db.add(
        GateAccount(
            id="zolnode",
            name="zolnode",
            enabled=True,
            configured=True,
        )
    )

    db.commit()

    return engine, db


def _patch_session_scope(
    monkeypatch,
    db,
) -> None:
    @contextmanager
    def test_session_scope():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    monkeypatch.setattr(
        collector_module,
        "session_scope",
        test_session_scope,
    )


def _collector() -> BotCollector:
    return BotCollector(
        settings=SimpleNamespace(
            gate_details_concurrency=4,
            missing_bot_grace_syncs=2,
        )
    )


def _account():
    return SimpleNamespace(
        id="zolnode",
        name="zolnode",
    )


@pytest.mark.asyncio
async def test_live_sync_deduplicates_spot_grid_ticker_reads(
    monkeypatch,
) -> None:
    engine, db = _database()

    try:
        FakeGateClient.list_items = [
            _list_item(
                "spot-a"
            ),
            _list_item(
                "spot-b"
            ),
            _list_item(
                "future-a",
                market="BTC_USDT",
                strategy_type="futures_grid",
            ),
        ]

        FakeGateClient.details = {
            "spot-a": _detail(
                "spot-a"
            ),
            "spot-b": _detail(
                "spot-b"
            ),
            "future-a": _detail(
                "future-a",
                market="BTC_USDT",
                strategy_type="futures_grid",
            ),
        }

        FakeGateClient.ticker_calls = []
        FakeGateClient.ticker_mode = (
            "success"
        )

        monkeypatch.setattr(
            collector_module,
            "GateClient",
            FakeGateClient,
        )

        _patch_session_scope(
            monkeypatch,
            db,
        )

        summary = await (
            _collector()
            ._sync_live_account(
                _account(),
                now=datetime.now(
                    timezone.utc
                ),
            )
        )

        assert (
            summary["status"]
            == "success"
        )

        assert (
            summary["bot_count"]
            == 3
        )

        assert (
            FakeGateClient.ticker_calls
            == ["EQTY_USDT"]
        )

        db.expire_all()

        rows = {
            bot.strategy_id: bot
            for bot in db.scalars(
                select(Bot)
            )
        }

        assert set(rows) == {
            "spot-a",
            "spot-b",
            "future-a",
        }

        for strategy_id in (
            "spot-a",
            "spot-b",
        ):
            bot = rows[
                strategy_id
            ]

            assert (
                bot.current_market_price
                == Decimal(
                    "0.002600"
                )
            )

            assert (
                bot_range_state(bot)
                == "out_of_range"
            )

            assert (
                bot.status
                == "running"
            )

            assert (
                bot.source_status
                == "running"
            )

        assert (
            rows[
                "future-a"
            ].current_market_price
            is None
        )

        assert (
            bot_range_state(
                rows["future-a"]
            )
            == "not_applicable"
        )

    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_ticker_failure_clears_stale_price_without_failing_sync(
    monkeypatch,
) -> None:
    engine, db = _database()

    try:
        stale = Bot(
            account_id="zolnode",
            strategy_id="spot-a",
            strategy_type="spot_grid",
            strategy_name="Existing bot",
            market="EQTY_USDT",
            status="running",
            source_status="running",
            price_range=(
                "0.001500-0.002500"
            ),
            current_market_price=Decimal(
                "0.001900"
            ),
        )

        db.add(stale)
        db.commit()

        FakeGateClient.list_items = [
            _list_item(
                "spot-a"
            )
        ]

        FakeGateClient.details = {
            "spot-a": _detail(
                "spot-a"
            )
        }

        FakeGateClient.ticker_calls = []
        FakeGateClient.ticker_mode = (
            "error"
        )

        monkeypatch.setattr(
            collector_module,
            "GateClient",
            FakeGateClient,
        )

        _patch_session_scope(
            monkeypatch,
            db,
        )

        summary = await (
            _collector()
            ._sync_live_account(
                _account(),
                now=datetime.now(
                    timezone.utc
                ),
            )
        )

        assert (
            summary["status"]
            == "success"
        )

        assert (
            summary["detail_errors"]
            == []
        )

        assert (
            FakeGateClient.ticker_calls
            == ["EQTY_USDT"]
        )

        db.expire_all()

        refreshed = db.scalar(
            select(Bot).where(
                Bot.strategy_id
                == "spot-a"
            )
        )

        assert refreshed is not None

        assert (
            refreshed.current_market_price
            is None
        )

        assert (
            refreshed.status
            == "running"
        )

        assert (
            refreshed.source_status
            == "running"
        )

        assert (
            bot_range_state(
                refreshed
            )
            == "unknown"
        )

    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_last",
    [
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
async def test_non_finite_ticker_price_is_treated_as_missing_evidence(
    monkeypatch,
    bad_last,
) -> None:
    engine, db = _database()

    try:
        stale = Bot(
            account_id="zolnode",
            strategy_id="spot-a",
            strategy_type="spot_grid",
            strategy_name="Existing bot",
            market="EQTY_USDT",
            status="running",
            source_status="running",
            price_range=(
                "0.001500-0.002500"
            ),
            current_market_price=Decimal(
                "0.001900"
            ),
        )

        db.add(stale)
        db.commit()

        FakeGateClient.list_items = [
            _list_item(
                "spot-a"
            )
        ]

        FakeGateClient.details = {
            "spot-a": _detail(
                "spot-a"
            )
        }

        FakeGateClient.ticker_calls = []
        FakeGateClient.ticker_mode = (
            "success"
        )

        async def non_finite_ticker(
            self,
            currency_pair=None,
        ):
            market = str(
                currency_pair or ""
            ).upper()

            type(self).ticker_calls.append(
                market
            )

            data = [
                {
                    "currency_pair": market,
                    "last": bad_last,
                }
            ]

            return GateResponse(
                data=data,
                status_code=200,
                headers={},
                raw=data,
            )

        monkeypatch.setattr(
            FakeGateClient,
            "list_spot_tickers",
            non_finite_ticker,
        )

        monkeypatch.setattr(
            collector_module,
            "GateClient",
            FakeGateClient,
        )

        _patch_session_scope(
            monkeypatch,
            db,
        )

        summary = await (
            _collector()
            ._sync_live_account(
                _account(),
                now=datetime.now(
                    timezone.utc
                ),
            )
        )

        assert (
            summary["status"]
            == "success"
        )

        assert (
            summary["detail_errors"]
            == []
        )

        assert (
            FakeGateClient.ticker_calls
            == ["EQTY_USDT"]
        )

        db.expire_all()

        refreshed = db.scalar(
            select(Bot).where(
                Bot.strategy_id
                == "spot-a"
            )
        )

        assert refreshed is not None

        assert (
            refreshed.current_market_price
            is None
        )

        assert (
            refreshed.status
            == "running"
        )

        assert (
            refreshed.source_status
            == "running"
        )

        assert (
            bot_range_state(
                refreshed
            )
            == "unknown"
        )

    finally:
        db.close()
        engine.dispose()
