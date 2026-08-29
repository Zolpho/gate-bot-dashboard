from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.schema import CreateIndex, CreateTable

logger = logging.getLogger(__name__)


from .exact_decimal import exact_decimal_text


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _compile_ddl(engine: Engine, statement: Any) -> str:
    return str(statement.compile(dialect=engine.dialect))


def _create_table(raw_connection: Any, engine: Engine, table: Any) -> None:
    cursor = raw_connection.cursor()
    cursor.execute(_compile_ddl(engine, CreateTable(table)))
    for index in sorted(table.indexes, key=lambda item: item.name or ""):
        cursor.execute(_compile_ddl(engine, CreateIndex(index)))


def _drop_named_indexes(raw_connection: Any, table_name: str) -> None:
    rows = raw_connection.execute(f"PRAGMA index_list({_quote(table_name)})").fetchall()
    for row in rows:
        # PRAGMA index_list: seq, name, unique, origin, partial
        name = str(row[1])
        origin = str(row[3]) if len(row) > 3 else ""
        if origin == "c" and name and not name.startswith("sqlite_autoindex"):
            raw_connection.execute(f"DROP INDEX IF EXISTS {_quote(name)}")


def _table_columns(raw_connection: Any, table_name: str) -> list[str]:
    return [str(row[1]) for row in raw_connection.execute(f"PRAGMA table_info({_quote(table_name)})")]


def _table_exists(raw_connection: Any, table_name: str) -> bool:
    row = raw_connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def _rebuild_table(
    raw_connection: Any,
    engine: Engine,
    table: Any,
    *,
    fill_expressions: dict[str, str] | None = None,
) -> None:
    fill_expressions = fill_expressions or {}
    table_name = table.name
    old_name = f"{table_name}__schema_v1"

    if _table_exists(raw_connection, old_name):
        raw_connection.execute(f"DROP TABLE {_quote(old_name)}")

    _drop_named_indexes(raw_connection, table_name)
    raw_connection.execute(f"ALTER TABLE {_quote(table_name)} RENAME TO {_quote(old_name)}")
    _create_table(raw_connection, engine, table)

    old_columns = set(_table_columns(raw_connection, old_name))
    target_columns: list[str] = []
    select_expressions: list[str] = []
    for column in table.columns:
        name = column.name
        if name in old_columns:
            expression = _quote(name)
        elif name in fill_expressions:
            expression = fill_expressions[name]
        elif column.nullable:
            expression = "NULL"
        else:
            default = getattr(column.default, "arg", None) if column.default is not None else None
            if isinstance(default, bool):
                expression = "1" if default else "0"
            elif isinstance(default, int):
                expression = str(default)
            elif isinstance(default, str):
                expression = "'" + default.replace("'", "''") + "'"
            elif callable(default) and column.type.python_type is datetime:
                expression = "CURRENT_TIMESTAMP"
            else:
                raise RuntimeError(
                    f"Cannot migrate {table_name}: no source/default for required column {name}"
                )
        target_columns.append(_quote(name))
        select_expressions.append(expression)

    raw_connection.execute(
        f"INSERT INTO {_quote(table_name)} ({', '.join(target_columns)}) "
        f"SELECT {', '.join(select_expressions)} FROM {_quote(old_name)}"
    )
    raw_connection.execute(f"DROP TABLE {_quote(old_name)}")


def _declared_column_type(
    raw_connection: Any,
    table_name: str,
    column_name: str,
) -> str:
    rows = raw_connection.execute(
        f"PRAGMA table_info({_quote(table_name)})"
    ).fetchall()

    for row in rows:
        if str(row[1]) == column_name:
            return str(row[2] or "").upper()

    raise RuntimeError(
        f"Missing column {table_name}.{column_name}"
    )


def _json_object(
    value: Any,
    *,
    context: str,
) -> dict[str, Any]:
    try:
        parsed = json.loads(
            str(value or "{}")
        )
    except Exception as exc:
        raise RuntimeError(
            f"Invalid immutable JSON for {context}"
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"Immutable JSON for {context} "
            "is not an object"
        )

    return parsed


def _legacy_decimal_matches(
    legacy_value: Any,
    canonical_text: str,
    *,
    context: str,
) -> None:
    try:
        legacy_decimal = Decimal(
            str(legacy_value)
        )

        canonical_decimal = Decimal(
            canonical_text
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            f"Cannot validate legacy Treasury "
            f"decimal for {context}"
        ) from exc

    if (
        not legacy_decimal.is_finite()
        or not canonical_decimal.is_finite()
        or legacy_decimal
        != canonical_decimal
    ):
        raise RuntimeError(
            "Treasury exact-decimal migration "
            f"mismatch for {context}: "
            f"legacy={legacy_value!r}, "
            f"canonical={canonical_text!r}"
        )


