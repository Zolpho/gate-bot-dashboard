from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.alerts import evaluate_alerts
from app.db import Base
from app.models import (
    AlertEvent,
    AlertIncident,
    AlertRule,
    Bot,
    GateAccount,
)


def _session_factory(tmp_path, name: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        future=True,
    )

    Base.metadata.create_all(
        bind=engine,
    )

    Session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    return engine, Session


def _seed_pnl_rule(
    session,
    *,
    pnl: str = "-120",
):
    account = GateAccount(
        id="incident-evaluator",
        name="Incident evaluator",
    )

    session.add(account)
    session.flush()

    bot = Bot(
        account_id=account.id,
        strategy_id="grid-evaluator",
        strategy_type="spot_grid",
        strategy_name="Evaluator Grid",
        market="EQTY_USDT",
        status="running",
        total_profit=Decimal(pnl),
    )

    session.add(bot)
    session.flush()

    rule = AlertRule(
        name="Loss warning",
        metric="pnl",
        operator="<=",
        threshold=Decimal("-100"),
        bot_id=bot.id,
        enabled=True,
        cooldown_seconds=1,
    )

    session.add(rule)
    session.commit()

    return bot.id, rule.id


def _incident_rows(session, rule_id, bot_id):
    return list(
        session.scalars(
            select(AlertIncident)
            .where(
                AlertIncident.rule_id == rule_id,
                AlertIncident.bot_id == bot_id,
            )
            .order_by(
                AlertIncident.id.asc()
            )
        )
    )


def _event_rows(session, rule_id, bot_id):
    return list(
        session.scalars(
            select(AlertEvent)
            .where(
                AlertEvent.rule_id == rule_id,
                AlertEvent.bot_id == bot_id,
            )
            .order_by(
                AlertEvent.id.asc()
            )
        )
    )


def test_first_breach_opens_incident_and_one_event(
    tmp_path,
) -> None:
    engine, Session = _session_factory(
        tmp_path,
        "first-breach.db",
    )

    now = datetime.now(
        timezone.utc
    )

    with Session() as session:
        bot_id, rule_id = _seed_pnl_rule(
            session
        )

        created = evaluate_alerts(
            session,
            now=now,
        )

        assert len(created) == 1

        session.commit()

        incidents = _incident_rows(
            session,
            rule_id,
            bot_id,
        )

        events = _event_rows(
            session,
            rule_id,
            bot_id,
        )

        assert len(incidents) == 1
        assert len(events) == 1

        incident = incidents[0]

        assert incident.recovered_at is None

        assert (
            incident.trigger_value
            == Decimal("-120")
        )

        assert (
            incident.current_value
            == Decimal("-120")
        )

        assert (
            incident.worst_value
            == Decimal("-120")
        )

        assert (
            incident.last_notification_at
            is not None
        )

    engine.dispose()


def test_continuous_breach_updates_one_incident_without_duplicate_event(
    tmp_path,
) -> None:
    engine, Session = _session_factory(
        tmp_path,
        "continuous.db",
    )

    first_now = datetime.now(
        timezone.utc
    )

    with Session() as session:
        bot_id, rule_id = _seed_pnl_rule(
            session
        )

        first = evaluate_alerts(
            session,
            now=first_now,
        )

        assert len(first) == 1
        session.commit()

    # Far beyond the one-second cooldown. This must
    # still remain the same continuous incident.
    second_now = (
        first_now
        + timedelta(hours=2)
    )

    with Session() as session:
        bot = session.get(
            Bot,
            bot_id,
        )

        assert bot is not None

        bot.total_profit = Decimal(
            "-175"
        )

        session.commit()

    with Session() as session:
        second = evaluate_alerts(
            session,
            now=second_now,
        )

        assert second == []

        session.commit()

        incidents = _incident_rows(
            session,
            rule_id,
            bot_id,
        )

        events = _event_rows(
            session,
            rule_id,
            bot_id,
        )

        assert len(incidents) == 1
        assert len(events) == 1

        incident = incidents[0]

        assert (
            incident.current_value
            == Decimal("-175")
        )

        # <= means the lower value is worse.
        assert (
            incident.worst_value
            == Decimal("-175")
        )

        assert incident.recovered_at is None

    engine.dispose()


