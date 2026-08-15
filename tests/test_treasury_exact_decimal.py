from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import (
    Column,
    MetaData,
    Numeric,
    Table,
    create_engine,
    select,
)
from sqlalchemy.orm import Session

from app.exact_decimal import (
    ExactDecimal,
    exact_decimal_text,
)
from app.migrations import migrate_database
from app.models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryTransferRequest,
    TreasuryWithdrawalRequest,
)


def test_exact_decimal_sqlite_roundtrip(
    tmp_path,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'exact.db'}"
    )

    metadata = MetaData()

    table = Table(
        "amounts",
        metadata,
        Column(
            "value",
            ExactDecimal(48, 24),
            nullable=False,
        ),
    )

    metadata.create_all(engine)

    values = (
        Decimal("5"),
        Decimal("0.05"),
        Decimal("5.05"),
        Decimal("4.05"),
        Decimal("1.2300"),
        Decimal("0.000001"),
    )

    with engine.begin() as conn:
        for value in values:
            conn.execute(
                table.insert().values(
                    value=value
                )
            )

        raw = conn.exec_driver_sql(
            """
            SELECT value, typeof(value)
            FROM amounts
            ORDER BY rowid
            """
        ).fetchall()

        assert raw == [
            ("5", "text"),
            ("0.05", "text"),
            ("5.05", "text"),
            ("4.05", "text"),
            ("1.2300", "text"),
            ("0.000001", "text"),
        ]

        loaded = conn.execute(
            select(table.c.value)
            .order_by(table.c.value)
        ).scalars().all()

        assert all(
            isinstance(value, Decimal)
            for value in loaded
        )

    engine.dispose()


def test_exact_decimal_rejects_excess_scale():
    with pytest.raises(ValueError):
        exact_decimal_text(
            Decimal(
                "1.1234567890123456789012345"
            ),
            precision=48,
            scale=24,
        )


def test_legacy_treasury_numeric_migrates_to_exact_text(
    tmp_path,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}"
    )

    metadata = MetaData()

    transfer = (
        TreasuryTransferRequest
        .__table__
        .to_metadata(metadata)
    )

    withdrawal = (
        TreasuryWithdrawalRequest
        .__table__
        .to_metadata(metadata)
    )

    ownership = (
        TreasuryOwnershipLedgerEntry
        .__table__
        .to_metadata(metadata)
    )

    transfer.c.amount.type = Numeric(
        48,
        24,
    )

    for name in (
        "amount",
        "estimated_fee",
        "conservative_funding_required",
        "minimum_jit_transfer",
    ):
        withdrawal.c[name].type = Numeric(
            48,
            24,
        )

    ownership.c.delta_amount.type = Numeric(
        48,
        24,
    )

    metadata.create_all(engine)

    transfer_id = "legacy-transfer"
    withdrawal_id = "legacy-withdrawal"

    with engine.begin() as conn:
        conn.execute(
            transfer.insert().values(
                request_id=transfer_id,
                source_account_id="arnold",
                destination_account_id="zolnode",
                username="arnold",
                direction="from",
                currency="USDT",
                amount=Decimal("1.25"),
                status="success",
                request_hash="a" * 64,
                request_json=json.dumps(
                    {
                        "operation":
                            "subaccount_to_main",
                        "gate_payload": {
                            "amount": "1.25",
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                response_json="{}",
                client_order_id="legacy",
                gate_transfer_id="123",
                gate_label="",
                error="",
                simulation=False,
                write_performed=True,
            )
        )

        conn.execute(
            withdrawal.insert().values(
                request_id=withdrawal_id,
                owner_account_id="arnold",
                custody_account_id="zolnode",
                username="arnold",
                destination_id="wd_legacy",
                currency="USDT",
                chain="ARBEVM",
                address="0x" + "1" * 40,
                memo="",
                amount=Decimal("5.123456"),
                estimated_fee=Decimal(
                    "0.050001"
                ),
                conservative_funding_required=(
                    Decimal("5.173457")
                ),
                minimum_jit_transfer=(
                    Decimal("4.173457")
                ),
                jit_required=True,
                status="simulated",
                request_hash="b" * 64,
                request_json=json.dumps(
                    {
                        "amount": "5.123456",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                preflight_json=json.dumps(
                    {
                        "fee": {
                            "estimated_fee":
                                "0.050001",
                        },
                        "funding": {
                            "conservative_funding_required":
                                "5.173457",
                            "minimum_jit_transfer":
                                "4.173457",
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                destination_snapshot_json="{}",
                gate_withdraw_order_id="",
                gate_withdrawal_id="",
                gate_txid="",
                gate_status="",
                error="",
                simulation=True,
                write_performed=False,
            )
        )

        conn.execute(
            ownership.insert().values(
                event_id=(
                    "internal-transfer-credit:"
                    + transfer_id
                ),
                owner_account_id="arnold",
                custody_account_id="zolnode",
                currency="USDT",
                delta_amount=Decimal("1.25"),
                entry_type=(
                    "internal_transfer_credit"
                ),
                source_request_id=transfer_id,
                reason="Legacy exact-decimal test",
                metadata_json="{}",
            )
        )

    migrate_database(engine)

    with engine.connect() as conn:
        transfer_info = {
            row[1]: str(row[2]).upper()
            for row in conn.exec_driver_sql(
                """
                PRAGMA table_info(
                    treasury_transfer_requests
                )
                """
            )
        }

        withdrawal_info = {
            row[1]: str(row[2]).upper()
            for row in conn.exec_driver_sql(
                """
                PRAGMA table_info(
                    treasury_withdrawal_requests
                )
                """
            )
        }

        ownership_info = {
            row[1]: str(row[2]).upper()
            for row in conn.exec_driver_sql(
                """
                PRAGMA table_info(
                    treasury_ownership_ledger
                )
                """
            )
        }

        assert transfer_info["amount"] == "TEXT"

        for name in (
            "amount",
            "estimated_fee",
            "conservative_funding_required",
            "minimum_jit_transfer",
        ):
            assert (
                withdrawal_info[name]
                == "TEXT"
            )

        assert (
            ownership_info["delta_amount"]
            == "TEXT"
        )

        row = conn.exec_driver_sql(
            """
            SELECT
                amount,
                typeof(amount),
                estimated_fee,
                typeof(estimated_fee),
                conservative_funding_required,
                minimum_jit_transfer
            FROM treasury_withdrawal_requests
            WHERE request_id=?
            """,
            (withdrawal_id,),
        ).fetchone()

        assert row == (
            "5.123456",
            "text",
            "0.050001",
            "text",
            "5.173457",
            "4.173457",
        )

    with Session(engine) as session:
        withdrawal_row = session.scalar(
            select(
                TreasuryWithdrawalRequest
            ).where(
                TreasuryWithdrawalRequest
                .request_id
                == withdrawal_id
            )
        )

        assert withdrawal_row is not None

        assert (
            withdrawal_row.amount
            == Decimal("5.123456")
        )

        assert (
            withdrawal_row.estimated_fee
            == Decimal("0.050001")
        )

        assert (
            withdrawal_row
            .conservative_funding_required
            == Decimal("5.173457")
        )

        assert (
            withdrawal_row
            .minimum_jit_transfer
            == Decimal("4.173457")
        )

    engine.dispose()
