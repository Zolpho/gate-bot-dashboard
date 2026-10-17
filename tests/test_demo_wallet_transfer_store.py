from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.demo_wallet import (
    DEMO_WALLET_OWNERSHIP_TRANSFER_SEED_VERSION,
    DemoWalletStateError,
    DemoWalletStore,
    DemoWalletTransferConflict,
)


def _database(
    tmp_path: Path,
) -> Path:
    return (
        tmp_path
        / "isolated-demo"
        / "demo.db"
    )


def _asset(
    payload,
    currency: str,
):
    return next(
        item
        for item
        in payload[
            "assets"
        ]
        if item[
            "currency"
        ]
        == currency
    )


def test_f5_tables_and_feature_seed_are_isolated_and_deterministic(
    tmp_path,
):
    database = _database(
        tmp_path
    )

    store = DemoWalletStore(
        database
    )

    assert (
        store.ensure_seeded()
        is True
    )

    with sqlite3.connect(
        database
    ) as db:
        tables = {
            row[
                0
            ]
            for row
            in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        marker = db.execute(
            """
            SELECT value
            FROM demo_wallet_meta
            WHERE key = 'ownership_transfer_seed_version'
            """
        ).fetchone()

    assert {
        "demo_ownership_entries",
        "demo_transfers",
        "demo_transfer_events",
    }.issubset(
        tables
    )

    assert marker is not None

    assert (
        marker[
            0
        ]
        == DEMO_WALLET_OWNERSHIP_TRANSFER_SEED_VERSION
    )

    assert len(
        store.list_ownership_entries()
    ) == 3

    assert len(
        store.list_transfers()
    ) == 2


def test_f5_seed_attaches_to_existing_wallet_state_without_reseed(
    tmp_path,
):
    database = _database(
        tmp_path
    )

    store = DemoWalletStore(
        database
    )

    assert (
        store.ensure_seeded()
        is True
    )

    before = store.get_balance_state(
        "demo-wallet-1"
    )

    with sqlite3.connect(
        database
    ) as db:
        db.execute(
            """
            DELETE FROM demo_transfer_events
            """
        )

        db.execute(
            """
            DELETE FROM demo_transfers
            """
        )

        db.execute(
            """
            DELETE FROM demo_ownership_entries
            """
        )

        db.execute(
            """
            DELETE FROM demo_wallet_meta
            WHERE key IN (
                'ownership_transfer_seed_version',
                'ownership_transfer_seed_timestamp'
            )
            """
        )

    assert (
        store.ensure_seeded()
        is False
    )

    after = store.get_balance_state(
        "demo-wallet-1"
    )

    assert after == before

    assert len(
        store.list_ownership_entries()
    ) == 3

    assert len(
        store.list_transfers()
    ) == 2


def test_seeded_ownership_balances_are_precise_and_account_scoped(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    rows = store.ownership_balances(
        account_ids={
            "demo-wallet-1",
        },
    )

    amounts = {
        item[
            "currency"
        ]:
            item[
                "main_held_amount"
            ]
        for item
        in rows
    }

    assert amounts == {
        "EQTY":
            "125000",
        "ETH":
            "0.15",
        "USDT":
            "2500",
    }

    assert {
        item[
            "owner_account_id"
        ]
        for item
        in rows
    } == {
        "demo-wallet-1",
    }

    assert {
        item[
            "custody_account_id"
        ]
        for item
        in rows
    } == {
        "demo-wallet-2",
    }

    entries = store.list_ownership_entries(
        account_ids={
            "demo-wallet-2",
        },
    )

    assert len(
        entries
    ) == 3

    assert all(
        item[
            "metadata"
        ][
            "demo"
        ]
        is True
        for item
        in entries
    )

    assert all(
        item[
            "entry_type"
        ]
        == "correction_credit"
        for item
        in entries
    )


def test_transfer_preview_is_read_only(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    source_before = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    destination_before = (
        store.get_balance_state(
            "demo-wallet-2"
        )
    )

    preview = store.preview_transfer(
        source_account_id=(
            "demo-wallet-1"
        ),
        destination_account_id=(
            "demo-wallet-2"
        ),
        currency="USDT",
        amount="100",
    )

    assert preview[
        "status"
    ] == "ready"

    assert preview[
        "can_transfer"
    ] is True

    assert preview[
        "source_available_before"
    ] == "12500"

    assert preview[
        "source_available_after"
    ] == "12400"

    assert preview[
        "destination_available_before"
    ] == "42000"

    assert preview[
        "destination_available_after"
    ] == "42100"

    assert preview[
        "gate_write_required"
    ] is False

    assert preview[
        "gate_write_performed"
    ] is False

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == source_before
    )

    assert (
        store.get_balance_state(
            "demo-wallet-2"
        )
        == destination_before
    )


def test_simulated_user_transfer_is_atomic_and_does_not_mint_ownership(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    source_before = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    destination_before = (
        store.get_balance_state(
            "demo-wallet-2"
        )
    )

    ownership_before = (
        store.ownership_balances()
    )

    result = store.simulate_transfer(
        request_id=(
            "demo-test-transfer-001"
        ),
        source_account_id=(
            "demo-wallet-1"
        ),
        destination_account_id=(
            "demo-wallet-2"
        ),
        currency="USDT",
        amount="100",
        username="demo",
        occurred_at=(
            "2026-10-17T10:30:00+00:00"
        ),
    )

    assert result[
        "created"
    ] is True

    transfer = result[
        "transfer"
    ]

    assert transfer[
        "status"
    ] == "success"

    assert transfer[
        "direction"
    ] == "user_account_transfer"

    assert transfer[
        "simulation"
    ] is True

    assert transfer[
        "write_performed"
    ] is False

    assert transfer[
        "gate_transfer_id"
    ] is None

    assert result[
        "response"
    ][
        "ownership_changed"
    ] is False

    source_after = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    destination_after = (
        store.get_balance_state(
            "demo-wallet-2"
        )
    )

    source_before_usdt = _asset(
        source_before,
        "USDT",
    )

    source_after_usdt = _asset(
        source_after,
        "USDT",
    )

    destination_before_usdt = _asset(
        destination_before,
        "USDT",
    )

    destination_after_usdt = _asset(
        destination_after,
        "USDT",
    )

    assert (
        source_before_usdt[
            "available"
        ]
        == "12500"
    )

    assert (
        source_after_usdt[
            "available"
        ]
        == "12400"
    )

    assert (
        source_after_usdt[
            "locked"
        ]
        == source_before_usdt[
            "locked"
        ]
    )

    assert (
        destination_before_usdt[
            "available"
        ]
        == "42000"
    )

    assert (
        destination_after_usdt[
            "available"
        ]
        == "42100"
    )

    assert (
        destination_after_usdt[
            "locked"
        ]
        == destination_before_usdt[
            "locked"
        ]
    )

    assert (
        store.ownership_balances()
        == ownership_before
    )

    events = (
        store.list_transfer_events(
            "demo-test-transfer-001"
        )
    )

    assert [
        item[
            "event_type"
        ]
        for item
        in events
    ] == [
        "created",
        "completed",
    ]

    assert [
        item[
            "status"
        ]
        for item
        in events
    ] == [
        "pending",
        "success",
    ]


def test_simulated_transfer_is_idempotent_without_double_debit(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    first = store.simulate_transfer(
        request_id=(
            "demo-test-transfer-002"
        ),
        source_account_id=(
            "demo-wallet-1"
        ),
        destination_account_id=(
            "demo-wallet-2"
        ),
        currency="ETH",
        amount="0.1",
        username="demo",
        occurred_at=(
            "2026-10-17T10:31:00+00:00"
        ),
    )

    after_first = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    replay = store.simulate_transfer(
        request_id=(
            "demo-test-transfer-002"
        ),
        source_account_id=(
            "demo-wallet-1"
        ),
        destination_account_id=(
            "demo-wallet-2"
        ),
        currency="ETH",
        amount="0.10",
        username="demo",
        occurred_at=(
            "2026-10-17T11:00:00+00:00"
        ),
    )

    after_replay = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    assert first[
        "created"
    ] is True

    assert replay[
        "created"
    ] is False

    assert (
        replay[
            "transfer"
        ][
            "request_id"
        ]
        == "demo-test-transfer-002"
    )

    assert after_replay == after_first

    matching = [
        item
        for item
        in store.list_transfers()
        if item[
            "request_id"
        ]
        == "demo-test-transfer-002"
    ]

    assert len(
        matching
    ) == 1

    assert len(
        store.list_transfer_events(
            "demo-test-transfer-002"
        )
    ) == 2


def test_transfer_request_id_conflict_fails_closed_without_extra_mutation(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    store.simulate_transfer(
        request_id=(
            "demo-test-transfer-003"
        ),
        source_account_id=(
            "demo-wallet-1"
        ),
        destination_account_id=(
            "demo-wallet-2"
        ),
        currency="USDT",
        amount="10",
        username="demo",
        occurred_at=(
            "2026-10-17T10:32:00+00:00"
        ),
    )

    after_first = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    with pytest.raises(
        DemoWalletTransferConflict,
        match=(
            "different Demo transfer operation"
        ),
    ):
        store.simulate_transfer(
            request_id=(
                "demo-test-transfer-003"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="11",
            username="demo",
            occurred_at=(
                "2026-10-17T10:33:00+00:00"
            ),
        )

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == after_first
    )

    matching = [
        item
        for item
        in store.list_transfers()
        if item[
            "request_id"
        ]
        == "demo-test-transfer-003"
    ]

    assert len(
        matching
    ) == 1


def test_invalid_or_insufficient_transfer_rolls_back_without_audit_row(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    before = store.get_balance_state(
        "demo-wallet-1"
    )

    with pytest.raises(
        ValueError,
        match=(
            "source and destination must differ"
        ),
    ):
        store.simulate_transfer(
            request_id=(
                "demo-test-transfer-004"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-1"
            ),
            currency="USDT",
            amount="1",
        )

    with pytest.raises(
        ValueError,
        match=(
            "Insufficient Demo Wallet available balance"
        ),
    ):
        store.simulate_transfer(
            request_id=(
                "demo-test-transfer-005"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="999999999",
        )

    with pytest.raises(
        KeyError,
        match=(
            "Unknown Demo Wallet account"
        ),
    ):
        store.simulate_transfer(
            request_id=(
                "demo-test-transfer-006"
            ),
            source_account_id="zolnode",
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="1",
        )

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == before
    )

    request_ids = {
        item[
            "request_id"
        ]
        for item
        in store.list_transfers()
    }

    assert (
        "demo-test-transfer-004"
        not in request_ids
    )

    assert (
        "demo-test-transfer-005"
        not in request_ids
    )

    assert (
        "demo-test-transfer-006"
        not in request_ids
    )


def test_unknown_f5_feature_seed_version_fails_closed(
    tmp_path,
):
    database = _database(
        tmp_path
    )

    store = DemoWalletStore(
        database
    )

    assert (
        store.ensure_seeded()
        is True
    )

    with sqlite3.connect(
        database
    ) as db:
        before = db.execute(
            """
            SELECT available
            FROM demo_wallet_assets
            WHERE account_id = 'demo-wallet-1'
              AND currency = 'USDT'
            """
        ).fetchone()[0]

        db.execute(
            """
            UPDATE demo_wallet_meta
            SET value = '999'
            WHERE key = 'ownership_transfer_seed_version'
            """
        )

    with pytest.raises(
        DemoWalletStateError,
        match=(
            "Unsupported Demo Wallet ownership/transfer seed version"
        ),
    ):
        store.ensure_seeded()

    with sqlite3.connect(
        database
    ) as db:
        after = db.execute(
            """
            SELECT available
            FROM demo_wallet_assets
            WHERE account_id = 'demo-wallet-1'
              AND currency = 'USDT'
            """
        ).fetchone()[0]

    assert after == before