def test_recovery_closes_incident_without_creating_event(
    tmp_path,
) -> None:
    engine, Session = _session_factory(
        tmp_path,
        "recovery.db",
    )

    first_now = datetime.now(
        timezone.utc
    )

    with Session() as session:
        bot_id, rule_id = _seed_pnl_rule(
            session
        )

        assert len(
            evaluate_alerts(
                session,
                now=first_now,
            )
        ) == 1

        session.commit()

    recovered_now = (
        first_now
        + timedelta(minutes=30)
    )

    with Session() as session:
        bot = session.get(
            Bot,
            bot_id,
        )

        assert bot is not None

        bot.total_profit = Decimal(
            "-80"
        )

        session.commit()

    with Session() as session:
        created = evaluate_alerts(
            session,
            now=recovered_now,
        )

        assert created == []

        session.commit()

        incidents = _incident_rows(
            session,
            rule_id,
            bot_id,
        )

        events = _event_rows(
            session,
            rule_id,
            bot_id,
        )

        assert len(incidents) == 1
        assert len(events) == 1

        incident = incidents[0]

        assert incident.recovered_at is not None

        assert (
            incident.current_value
            == Decimal("-80")
        )

    engine.dispose()


def test_rebreach_after_recovery_opens_new_incident(
    tmp_path,
) -> None:
    engine, Session = _session_factory(
        tmp_path,
        "rebreach.db",
    )

    first_now = datetime.now(
        timezone.utc
    )

    with Session() as session:
        bot_id, rule_id = _seed_pnl_rule(
            session
        )

        assert len(
            evaluate_alerts(
                session,
                now=first_now,
            )
        ) == 1

        session.commit()

    with Session() as session:
        bot = session.get(
            Bot,
            bot_id,
        )

        assert bot is not None

        bot.total_profit = Decimal(
            "-75"
        )

        session.commit()

    with Session() as session:
        assert evaluate_alerts(
            session,
            now=(
                first_now
                + timedelta(minutes=20)
            ),
        ) == []

        session.commit()

    with Session() as session:
        bot = session.get(
            Bot,
            bot_id,
        )

        assert bot is not None

        bot.total_profit = Decimal(
            "-140"
        )

        session.commit()

    with Session() as session:
        created = evaluate_alerts(
            session,
            now=(
                first_now
                + timedelta(hours=1)
            ),
        )

        assert len(created) == 1

        session.commit()

        incidents = _incident_rows(
            session,
            rule_id,
            bot_id,
        )

        events = _event_rows(
            session,
            rule_id,
            bot_id,
        )

        assert len(incidents) == 2
        assert len(events) == 2

        assert (
            incidents[0].recovered_at
            is not None
        )

        assert (
            incidents[1].recovered_at
            is None
        )

    engine.dispose()


def test_acknowledgement_survives_recovery(
    tmp_path,
) -> None:
    engine, Session = _session_factory(
        tmp_path,
        "ack-recovery.db",
    )

    first_now = datetime.now(
        timezone.utc
    )

    with Session() as session:
        bot_id, rule_id = _seed_pnl_rule(
            session
        )

        evaluate_alerts(
            session,
            now=first_now,
        )

        session.commit()

        incident = _incident_rows(
            session,
            rule_id,
            bot_id,
        )[0]

        incident.acknowledged_at = (
            first_now
            + timedelta(minutes=2)
        )

        incident.acknowledged_by = (
            "operator"
        )

        session.commit()

    with Session() as session:
        bot = session.get(
            Bot,
            bot_id,
        )

        assert bot is not None

        bot.total_profit = Decimal(
            "-50"
        )

        session.commit()

    with Session() as session:
        evaluate_alerts(
            session,
            now=(
                first_now
                + timedelta(minutes=5)
            ),
        )

        session.commit()

        incident = _incident_rows(
            session,
            rule_id,
            bot_id,
        )[0]

        assert incident.recovered_at is not None

        assert incident.acknowledged_at is not None

        assert (
            incident.acknowledged_by
            == "operator"
        )

    engine.dispose()