def _canonical_transfer_amount(
    request_json: Any,
    *,
    request_id: str,
) -> str:
    payload = _json_object(
        request_json,
        context=(
            f"transfer request {request_id}"
        ),
    )

    value = payload.get("amount")

    if value is None:
        gate_payload = payload.get(
            "gate_payload"
        )

        if isinstance(gate_payload, dict):
            value = gate_payload.get(
                "amount"
            )

    if value is None:
        raise RuntimeError(
            "Treasury exact-decimal migration "
            "cannot find canonical transfer amount "
            f"for {request_id}"
        )

    return exact_decimal_text(value)


def _canonical_withdrawal_values(
    *,
    request_id: str,
    request_json: Any,
    preflight_json: Any,
) -> dict[str, str]:
    request = _json_object(
        request_json,
        context=(
            f"withdrawal request {request_id}"
        ),
    )

    preflight = _json_object(
        preflight_json,
        context=(
            f"withdrawal preflight {request_id}"
        ),
    )

    fee = preflight.get("fee")
    funding = preflight.get("funding")

    if not isinstance(fee, dict):
        raise RuntimeError(
            "Treasury exact-decimal migration "
            f"missing fee snapshot for {request_id}"
        )

    if not isinstance(funding, dict):
        raise RuntimeError(
            "Treasury exact-decimal migration "
            f"missing funding snapshot for {request_id}"
        )

    sources = {
        "amount": request.get("amount"),
        "estimated_fee": (
            fee.get("estimated_fee")
        ),
        "conservative_funding_required": (
            funding.get(
                "conservative_funding_required"
            )
        ),
        "minimum_jit_transfer": (
            funding.get(
                "minimum_jit_transfer"
            )
        ),
    }

    result: dict[str, str] = {}

    for column, value in sources.items():
        if value is None:
            raise RuntimeError(
                "Treasury exact-decimal migration "
                f"missing {column} canonical value "
                f"for {request_id}"
            )

        result[column] = (
            exact_decimal_text(value)
        )

    return result


def _migrate_transfer_exact_decimal(
    raw_connection: Any,
    engine: Engine,
    table: Any,
) -> None:
    table_name = "treasury_transfer_requests"

    if not _table_exists(
        raw_connection,
        table_name,
    ):
        return

    if (
        _declared_column_type(
            raw_connection,
            table_name,
            "amount",
        )
        == "TEXT"
    ):
        return

    rows = raw_connection.execute(
        """
        SELECT
            request_id,
            amount,
            request_json
        FROM treasury_transfer_requests
        ORDER BY id
        """
    ).fetchall()

    canonical: dict[str, str] = {}

    for row in rows:
        request_id = str(row[0])

        amount = _canonical_transfer_amount(
            row[2],
            request_id=request_id,
        )

        _legacy_decimal_matches(
            row[1],
            amount,
            context=(
                f"transfer {request_id}.amount"
            ),
        )

        canonical[request_id] = amount

    logger.info(
        "Migrating Treasury transfer amounts "
        "to exact SQLite TEXT decimals"
    )

    _rebuild_table(
        raw_connection,
        engine,
        table,
    )

    for request_id, amount in canonical.items():
        raw_connection.execute(
            """
            UPDATE treasury_transfer_requests
            SET amount=?
            WHERE request_id=?
            """,
            (
                amount,
                request_id,
            ),
        )


