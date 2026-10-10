from __future__ import annotations

import sqlite3
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import (
    create_engine,
    inspect,
    select,
)
from sqlalchemy.orm import sessionmaker

from app.donation_ledger import (
    DonationLedgerInvariantError,
    SOURCE_DEMO,
    SOURCE_EXTERNAL_DEPOSIT,
    SOURCE_INTERNAL_TRANSFER,
    create_donation_intent,
    demo_source_key,
    donation_intent_claim_matches,
    ensure_donation_event,
    external_deposit_source_key,
    internal_transfer_source_key,
)
from app.migrations import migrate_database
from app.models import (
    DonationAttribution,
    DonationEvent,
    DonationIntent,
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
    )

    DonationEvent.__table__.create(
        engine
    )

    DonationAttribution.__table__.create(
        engine
    )

    DonationIntent.__table__.create(
        engine
    )

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return engine, factory()


def test_donation_models_separate_financial_fact_from_attribution() -> None:
    event_columns = {
        column.name
        for column in DonationEvent.__table__.columns
    }

    attribution_columns = {
        column.name
        for column
        in DonationAttribution.__table__.columns
    }

    intent_columns = {
        column.name
        for column in DonationIntent.__table__.columns
    }

    assert {
        "event_id",
        "source_type",
        "source_key",
        "currency",
        "chain_key",
        "chain",
        "amount",
        "occurred_at",
        "demo",
    }.issubset(
        event_columns
    )

    assert not {
        "address",
        "memo",
        "txid",
        "gate_deposit_id",
        "account_id",
        "username",
        "nickname",
        "telegram_handle",
        "x_handle",
    } & event_columns

    assert {
        "event_id",
        "display_mode",
        "nickname",
        "telegram_handle",
        "x_handle",
    }.issubset(
        attribution_columns
    )

    assert not {
        "verified",
        "telegram_verified",
        "x_verified",
    } & attribution_columns

    assert {
        "intent_id",
        "claim_token_hash",
        "currency",
        "chain_key",
        "chain",
        "submitted_txid",
        "status",
        "matched_event_id",
        "expires_at",
    }.issubset(
        intent_columns
    )

    assert "claim_token" not in intent_columns


def test_external_event_is_idempotent_and_immutable() -> None:
    engine, db = _session()

    try:
        source_key = (
            external_deposit_source_key(
                "eqtydao",
                "gate-deposit-123",
            )
        )

        occurred = datetime(
            2026,
            10,
            10,
            8,
            0,
            tzinfo=timezone.utc,
        )

        first, created = ensure_donation_event(
            db,
            source_type=SOURCE_EXTERNAL_DEPOSIT,
            source_key=source_key,
            currency="eqty",
            chain_key="baseevm",
            chain="Base",
            amount=Decimal(
                "1.234567890123456789012345"
            ),
            occurred_at=occurred,
            demo=False,
        )

        replay, replay_created = (
            ensure_donation_event(
                db,
                source_type=SOURCE_EXTERNAL_DEPOSIT,
                source_key=source_key,
                currency="EQTY",
                chain_key="BASEEVM",
                chain="Base",
                amount=(
                    "1.234567890123456789012345"
                ),
                occurred_at=occurred,
                demo=False,
            )
        )

        assert created is True
        assert replay_created is False
        assert (
            replay["event_id"]
            == first["event_id"]
        )

        count = len(
            db.scalars(
                select(
                    DonationEvent
                )
            ).all()
        )

        assert count == 1

        with pytest.raises(
            DonationLedgerInvariantError,
            match="conflicts",
        ):
            ensure_donation_event(
                db,
                source_type=SOURCE_EXTERNAL_DEPOSIT,
                source_key=source_key,
                currency="EQTY",
                chain_key="BASEEVM",
                chain="Base",
                amount="2",
                occurred_at=occurred,
                demo=False,
            )

    finally:
        db.close()
        engine.dispose()


def test_source_identity_builders_fail_closed() -> None:
    with pytest.raises(
        DonationLedgerInvariantError,
        match="eqtydao",
    ):
        external_deposit_source_key(
            "zolnode",
            "123",
        )

    assert (
        internal_transfer_source_key(
            "req-123"
        )
        == "request:req-123"
    )

    assert (
        demo_source_key(
            "demo-123"
        )
        == "demo:demo-123"
    )


def test_demo_and_real_source_types_cannot_be_confused() -> None:
    engine, db = _session()

    try:
        now = datetime.now(
            timezone.utc
        )

        with pytest.raises(
            DonationLedgerInvariantError,
            match="must agree",
        ):
            ensure_donation_event(
                db,
                source_type=SOURCE_DEMO,
                source_key=demo_source_key(
                    "one"
                ),
                currency="EQTY",
                amount="1",
                occurred_at=now,
                demo=False,
            )

        with pytest.raises(
            DonationLedgerInvariantError,
            match="must agree",
        ):
            ensure_donation_event(
                db,
                source_type=SOURCE_INTERNAL_TRANSFER,
                source_key=(
                    internal_transfer_source_key(
                        "req"
                    )
                ),
                currency="USDT",
                amount="1",
                occurred_at=now,
                demo=True,
            )

    finally:
        db.close()
        engine.dispose()


