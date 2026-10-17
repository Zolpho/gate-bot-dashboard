from __future__ import annotations

import ast
import sqlite3

from decimal import Decimal
from pathlib import Path

import pytest

from app.demo_trading import (
    DEMO_TRADING_REQUIRED_CONFIRMATION,
    DemoTradingStore,
)
from app.demo_wallet import DemoWalletStore
from app.demo_withdrawal import DemoWithdrawalStore


def _stores(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "demo.db"
    )

    wallet = DemoWalletStore(
        database
    )

    withdrawals = DemoWithdrawalStore(
        database
    )

    trading = DemoTradingStore(
        database
    )

    return (
        database,
        wallet,
        withdrawals,
        trading,
    )


def _table_count(
    database: Path,
    table: str,
) -> int:
    db = sqlite3.connect(
        database
    )

    try:
        return int(
            db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        )

    finally:
        db.close()


def _asset_rows(
    database: Path,
):
    db = sqlite3.connect(
        database
    )

    try:
        return db.execute(
            """
            SELECT
                account_id,
                currency,
                available,
                locked
            FROM demo_wallet_assets
            ORDER BY
                account_id,
                currency
            """
        ).fetchall()

    finally:
        db.close()


def test_trading_schema_is_additive_to_wallet_and_withdrawals(
    tmp_path,
):
    (
        database,
        wallet,
        withdrawals,
        trading,
    ) = _stores(
        tmp_path
    )

    wallet.ensure_seeded()
    withdrawals.ensure_seeded()

    before_assets = _asset_rows(
        database
    )

    before_recipients = (
        _table_count(
            database,
            "demo_withdrawal_recipients",
        )
    )

    trading.ensure_ready()

    assert (
        _table_count(
            database,
            "demo_trading_markets",
        )
        == 3
    )

    assert (
        _asset_rows(
            database
        )
        == before_assets
    )

    assert (
        _table_count(
            database,
            "demo_withdrawal_recipients",
        )
        == before_recipients
    )


def test_catalog_uses_only_demo_wallet_accounts_and_markets(
    tmp_path,
):
    *_, trading = _stores(
        tmp_path
    )

    catalog = trading.catalog()

    assert [
        item["id"]
        for item
        in catalog["accounts"]
    ] == [
        "demo-wallet-1",
        "demo-wallet-2",
    ]

    assert [
        item["id"]
        for item
        in catalog["pairs"]
    ] == [
        "EQTY_USDT",
        "BTC_USDT",
        "ETH_USDT",
    ]

    assert (
        catalog[
            "default_pair"
        ]
        == "EQTY_USDT"
    )

    assert (
        catalog[
            "gate_read_performed"
        ]
        is False
    )

    assert (
        catalog[
            "gate_write_performed"
        ]
        is False
    )


def test_snapshot_is_deterministic_and_uses_demo_wallet_balances(
    tmp_path,
):
    *_, trading = _stores(
        tmp_path
    )

    first = trading.snapshot(
        account_id=
            "demo-wallet-1",
        pair="EQTY_USDT",
        depth=10,
    )

    second = trading.snapshot(
        account_id=
            "demo-wallet-1",
        pair="EQTY_USDT",
        depth=10,
    )

    assert first == second

    assert (
        first["balances"]
        ["base"]
        ["available"]
        == "750000"
    )

    assert (
        first["balances"]
        ["quote"]
        ["available"]
        == "12500"
    )

    assert (
        len(
            first[
                "order_book"
            ]["bids"]
        )
        == 10
    )

    assert (
        len(
            first[
                "order_book"
            ]["asks"]
        )
        == 10
    )

    assert (
        Decimal(
            first[
                "order_book"
            ]["best_bid"]
        )
        < Decimal(
            first[
                "order_book"
            ]["best_ask"]
        )
    )


def test_candles_and_trades_are_deterministic_and_gate_free(
    tmp_path,
):
    *_, trading = _stores(
        tmp_path
    )

    candles = trading.candles(
        pair="ETH_USDT",
        interval="1h",
        limit=12,
    )

    trades = trading.trades(
        pair="ETH_USDT",
        limit=7,
    )

    assert (
        len(
            candles["candles"]
        )
        == 12
    )

    assert (
        len(
            trades["trades"]
        )
        == 7
    )

    for result in (
        candles,
        trades,
    ):
        assert (
            result["source"]
            == "demo"
        )

        assert (
            result[
                "gate_read_performed"
            ]
            is False
        )

        assert (
            result[
                "gate_write_performed"
            ]
            is False
        )

        assert (
            result[
                "write_performed"
            ]
            is False
        )


