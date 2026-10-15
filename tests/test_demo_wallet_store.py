from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from app.demo_auth import (
    DEMO_ACCOUNT_IDS,
    DemoSessionStore,
)
from app.demo_wallet import (
    DEMO_WALLET_SEED_VERSION,
    DemoWalletStateError,
    DemoWalletStore,
)


def _database(
    tmp_path: Path,
) -> Path:
    return (
        tmp_path
        / "isolated-demo"
        / "demo.db"
    )


def test_wallet_seed_preserves_existing_demo_auth_session(
    tmp_path,
):
    database = _database(
        tmp_path
    )

    token, _ = (
        DemoSessionStore(
            database
        ).create_session(
            account_ids=(
                DEMO_ACCOUNT_IDS
            ),
            ttl_seconds=900,
        )
    )

    assert token.startswith(
        "gdbdemo_"
    )

    with sqlite3.connect(
        database
    ) as db:
        before = db.execute(
            """
            SELECT COUNT(*)
            FROM demo_sessions
            """
        ).fetchone()[0]

    assert before == 1

    created = DemoWalletStore(
        database
    ).ensure_seeded()

    assert created is True

    with sqlite3.connect(
        database
    ) as db:
        after = db.execute(
            """
            SELECT COUNT(*)
            FROM demo_sessions
            """
        ).fetchone()[0]

        tables = {
            row[0]
            for row in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

    assert after == 1

    assert "demo_sessions" in tables

    assert {
        "demo_wallet_meta",
        "demo_wallet_accounts",
        "demo_wallet_currencies",
        "demo_wallet_assets",
        "demo_deposit_addresses",
        "demo_deposits",
    }.issubset(
        tables
    )


def test_wallet_seed_is_idempotent_and_deterministic(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    assert (
        store.ensure_seeded()
        is True
    )

    first_accounts = (
        store.list_accounts()
    )

    first_balance = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    first_deposits = (
        store.list_deposits(
            "demo-wallet-1"
        )
    )

    assert (
        store.ensure_seeded()
        is False
    )

    assert (
        store.list_accounts()
        == first_accounts
    )

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == first_balance
    )

    assert (
        store.list_deposits(
            "demo-wallet-1"
        )
        == first_deposits
    )


def test_wallet_accounts_exactly_match_demo_identity_accounts(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    accounts = (
        store.list_accounts()
    )

    assert tuple(
        item[
            "account_id"
        ]
        for item
        in accounts
    ) == DEMO_ACCOUNT_IDS

    assert [
        item[
            "display_name"
        ]
        for item
        in accounts
    ] == [
        "Demo Growth Wallet",
        "Demo Treasury Wallet",
    ]


def test_wallet_balance_state_is_fake_account_scoped_and_precise(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    growth = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    treasury = (
        store.get_balance_state(
            "demo-wallet-2"
        )
    )

    assert growth[
        "source"
    ] == "demo"

    assert treasury[
        "source"
    ] == "demo"

    assert growth[
        "seed_version"
    ] == DEMO_WALLET_SEED_VERSION

    assert growth[
        "account_id"
    ] == "demo-wallet-1"

    assert treasury[
        "account_id"
    ] == "demo-wallet-2"

    assert (
        growth[
            "total_value_usdt"
        ]
        != treasury[
            "total_value_usdt"
        ]
    )

    growth_assets = {
        item[
            "currency"
        ]: item
        for item
        in growth[
            "assets"
        ]
    }

    assert set(
        growth_assets
    ) == {
        "USDT",
        "EQTY",
        "BTC",
        "ETH",
    }

    assert (
        growth_assets[
            "USDT"
        ][
            "available"
        ]
        == "12500"
    )

    assert (
        growth_assets[
            "USDT"
        ][
            "locked"
        ]
        == "250"
    )

    assert (
        growth[
            "bot_summary"
        ][
            "running_bots"
        ]
        == 3
    )


def test_deposit_catalog_networks_and_addresses_are_synthetic(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    currencies = (
        store.list_currencies()
    )

    assert [
        item[
            "currency"
        ]
        for item
        in currencies
    ] == [
        "USDT",
        "EQTY",
        "BTC",
        "ETH",
    ]

    networks = (
        store.list_deposit_networks(
            "demo-wallet-1",
            "usdt",
        )
    )

    assert [
        item[
            "chain"
        ]
        for item
        in networks
    ] == [
        "ETH",
        "TRX",
    ]

    address = (
        store.get_deposit_address(
            "demo-wallet-1",
            "USDT",
            "ETH",
        )
    )

    assert (
        address[
            "source"
        ]
        == "demo"
    )

    assert (
        address[
            "address"
        ].startswith(
            "DEMO-ONLY-"
        )
    )

    assert (
        address[
            "address"
        ]
        != ""
    )

    assert (
        address[
            "deposit_enabled"
        ]
        is True
    )


def test_deposit_history_is_deterministic_and_account_scoped(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    growth = (
        store.list_deposits(
            "demo-wallet-1"
        )
    )

    treasury = (
        store.list_deposits(
            "demo-wallet-2"
        )
    )

    assert growth[
        "total"
    ] == 3

    assert treasury[
        "total"
    ] == 3

    assert {
        item[
            "account_id"
        ]
        for item
        in growth[
            "items"
        ]
    } == {
        "demo-wallet-1"
    }

    assert {
        item[
            "account_id"
        ]
        for item
        in treasury[
            "items"
        ]
    } == {
        "demo-wallet-2"
    }

    detail = store.get_deposit(
        "demo-wallet-1",
        900001,
    )

    assert detail[
        "currency"
    ] == "USDT"

    assert detail[
        "chain"
    ] == "ETH"

    assert detail[
        "status"
    ] == "DONE"

    assert detail[
        "final"
    ] is True

    assert detail[
        "raw"
    ][
        "demo"
    ] is True

    with pytest.raises(
        KeyError
    ):
        store.get_deposit(
            "demo-wallet-2",
            900001,
        )


def test_unknown_demo_wallet_account_fails_closed(
    tmp_path,
):
    store = DemoWalletStore(
        _database(
            tmp_path
        )
    )

    with pytest.raises(
        KeyError,
        match=(
            "Unknown Demo Wallet account"
        ),
    ):
        store.get_balance_state(
            "zolnode"
        )

    with pytest.raises(
        KeyError
    ):
        store.list_deposits(
            "arnold"
        )

    with pytest.raises(
        KeyError
    ):
        store.get_deposit_address(
            "eqtydao",
            "USDT",
            "ETH",
        )


def test_unknown_wallet_seed_version_fails_closed_without_reseed(
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

    original = (
        store.get_balance_state(
            "demo-wallet-1"
        )
    )

    with sqlite3.connect(
        database
    ) as db:
        db.execute(
            """
            UPDATE demo_wallet_meta
            SET value = '999'
            WHERE key = 'seed_version'
            """
        )

    with pytest.raises(
        DemoWalletStateError,
        match=(
            "Unsupported Demo Wallet seed version"
        ),
    ):
        store.ensure_seeded()

    with sqlite3.connect(
        database
    ) as db:
        row = db.execute(
            """
            SELECT available
            FROM demo_wallet_assets
            WHERE account_id = 'demo-wallet-1'
              AND currency = 'USDT'
            """
        ).fetchone()

    assert row is not None

    assert (
        row[0]
        == original[
            "assets"
        ][
            next(
                index
                for index, item
                in enumerate(
                    original[
                        "assets"
                    ]
                )
                if item[
                    "currency"
                ]
                == "USDT"
            )
        ][
            "available"
        ]
    )


def test_demo_wallet_module_has_no_production_or_gate_dependencies():
    path = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "app"
        / "demo_wallet.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        ),
        filename=str(
            path
        ),
    )

    imported_modules: set[
        str
    ] = set()

    imported_symbols: set[
        str
    ] = set()

    called_names: set[
        str
    ] = set()

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                imported_modules.add(
                    alias.name
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            imported_modules.add(
                node.module
                or ""
            )

            for alias in node.names:
                imported_symbols.add(
                    alias.name
                )

        elif isinstance(
            node,
            ast.Call,
        ):
            if isinstance(
                node.func,
                ast.Name,
            ):
                called_names.add(
                    node.func.id
                )

            elif isinstance(
                node.func,
                ast.Attribute,
            ):
                called_names.add(
                    node.func.attr
                )

    forbidden_modules = {
        "accounts",
        "db",
        "gate_client",
        "gate_native_activity_transport",
        "models",
        "treasury",
        "sqlalchemy",
        "fastapi",
    }

    for module in imported_modules:
        normalized = (
            module
            .lstrip(".")
            .split(".")[0]
        )

        assert (
            normalized
            not in forbidden_modules
        ), module

    for symbol in (
        "GateClient",
        "SessionLocal",
        "Session",
        "get_db",
        "session_scope",
        "get_gate_account",
    ):
        assert (
            symbol
            not in imported_symbols
        ), symbol

        assert (
            symbol
            not in called_names
        ), symbol

    assert (
        "DEMO_ACCOUNT_IDS"
        in imported_symbols
    )