def test_event_amount_must_be_positive_exact_decimal() -> None:
    engine, db = _session()

    try:
        now = datetime.now(
            timezone.utc
        )

        for value in (
            "0",
            "-1",
            "nan",
            "inf",
        ):
            with pytest.raises(
                DonationLedgerInvariantError,
            ):
                ensure_donation_event(
                    db,
                    source_type=SOURCE_INTERNAL_TRANSFER,
                    source_key=(
                        internal_transfer_source_key(
                            "req-" + value
                        )
                    ),
                    currency="USDT",
                    amount=value,
                    occurred_at=now,
                    demo=False,
                )

    finally:
        db.close()
        engine.dispose()


def test_intent_stores_only_claim_hash() -> None:
    engine, db = _session()

    try:
        now = datetime(
            2026,
            10,
            10,
            9,
            0,
            tzinfo=timezone.utc,
        )

        public, raw_claim = (
            create_donation_intent(
                db,
                currency="eqty",
                chain_key="baseevm",
                chain="Base",
                expires_at=(
                    now
                    + timedelta(
                        minutes=30
                    )
                ),
                now=now,
            )
        )

        row = db.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == public["intent_id"]
            )
        )

        assert row is not None

        assert (
            row.claim_token_hash
            != raw_claim
        )

        assert len(
            row.claim_token_hash
        ) == 64

        assert raw_claim not in (
            row.claim_token_hash,
            row.intent_id,
            row.submitted_txid,
        )

        assert (
            donation_intent_claim_matches(
                row,
                raw_claim,
            )
            is True
        )

        assert (
            donation_intent_claim_matches(
                row,
                raw_claim + "wrong",
            )
            is False
        )

        assert (
            "claim_token_hash"
            not in public
        )

    finally:
        db.close()
        engine.dispose()


def test_migration_creates_empty_foundation_without_historical_backfill(
    tmp_path: Path,
) -> None:
    db_path = (
        tmp_path
        / "legacy.db"
    )

    raw = sqlite3.connect(
        db_path
    )

    try:
        raw.execute(
            """
            CREATE TABLE gate_accounts (
                id VARCHAR(64) PRIMARY KEY
            )
            """
        )

        raw.execute(
            """
            INSERT INTO gate_accounts (id)
            VALUES ('eqtydao')
            """
        )

        raw.execute(
            """
            CREATE TABLE deposit_records (
                id INTEGER PRIMARY KEY,
                account_id VARCHAR(64) NOT NULL,
                gate_deposit_id VARCHAR(128) NOT NULL,
                txid TEXT NOT NULL DEFAULT '',
                currency VARCHAR(32) NOT NULL,
                chain VARCHAR(64) NOT NULL DEFAULT '',
                amount TEXT NOT NULL,
                status VARCHAR(32) NOT NULL,
                deposited_at DATETIME NOT NULL
            )
            """
        )

        raw.execute(
            """
            INSERT INTO deposit_records (
                account_id,
                gate_deposit_id,
                txid,
                currency,
                chain,
                amount,
                status,
                deposited_at
            )
            VALUES (
                'eqtydao',
                'historical-1',
                'historical-txid',
                'EQTY',
                'BASEEVM',
                '10',
                'DONE',
                '2026-07-30 19:56:15'
            )
            """
        )

        raw.commit()

    finally:
        raw.close()

    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
    )

    try:
        migrate_database(
            engine
        )

        inspector = inspect(
            engine
        )

        tables = set(
            inspector.get_table_names()
        )

        assert {
            "donation_events",
            "donation_attributions",
            "donation_intents",
        }.issubset(
            tables
        )

        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    """
                    SELECT COUNT(*)
                    FROM donation_events
                    """
                ).scalar_one()
                == 0
            )

            assert (
                connection.exec_driver_sql(
                    """
                    SELECT COUNT(*)
                    FROM donation_attributions
                    """
                ).scalar_one()
                == 0
            )

            assert (
                connection.exec_driver_sql(
                    """
                    SELECT COUNT(*)
                    FROM donation_intents
                    """
                ).scalar_one()
                == 0
            )

            assert (
                connection.exec_driver_sql(
                    """
                    SELECT COUNT(*)
                    FROM deposit_records
                    WHERE account_id='eqtydao'
                    """
                ).scalar_one()
                == 1
            )

            assert (
                connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                == []
            )

    finally:
        engine.dispose()
