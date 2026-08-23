from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.migrations import migrate_database
from app.models import (
    AlertEvent,
    AlertIncident,
    AlertRule,
    Bot,
    GateAccount,
)


def _engine(tmp_path, name: str):
    return create_engine(
        f"sqlite:///{tmp_path / name}",
        future=True,
    )


def _seed_rule_and_bot(session):
    account = GateAccount(
        id="incident-account",
        name="Incident account",
    )
    session.add(account)
    session.flush()

    bot = Bot(
        account_id=account.id,
        strategy_id="incident-grid",
        strategy_type="spot_grid",
        strategy_name="Incident Grid",
        market="EQTY_USDT",
        status="running",
    )
    session.add(bot)
    session.flush()

    rule = AlertRule(
        name="Drawdown warning",
        metric="drawdown_pct",
        operator=">=",
        threshold=Decimal("12"),
        enabled=True,
        cooldown_seconds=3600,
    )
    session.add(rule)
    session.flush()

    return bot, rule


def _incident(
    *,
    rule_id: int,
    bot_id: int,
    opened_at: datetime,
) -> AlertIncident:
    return AlertIncident(
        rule_id=rule_id,
        bot_id=bot_id,
        rule_name="Drawdown warning",
        metric="drawdown_pct",
        operator=">=",
        threshold_value=Decimal("12"),
        trigger_value=Decimal("12.25"),
        current_value=Decimal("14.50"),
        worst_value=Decimal("14.50"),
        opened_at=opened_at,
        last_observed_at=opened_at,
        message="Drawdown threshold breached.",
    )


def test_new_schema_contains_alert_incident_table(
    tmp_path,
) -> None:
    engine = _engine(
        tmp_path,
        "incident-new.db",
    )

    Base.metadata.create_all(
        bind=engine,
    )

    inspector = inspect(engine)

    assert (
        "alert_incidents"
        in inspector.get_table_names()
    )

    columns = {
        item["name"]
        for item in inspector.get_columns(
            "alert_incidents"
        )
    }

    assert {
        "id",
        "rule_id",
        "bot_id",
        "rule_name",
        "metric",
        "operator",
        "threshold_value",
        "trigger_value",
        "current_value",
        "worst_value",
        "opened_at",
        "last_observed_at",
        "recovered_at",
        "acknowledged_at",
        "acknowledged_by",
        "last_notification_at",
        "message",
        "updated_at",
    }.issubset(columns)

    indexes = {
        item["name"]
        for item in inspector.get_indexes(
            "alert_incidents"
        )
    }

    assert (
        "uq_alert_incident_open_rule_bot"
        in indexes
    )

    assert (
        "ix_alert_incident_rule_bot_opened"
        in indexes
    )

    engine.dispose()


def test_existing_database_migration_creates_incidents(
    tmp_path,
) -> None:
    engine = _engine(
        tmp_path,
        "incident-migration.db",
    )

    # Simulate the currently deployed schema:
    # parent alert tables exist, incident table does not.
    GateAccount.__table__.create(
        bind=engine,
    )
    Bot.__table__.create(
        bind=engine,
    )
    AlertRule.__table__.create(
        bind=engine,
    )
    AlertEvent.__table__.create(
        bind=engine,
    )

    assert (
        "alert_incidents"
        not in inspect(engine).get_table_names()
    )

    migrate_database(engine)

    assert (
        "alert_incidents"
        in inspect(engine).get_table_names()
    )

    # Built-in migration must remain idempotent.
    migrate_database(engine)

    assert (
        "alert_incidents"
        in inspect(engine).get_table_names()
    )

    with engine.connect() as connection:
        violations = connection.exec_driver_sql(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert violations == []

    engine.dispose()


def test_only_one_open_incident_per_rule_and_bot(
    tmp_path,
) -> None:
    engine = _engine(
        tmp_path,
        "incident-unique.db",
    )

    Base.metadata.create_all(
        bind=engine,
    )

    Session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    opened_at = datetime.now(
        timezone.utc,
    )

    with Session() as session:
        bot, rule = _seed_rule_and_bot(
            session
        )

        first = _incident(
            rule_id=rule.id,
            bot_id=bot.id,
            opened_at=opened_at,
        )

        session.add(first)
        session.commit()

        first_id = first.id
        rule_id = rule.id
        bot_id = bot.id

    with Session() as session:
        duplicate = _incident(
            rule_id=rule_id,
            bot_id=bot_id,
            opened_at=(
                opened_at
                + timedelta(minutes=5)
            ),
        )

        session.add(duplicate)

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    with Session() as session:
        first = session.get(
            AlertIncident,
            first_id,
        )

        assert first is not None

        first.recovered_at = (
            opened_at
            + timedelta(hours=1)
        )

        first.current_value = Decimal("11.5")
        first.last_observed_at = first.recovered_at

        session.commit()

    # Once the first lifecycle is recovered, a later
    # breach may open a new incident for the same pair.
    with Session() as session:
        second = _incident(
            rule_id=rule_id,
            bot_id=bot_id,
            opened_at=(
                opened_at
                + timedelta(hours=2)
            ),
        )

        session.add(second)
        session.commit()

        assert second.id != first_id

    engine.dispose()


def test_incident_acknowledgement_is_independent_from_recovery(
    tmp_path,
) -> None:
    engine = _engine(
        tmp_path,
        "incident-lifecycle.db",
    )

    Base.metadata.create_all(
        bind=engine,
    )

    Session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    opened_at = datetime.now(
        timezone.utc,
    )

    with Session() as session:
        bot, rule = _seed_rule_and_bot(
            session
        )

        incident = _incident(
            rule_id=rule.id,
            bot_id=bot.id,
            opened_at=opened_at,
        )

        session.add(incident)
        session.commit()

        incident.acknowledged_at = (
            opened_at
            + timedelta(minutes=10)
        )

        incident.acknowledged_by = (
            "incident-operator"
        )

        session.commit()

        assert incident.acknowledged_at is not None
        assert incident.recovered_at is None

        incident.current_value = Decimal("10")
        incident.recovered_at = (
            opened_at
            + timedelta(minutes=30)
        )
        incident.last_observed_at = (
            incident.recovered_at
        )

        session.commit()

        assert incident.acknowledged_at is not None
        assert incident.recovered_at is not None

    engine.dispose()


def test_incident_tracks_trigger_current_and_worst_values(
    tmp_path,
) -> None:
    engine = _engine(
        tmp_path,
        "incident-values.db",
    )

    Base.metadata.create_all(
        bind=engine,
    )

    Session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    opened_at = datetime.now(
        timezone.utc,
    )

    with Session() as session:
        bot, rule = _seed_rule_and_bot(
            session
        )

        incident = _incident(
            rule_id=rule.id,
            bot_id=bot.id,
            opened_at=opened_at,
        )

        incident.trigger_value = Decimal(
            "12.25"
        )

        incident.current_value = Decimal(
            "17.86"
        )

        incident.worst_value = Decimal(
            "19.17"
        )

        session.add(incident)
        session.commit()

        stored = session.get(
            AlertIncident,
            incident.id,
        )

        assert stored is not None

        assert stored.trigger_value == Decimal(
            "12.25"
        )

        assert stored.current_value == Decimal(
            "17.86"
        )

        assert stored.worst_value == Decimal(
            "19.17"
        )

        assert stored.threshold_value == Decimal(
            "12"
        )

    engine.dispose()