def test_stale_fresh_observation_splits_incidents_even_without_fresh_evaluation(
    tmp_path,
) -> None:
    engine, Session = _session_factory(
        tmp_path,
        "stale-cycle.db",
    )

    first_now = datetime.now(
        timezone.utc
    )

    with Session() as session:
        account = GateAccount(
            id="stale-incident",
            name="Stale incident",
        )

        session.add(account)
        session.flush()

        bot = Bot(
            account_id=account.id,
            strategy_id="stale-grid",
            strategy_type="spot_grid",
            strategy_name="Stale Grid",
            market="EQTY_USDT",
            status="running",
            last_seen_at=(
                first_now
                - timedelta(minutes=10)
            ),
        )

        session.add(bot)
        session.flush()

        rule = AlertRule(
            name="Stale data",
            metric="stale_minutes",
            operator=">=",
            threshold=Decimal("5"),
            bot_id=bot.id,
            enabled=True,
            cooldown_seconds=3600,
        )

        session.add(rule)
        session.commit()

        bot_id = bot.id
        rule_id = rule.id

    with Session() as session:
        first = evaluate_alerts(
            session,
            now=first_now,
        )

        assert len(first) == 1

        session.commit()

    # A genuinely fresh Gate observation occurred one
    # minute after the first stale incident opened.
    # No evaluator call happens at this exact moment.
    fresh_seen = (
        first_now
        + timedelta(minutes=1)
    )

    with Session() as session:
        bot = session.get(
            Bot,
            bot_id,
        )

        assert bot is not None

        bot.last_seen_at = fresh_seen
        session.commit()

    # Six minutes later the same bot is stale again.
    second_now = (
        first_now
        + timedelta(minutes=7)
    )

    with Session() as session:
        second = evaluate_alerts(
            session,
            now=second_now,
        )

        assert len(second) == 1

        session.commit()

        incidents = _incident_rows(
            session,
            rule_id,
            bot_id,
        )

        events = _event_rows(
            session,
            rule_id,
            bot_id,
        )

        assert len(incidents) == 2
        assert len(events) == 2

        assert (
            incidents[0].recovered_at
            is not None
        )

        assert (
            incidents[1].recovered_at
            is None
        )

    engine.dispose()


def test_stopped_bot_recovers_open_stale_incident(
    tmp_path,
) -> None:
    engine, Session = _session_factory(
        tmp_path,
        "stopped-stale.db",
    )

    first_now = datetime.now(
        timezone.utc
    )

    with Session() as session:
        account = GateAccount(
            id="stopped-stale",
            name="Stopped stale",
        )

        session.add(account)
        session.flush()

        bot = Bot(
            account_id=account.id,
            strategy_id="stopped-stale-grid",
            strategy_type="spot_grid",
            strategy_name="Stopped Stale Grid",
            market="EQTY_USDT",
            status="running",
            last_seen_at=(
                first_now
                - timedelta(minutes=10)
            ),
        )

        session.add(bot)
        session.flush()

        rule = AlertRule(
            name="Stale data",
            metric="stale_minutes",
            operator=">=",
            threshold=Decimal("5"),
            bot_id=bot.id,
            enabled=True,
        )

        session.add(rule)
        session.commit()

        bot_id = bot.id
        rule_id = rule.id

    with Session() as session:
        assert len(
            evaluate_alerts(
                session,
                now=first_now,
            )
        ) == 1

        session.commit()

    with Session() as session:
        bot = session.get(
            Bot,
            bot_id,
        )

        assert bot is not None

        bot.status = "stopped"
        session.commit()

    with Session() as session:
        created = evaluate_alerts(
            session,
            now=(
                first_now
                + timedelta(minutes=1)
            ),
        )

        assert created == []

        session.commit()

        incident = _incident_rows(
            session,
            rule_id,
            bot_id,
        )[0]

        assert incident.recovered_at is not None

        assert len(
            _event_rows(
                session,
                rule_id,
                bot_id,
            )
        ) == 1

    engine.dispose()
