from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.alerts import evaluate_alerts
from app.collector import BotCollector
from app.db import init_db, session_scope
from app.main import app

# This module is also intended to run standalone.
# Do not depend on another test creating the test database schema first.
init_db()
from app.models import AlertEvent, AlertRule, Bot, GateAccount


def _create_stale_bot(
    *,
    status: str = "running",
    stale_minutes: int = 10,
) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:10]
    account_id = f"alert-test-{suffix}"
    strategy_id = f"strategy-{suffix}"
    now = datetime.now(timezone.utc)
    last_seen = now - timedelta(minutes=stale_minutes)

    with session_scope() as session:
        session.add(
            GateAccount(
                id=account_id,
                name=account_id,
            )
        )
        session.flush()

        bot = Bot(
            account_id=account_id,
            strategy_id=strategy_id,
            strategy_type="spot_grid",
            strategy_name="Reliability Test Grid",
            market="EQTY_USDT",
            status=status,
            first_seen_at=last_seen,
            last_seen_at=last_seen,
        )
        session.add(bot)
        session.flush()

        rule = AlertRule(
            name=f"Stale test {suffix}",
            metric="stale_minutes",
            operator=">=",
            threshold=Decimal("5"),
            bot_id=bot.id,
            enabled=True,
            cooldown_seconds=3600,
        )
        session.add(rule)
        session.flush()

        return bot.id, rule.id


def test_stopped_bot_does_not_generate_stale_alert() -> None:
    bot_id, rule_id = _create_stale_bot(status="stopped")

    with session_scope() as session:
        events = evaluate_alerts(
            session,
            now=datetime.now(timezone.utc),
        )

        ours = [
            event
            for event in events
            if event.rule_id == rule_id
            and event.bot_id == bot_id
        ]

        assert ours == []


def test_running_stale_bot_generates_one_clean_alert() -> None:
    bot_id, rule_id = _create_stale_bot(
        status="running",
        stale_minutes=10,
    )

    now = datetime.now(timezone.utc)

    with session_scope() as session:
        events = evaluate_alerts(
            session,
            now=now,
        )

        ours = [
            event
            for event in events
            if event.rule_id == rule_id
            and event.bot_id == bot_id
        ]

        assert len(ours) == 1

        event = ours[0]
        bot = session.get(Bot, bot_id)
        assert bot is not None

        assert f"Strategy {bot.strategy_id}" in event.message
        assert "data stale for " in event.message
        assert "threshold >= 5 min" in event.message
        assert ".0000 min" not in event.message


def test_same_stale_incident_is_not_repeated_after_cooldown() -> None:
    bot_id, rule_id = _create_stale_bot(
        status="running",
        stale_minutes=10,
    )

    first_now = datetime.now(timezone.utc)

    with session_scope() as session:
        first = evaluate_alerts(
            session,
            now=first_now,
        )
        assert len(
            [
                event
                for event in first
                if event.rule_id == rule_id
                and event.bot_id == bot_id
            ]
        ) == 1

        # session_scope uses an explicit-flush transaction model.
        # Persist the first incident before evaluating it again.
        session.flush()

        # Much longer than the normal 3600-second cooldown.
        second = evaluate_alerts(
            session,
            now=first_now + timedelta(hours=2),
        )

        assert [
            event
            for event in second
            if event.rule_id == rule_id
            and event.bot_id == bot_id
        ] == []

        stored = list(
            session.scalars(
                select(AlertEvent).where(
                    AlertEvent.rule_id == rule_id,
                    AlertEvent.bot_id == bot_id,
                )
            )
        )
        assert len(stored) == 1


def test_fresh_observation_allows_new_later_stale_incident() -> None:
    bot_id, rule_id = _create_stale_bot(
        status="running",
        stale_minutes=10,
    )

    first_now = datetime.now(timezone.utc)

    with session_scope() as session:
        first = evaluate_alerts(
            session,
            now=first_now,
        )
        assert len(
            [
                event
                for event in first
                if event.rule_id == rule_id
                and event.bot_id == bot_id
            ]
        ) == 1

        # Persist the first stale incident before simulating recovery.
        session.flush()

        bot = session.get(Bot, bot_id)
        assert bot is not None

        # Data becomes fresh after the first stale incident.
        bot.last_seen_at = first_now + timedelta(minutes=1)
        session.flush()

        # Then the bot becomes stale again later.
        second_now = first_now + timedelta(minutes=7)
        second = evaluate_alerts(
            session,
            now=second_now,
        )

        ours = [
            event
            for event in second
            if event.rule_id == rule_id
            and event.bot_id == bot_id
        ]
        assert len(ours) == 1

        # Persist the newly-created second incident before counting rows.
        session.flush()

        stored = list(
            session.scalars(
                select(AlertEvent).where(
                    AlertEvent.rule_id == rule_id,
                    AlertEvent.bot_id == bot_id,
                )
            )
        )
        assert len(stored) == 2


def test_collector_sync_handles_start_run_failure(
    monkeypatch,
) -> None:
    collector = BotCollector()

    def fail_start_run(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated SyncRun database failure")

    monkeypatch.setattr(
        collector,
        "_start_run",
        fail_start_run,
    )

    result = asyncio.run(
        collector.sync(trigger="scheduler")
    )

    assert result["status"] == "error"
    assert (
        result["error"]
        == "simulated SyncRun database failure"
    )


def test_health_is_degraded_when_collector_task_is_dead() -> None:
    class DeadTask:
        @staticmethod
        def done() -> bool:
            return True

    with TestClient(app) as client:
        original_task = app.state.collection_task

        try:
            app.state.collection_task = DeadTask()

            response = client.get("/api/health")
            assert response.status_code == 200

            payload = response.json()

            assert payload["status"] == "degraded"
            assert payload["collector_running"] is False
            assert payload["collector_healthy"] is False
            assert (
                "collection_freshness_limit_seconds"
                in payload
            )
            assert "last_collection_success_at" in payload
        finally:
            app.state.collection_task = original_task