def test_buy_preview_uses_quote_balance_without_mutation(
    tmp_path,
):
    database, *_rest, trading = (
        _stores(
            tmp_path
        )
    )

    before = _asset_rows(
        database
    ) if database.exists() else None

    result = (
        trading.preview_limit_order(
            account_id=
                "demo-wallet-1",
            pair="EQTY_USDT",
            side="buy",
            price="0.0042",
            amount="100000",
            time_in_force="gtc",
        )
    )

    after = _asset_rows(
        database
    )

    assert (
        result["status"]
        == "ready"
    )

    assert (
        result[
            "demo_execution_ready"
        ]
        is True
    )

    assert (
        result["funds"]["asset"]
        == "USDT"
    )

    assert (
        result[
            "funds"
        ]["required"]
        == "420"
    )

    assert (
        result[
            "required_confirmation"
        ]
        == DEMO_TRADING_REQUIRED_CONFIRMATION
    )

    if before is not None:
        assert after == before


def test_sell_preview_uses_base_balance_without_mutation(
    tmp_path,
):
    database, *_rest, trading = (
        _stores(
            tmp_path
        )
    )

    result = (
        trading.preview_limit_order(
            account_id=
                "demo-wallet-1",
            pair="EQTY_USDT",
            side="sell",
            price="0.0043",
            amount="100000",
            time_in_force="gtc",
        )
    )

    assert (
        result["status"]
        == "ready"
    )

    assert (
        result["funds"]["asset"]
        == "EQTY"
    )

    assert (
        result[
            "funds"
        ]["required"]
        == "100000"
    )

    assert (
        _table_count(
            database,
            "demo_trading_markets",
        )
        == 3
    )


def test_preview_blocks_price_amount_and_minimum_precision_violations(
    tmp_path,
):
    *_, trading = _stores(
        tmp_path
    )

    result = (
        trading.preview_limit_order(
            account_id=
                "demo-wallet-1",
            pair="EQTY_USDT",
            side="buy",
            price="0.0042001",
            amount="100.001",
            time_in_force="gtc",
        )
    )

    text = " ".join(
        result["blockers"]
    )

    assert (
        result["status"]
        == "blocked"
    )

    assert (
        "Price exceeds"
        in text
    )

    assert (
        "Amount exceeds"
        in text
    )

    assert (
        "minimum"
        in text
    )


def test_post_only_crossing_is_blocked_and_gtc_crossing_is_warning(
    tmp_path,
):
    *_, trading = _stores(
        tmp_path
    )

    poc = (
        trading.preview_limit_order(
            account_id=
                "demo-wallet-1",
            pair="EQTY_USDT",
            side="buy",
            price="0.0043",
            amount="100000",
            time_in_force="poc",
        )
    )

    gtc = (
        trading.preview_limit_order(
            account_id=
                "demo-wallet-1",
            pair="EQTY_USDT",
            side="buy",
            price="0.0043",
            amount="100000",
            time_in_force="gtc",
        )
    )

    assert (
        poc["status"]
        == "blocked"
    )

    assert any(
        "Post-only"
        in item
        for item
        in poc["blockers"]
    )

    assert (
        gtc["status"]
        == "ready"
    )

    assert any(
        "marketable"
        in item
        for item
        in gtc["warnings"]
    )


def test_preview_enforces_demo_account_scope_and_available_balance(
    tmp_path,
):
    *_, trading = _stores(
        tmp_path
    )

    result = (
        trading.preview_limit_order(
            account_id=
                "demo-wallet-1",
            pair="BTC_USDT",
            side="buy",
            price="65000",
            amount="1",
            time_in_force="gtc",
        )
    )

    assert (
        result["status"]
        == "blocked"
    )

    assert any(
        "Insufficient"
        in item
        for item
        in result["blockers"]
    )

    with pytest.raises(
        KeyError
    ):
        trading.preview_limit_order(
            account_id="zolnode",
            pair="BTC_USDT",
            side="buy",
            price="65000",
            amount="0.001",
            time_in_force="gtc",
        )


def test_demo_trading_module_has_no_gate_production_or_route_dependency():
    path = Path(
        "app/demo_trading.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    imported_modules = set()

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            imported_modules.update(
                alias.name
                for alias
                in node.names
            )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            imported_modules.add(
                node.module or ""
            )

    forbidden_import_fragments = (
        "gate_client",
        "accounts",
        "trading_credentials",
        "trading_execution",
        "trading_order_audit",
        "trading_order_cancel",
        "trading_order_amend",
        "trading_order_locks",
        "trading_rate_limit",
        "account_action_policy",
        "config",
        "db",
        "models",
        "fastapi",
        "treasury",
    )

    for module in imported_modules:
        lowered = module.lower()

        assert not any(
            fragment
            in lowered
            for fragment
            in forbidden_import_fragments
        ), module

    forbidden_source_markers = (
        "GateClient(",
        "session_scope(",
        "get_trading_account(",
        "get_gate_account(",
        "require_account_action_allowed(",
        "create_spot_order(",
        "cancel_spot_order(",
        "amend_spot_order(",
    )

    for marker in (
        forbidden_source_markers
    ):
        assert marker not in source

    assert (
        "demo_trading_orders"
        not in source
    )

    assert (
        "DEMO_TRADING_REQUIRED_CONFIRMATION"
        in source
    )