def _migrate_withdrawal_exact_decimals(
    raw_connection: Any,
    engine: Engine,
    table: Any,
) -> None:
    table_name = "treasury_withdrawal_requests"

    columns = (
        "amount",
        "estimated_fee",
        "conservative_funding_required",
        "minimum_jit_transfer",
    )

    if not _table_exists(
        raw_connection,
        table_name,
    ):
        return

    declared_types = {
        _declared_column_type(
            raw_connection,
            table_name,
            column,
        )
        for column in columns
    }

    if declared_types == {"TEXT"}:
        return

    rows = raw_connection.execute(
        """
        SELECT
            request_id,
            amount,
            estimated_fee,
            conservative_funding_required,
            minimum_jit_transfer,
            request_json,
            preflight_json
        FROM treasury_withdrawal_requests
        ORDER BY id
        """
    ).fetchall()

    canonical: dict[
        str,
        dict[str, str],
    ] = {}

    for row in rows:
        request_id = str(row[0])

        values = (
            _canonical_withdrawal_values(
                request_id=request_id,
                request_json=row[5],
                preflight_json=row[6],
            )
        )

        for index, column in enumerate(
            columns,
            start=1,
        ):
            _legacy_decimal_matches(
                row[index],
                values[column],
                context=(
                    f"withdrawal "
                    f"{request_id}.{column}"
                ),
            )

        canonical[request_id] = values

    logger.info(
        "Migrating Treasury withdrawal amounts "
        "to exact SQLite TEXT decimals"
    )

    _rebuild_table(
        raw_connection,
        engine,
        table,
    )

    for request_id, values in canonical.items():
        raw_connection.execute(
            """
            UPDATE treasury_withdrawal_requests
            SET
                amount=?,
                estimated_fee=?,
                conservative_funding_required=?,
                minimum_jit_transfer=?
            WHERE request_id=?
            """,
            (
                values["amount"],
                values["estimated_fee"],
                values[
                    "conservative_funding_required"
                ],
                values[
                    "minimum_jit_transfer"
                ],
                request_id,
            ),
        )


def _migrate_ownership_exact_decimal(
    raw_connection: Any,
    engine: Engine,
    table: Any,
) -> None:
    table_name = "treasury_ownership_ledger"

    if not _table_exists(
        raw_connection,
        table_name,
    ):
        return

    if (
        _declared_column_type(
            raw_connection,
            table_name,
            "delta_amount",
        )
        == "TEXT"
    ):
        return

    rows = raw_connection.execute(
        """
        SELECT
            event_id,
            delta_amount,
            entry_type,
            source_request_id
        FROM treasury_ownership_ledger
        ORDER BY id
        """
    ).fetchall()

    canonical: dict[str, str] = {}

    for row in rows:
        event_id = str(row[0])
        entry_type = str(row[2] or "")
        source_request_id = str(
            row[3] or ""
        )

        if (
            entry_type
            != "internal_transfer_credit"
            or not source_request_id
        ):
            raise RuntimeError(
                "Treasury exact-decimal migration "
                "cannot prove ownership ledger "
                f"value for event {event_id}"
            )

        transfer = raw_connection.execute(
            """
            SELECT request_json
            FROM treasury_transfer_requests
            WHERE request_id=?
            """,
            (source_request_id,),
        ).fetchone()

        if transfer is None:
            raise RuntimeError(
                "Treasury exact-decimal migration "
                "cannot find source transfer "
                f"{source_request_id} for "
                f"ownership event {event_id}"
            )

        amount = _canonical_transfer_amount(
            transfer[0],
            request_id=source_request_id,
        )

        _legacy_decimal_matches(
            row[1],
            amount,
            context=(
                f"ownership {event_id}.delta_amount"
            ),
        )

        canonical[event_id] = amount

    logger.info(
        "Migrating Treasury ownership amounts "
        "to exact SQLite TEXT decimals"
    )

    _rebuild_table(
        raw_connection,
        engine,
        table,
    )

    for event_id, amount in canonical.items():
        raw_connection.execute(
            """
            UPDATE treasury_ownership_ledger
            SET delta_amount=?
            WHERE event_id=?
            """,
            (
                amount,
                event_id,
            ),
        )


def _migrate_treasury_exact_decimals(
    raw_connection: Any,
    engine: Engine,
    *,
    transfer_table: Any,
    withdrawal_table: Any,
    ownership_table: Any,
) -> None:
    _migrate_transfer_exact_decimal(
        raw_connection,
        engine,
        transfer_table,
    )

    _migrate_withdrawal_exact_decimals(
        raw_connection,
        engine,
        withdrawal_table,
    )

    _migrate_ownership_exact_decimal(
        raw_connection,
        engine,
        ownership_table,
    )


def _migrate_treasury_withdrawal_destination_recipient_bridge(
    raw_connection: Any,
    engine: Engine,
    table: Any,
) -> None:
    table_name = (
        "treasury_withdrawal_destinations"
    )

    if not _table_exists(
        raw_connection,
        table_name,
    ):
        return

    columns = set(
        _table_columns(
            raw_connection,
            table_name,
        )
    )

    if "recipient_id" in columns:
        return

    logger.info(
        "Migrating withdrawal destinations "
        "to recipient-linked schema"
    )

    # recipient_id is intentionally nullable.
    # Existing approved/revoked destination rows are
    # historical route/security records and therefore
    # remain unlinked until an explicit recipient bridge
    # operation safely associates one.
    _rebuild_table(
        raw_connection,
        engine,
        table,
    )


