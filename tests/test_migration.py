from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.db import Base
from app.migrations import migrate_database


def test_v1_sqlite_schema_migrates_to_account_aware_schema(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "v1.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            """
            CREATE TABLE bots (
                id INTEGER PRIMARY KEY,
                strategy_id VARCHAR(128) NOT NULL,
                strategy_type VARCHAR(64) NOT NULL,
                strategy_name VARCHAR(255) NOT NULL DEFAULT '',
                first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(strategy_id, strategy_type)
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE bot_snapshots (
                id INTEGER PRIMARY KEY,
                bot_id INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
                captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE sync_runs (
                id INTEGER PRIMARY KEY,
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(32) NOT NULL DEFAULT 'running',
                bot_count INTEGER NOT NULL DEFAULT 0,
                detail_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                raw_summary_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO bots(id, strategy_id, strategy_type, strategy_name) VALUES (1, '42', 'spot_grid', 'Old bot')"
        )
        connection.exec_driver_sql("INSERT INTO bot_snapshots(id, bot_id) VALUES (1, 1)")

    migrate_database(engine)
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "account_id" in {column["name"] for column in inspector.get_columns("bots")}
    assert "trigger" in {column["name"] for column in inspector.get_columns("sync_runs")}

    with engine.begin() as connection:
        migrated = connection.execute(
            text("SELECT id, account_id, strategy_id, strategy_type FROM bots")
        ).mappings().one()
        assert migrated == {
            "id": 1,
            "account_id": "legacy",
            "strategy_id": "42",
            "strategy_type": "spot_grid",
        }
        assert connection.execute(text("SELECT COUNT(*) FROM bot_snapshots")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []

        connection.execute(
            text(
                """
                INSERT INTO gate_accounts
                    (id, name, account_type, gate_uid, enabled, configured, sync_status,
                     last_error, bot_count, created_at, updated_at)
                VALUES
                    ('second', 'Second', 'subaccount', '', 1, 1, 'never', '', 0,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        # The same Gate strategy identifier is valid in another account.
        connection.execute(
            text(
                """
                INSERT INTO bots
                    (account_id, strategy_id, strategy_type, strategy_name, market, status,
                     source_status, price_range, position_side, stop_supported, missing_syncs,
                     first_seen_at, last_seen_at, updated_at, raw_list_json, raw_detail_json)
                VALUES
                    ('second', '42', 'spot_grid', 'Other account bot', '', 'running', '', '', '',
                     0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '{}', '{}')
                """
            )
        )
        assert connection.execute(text("SELECT COUNT(*) FROM bots")).scalar_one() == 2