def migrate_database(engine: Engine) -> None:
    """Apply the small built-in schema migration needed for multi-account support.

    The project deliberately avoids a heavy migration framework. New databases are
    created by SQLAlchemy. Existing SQLite v1 databases are rebuilt in place while
    preserving bot IDs, snapshots, alert references, and sync history.
    """

    if engine.dialect.name != "sqlite":
        # The current production package targets SQLite. For another database,
        # create a new schema or add an external migration system before upgrade.
        return

    from .models import (
        AlertIncident,
        Bot,
        BotArchive,
        BotControlAttentionReview,
        GateAccount,
        SyncRun,
        TreasuryOwnershipLedgerEntry,
        TreasuryRateLimitEvent,
        TreasuryTransferLockResolution,
        TreasuryTransferOperationLock,
        TreasuryTransferReconciliation,
        TreasuryTransferRequest,
        TreasuryWithdrawalRecipient,
        TreasuryWithdrawalRecipientEvent,
        TreasuryWithdrawalDestination,
        TreasuryWithdrawalDestinationEvent,
        TreasuryWithdrawalOperationLock,
        TreasuryWithdrawalReconciliation,
        TreasuryWithdrawalRequest,
        TreasuryWithdrawalRequestEvent,
    )

    raw = engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("PRAGMA legacy_alter_table=ON")

        if not _table_exists(raw, "gate_accounts"):
            _create_table(raw, engine, GateAccount.__table__)

        if not _table_exists(
            raw,
            "bot_control_attention_reviews",
        ):
            _create_table(
                raw,
                engine,
                BotControlAttentionReview.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_transfer_requests",
        ):
            _create_table(
                raw,
                engine,
                TreasuryTransferRequest.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_ownership_ledger",
        ):
            _create_table(
                raw,
                engine,
                TreasuryOwnershipLedgerEntry.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_transfer_reconciliations",
        ):
            _create_table(
                raw,
                engine,
                TreasuryTransferReconciliation.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_transfer_operation_locks",
        ):
            _create_table(
                raw,
                engine,
                TreasuryTransferOperationLock.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_rate_limit_events",
        ):
            _create_table(
                raw,
                engine,
                TreasuryRateLimitEvent.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_transfer_lock_resolutions",
        ):
            _create_table(
                raw,
                engine,
                TreasuryTransferLockResolution.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_withdrawal_recipients",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalRecipient.__table__,
            )
        if not _table_exists(
            raw,
            "treasury_withdrawal_recipient_events",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalRecipientEvent.__table__,
            )
        if not _table_exists(
            raw,
            "treasury_withdrawal_destinations",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalDestination.__table__,
            )
        _migrate_treasury_withdrawal_destination_recipient_bridge(
            raw,
            engine,
            TreasuryWithdrawalDestination.__table__,
        )

        if not _table_exists(
            raw,
            "treasury_withdrawal_destination_events",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalDestinationEvent.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_withdrawal_requests",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalRequest.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_withdrawal_reconciliations",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalReconciliation.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_withdrawal_request_events",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalRequestEvent.__table__,
            )

        if not _table_exists(
            raw,
            "treasury_withdrawal_operation_locks",
        ):
            _create_table(
                raw,
                engine,
                TreasuryWithdrawalOperationLock.__table__,
            )

        # T2C.3C: SQLite NUMERIC affinity is not exact
        # for fractional Treasury values. Rebuild only the
        # Treasury monetary tables as exact TEXT decimals,
        # deriving every existing value from immutable audit
        # evidence and failing closed on any mismatch.
        _migrate_treasury_exact_decimals(
            raw,
            engine,
            transfer_table=(
                TreasuryTransferRequest.__table__
            ),
            withdrawal_table=(
                TreasuryWithdrawalRequest.__table__
            ),
            ownership_table=(
                TreasuryOwnershipLedgerEntry.__table__
            ),
        )

        # Deterministic, idempotent ownership backfill.
        #
        # This deliberately derives ownership ONLY from
        # definitive successful LIVE internal-transfer audit
        # records. It never infers ownership from the physical
        # Gate main-account balance.
        #
        # instr() is used rather than SQLite JSON functions so
        # the migration has no JSON1 extension dependency.
        raw.execute(
            """
            INSERT OR IGNORE INTO treasury_ownership_ledger
            (
                event_id,
                owner_account_id,
                custody_account_id,
                currency,
                delta_amount,
                entry_type,
                source_request_id,
                reason,
                metadata_json,
                created_at
            )
            SELECT
                'internal-transfer-credit:' || request_id,
                source_account_id,
                destination_account_id,
                currency,
                amount,
                'internal_transfer_credit',
                request_id,
                'Definitive successful subaccount-to-main Treasury transfer.',
                '{"source":"migration_backfill"}',
                COALESCE(
                    completed_at,
                    updated_at,
                    created_at
                )
            FROM treasury_transfer_requests
            WHERE
                status = 'success'
                AND simulation = 0
                AND write_performed = 1
                AND lower(direction) = 'from'
                AND instr(
                    request_json,
                    '"operation":"subaccount_to_main"'
                ) > 0
            """
        )

        now = datetime.now(timezone.utc).isoformat()

        if _table_exists(raw, "bots"):
            bot_columns = set(_table_columns(raw, "bots"))
            indexes = raw.execute("PRAGMA index_list('bots')").fetchall()
            unique_columns: list[list[str]] = []
            for index in indexes:
                if int(index[2]) != 1:
                    continue
                index_name = str(index[1])
                cols = [str(row[2]) for row in raw.execute(f"PRAGMA index_info({_quote(index_name)})")]
                unique_columns.append(cols)
            needs_bot_rebuild = (
                "account_id" not in bot_columns
                or ["strategy_id", "strategy_type"] in unique_columns
                or ["account_id", "strategy_id", "strategy_type"] not in unique_columns
            )
            missing_account_rows = 0
            if "account_id" in bot_columns:
                missing_account_rows = int(
                    raw.execute(
                        "SELECT COUNT(*) FROM bots WHERE account_id IS NULL OR account_id=''"
                    ).fetchone()[0]
                )
            if needs_bot_rebuild or missing_account_rows:
                raw.execute(
                    """
                    INSERT OR IGNORE INTO gate_accounts
                        (id, name, account_type, gate_uid, enabled, configured, sync_status,
                         last_sync_at, last_success_at, last_error, bot_count, created_at, updated_at)
                    VALUES
                        ('legacy', 'Legacy account', 'legacy', '', 0, 0, 'migrated',
                         NULL, NULL, '', 0, ?, ?)
                    """,
                    (now, now),
                )
            if needs_bot_rebuild:
                logger.info("Migrating bots table to account-aware uniqueness")
                _rebuild_table(raw, engine, Bot.__table__, fill_expressions={"account_id": "'legacy'"})
            else:
                raw.execute("UPDATE bots SET account_id='legacy' WHERE account_id IS NULL OR account_id='' ")

        if (
            _table_exists(raw, "bots")
            and not _table_exists(
                raw,
                "bot_archives",
            )
        ):
            _create_table(
                raw,
                engine,
                BotArchive.__table__,
            )

        if (
            _table_exists(
                raw,
                "bots",
            )
            and _table_exists(
                raw,
                "alert_rules",
            )
            and not _table_exists(
                raw,
                "alert_incidents",
            )
        ):
            _create_table(
                raw,
                engine,
                AlertIncident.__table__,
            )

        if _table_exists(raw, "sync_runs"):
            sync_columns = set(_table_columns(raw, "sync_runs"))
            if "account_id" not in sync_columns or "trigger" not in sync_columns:
                logger.info("Migrating sync_runs table for per-account audit data")
                _rebuild_table(
                    raw,
                    engine,
                    SyncRun.__table__,
                    fill_expressions={"account_id": "NULL", "trigger": "'scheduler'"},
                )

        # Update the legacy account's retained bot count after an upgrade.
        if _table_exists(raw, "bots"):
            raw.execute(
                "UPDATE gate_accounts SET bot_count=(SELECT COUNT(*) FROM bots WHERE account_id='legacy') "
                "WHERE id='legacy'"
            )
            raw.execute(
                "DELETE FROM gate_accounts WHERE id='legacy' "
                "AND NOT EXISTS (SELECT 1 FROM bots WHERE account_id='legacy')"
            )

        raw.commit()
        raw.execute("PRAGMA legacy_alter_table=OFF")
        raw.execute("PRAGMA foreign_keys=ON")
        violations = raw.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Database migration produced foreign-key violations: {violations[:5]}")
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
