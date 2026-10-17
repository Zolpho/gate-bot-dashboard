from __future__ import annotations

import ast
import sqlite3

from pathlib import Path

import pytest

from app.demo_trading import (
    DEMO_TRADING_REQUIRED_CONFIRMATION,
    DemoTradingStore,
)
from app.demo_trading_orders import (
    DemoTradingOrderConflict,
    DemoTradingOrderError,
    DemoTradingOrderStore,
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

    orders = DemoTradingOrderStore(
        database
    )

    return (
        database,
        wallet,
        withdrawals,
        trading,
        orders,
    )


def _asset(
    database: Path,
    account_id: str,
    currency: str,
):
    db = sqlite3.connect(
        database
    )

    try:
        row = db.execute(
            """
            SELECT
                available,
                locked
            FROM demo_wallet_assets
            WHERE
                account_id = ?
                AND currency = ?
            """,
            (
                account_id,
                currency,
            ),
        ).fetchone()

        assert row is not None

        return row

    finally:
        db.close()


def _count(
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


def _create_growth_buy(
    orders: DemoTradingOrderStore,
    *,
    request_id: str,
    amount: str = "100000",
):
    return orders.create_limit_order(
        request_id=request_id,
        username="demo",
        account_id="demo-wallet-1",
        pair="EQTY_USDT",
        side="buy",
        price="0.0042",
        amount=amount,
        time_in_force="gtc",
        confirmation=(
            DEMO_TRADING_REQUIRED_CONFIRMATION
        ),
        occurred_at=(
            "2026-10-17T14:30:00+00:00"
        ),
    )


def test_order_schema_is_additive_to_existing_demo_state(
    tmp_path,
):
    (
        database,
        wallet,
        withdrawals,
        trading,
        orders,
    ) = _stores(
        tmp_path
    )

    wallet.ensure_seeded()
    withdrawals.ensure_seeded()
    trading.ensure_ready()

    before_assets = {
        (
            account,
            currency,
        ):
            _asset(
                database,
                account,
                currency,
            )
        for account in (
            "demo-wallet-1",
            "demo-wallet-2",
        )
        for currency in (
            "USDT",
            "EQTY",
            "BTC",
            "ETH",
        )
    }

    recipient_count = _count(
        database,
        "demo_withdrawal_recipients",
    )

    market_count = _count(
        database,
        "demo_trading_markets",
    )

    orders.ensure_ready()

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 0
    )

    assert (
        _count(
            database,
            "demo_trading_order_events",
        )
        == 0
    )

    assert (
        _count(
            database,
            "demo_trading_markets",
        )
        == market_count
    )

    assert (
        _count(
            database,
            "demo_withdrawal_recipients",
        )
        == recipient_count
    )

    after_assets = {
        (
            account,
            currency,
        ):
            _asset(
                database,
                account,
                currency,
            )
        for account in (
            "demo-wallet-1",
            "demo-wallet-2",
        )
        for currency in (
            "USDT",
            "EQTY",
            "BTC",
            "ETH",
        )
    }

    assert after_assets == before_assets


def test_buy_creation_atomically_reserves_quote_balance(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    result = _create_growth_buy(
        orders,
        request_id=
            "demo-order-request-buy-001",
    )

    assert (
        result[
            "idempotent_replay"
        ]
        is False
    )

    assert (
        result[
            "balance_reservation_performed"
        ]
        is True
    )

    order = result["order"]

    assert order["status"] == "open"
    assert order["side"] == "buy"
    assert order["funding_asset"] == "USDT"
    assert order["reserved_amount"] == "420"
    assert order["filled_amount"] == "0"
    assert order["remaining_amount"] == "100000"

    available, locked = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    assert available == "12080"
    assert locked == "670"

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 1
    )

    assert (
        _count(
            database,
            "demo_trading_order_events",
        )
        == 1
    )


def test_sell_creation_atomically_reserves_base_balance(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    result = orders.create_limit_order(
        request_id=
            "demo-order-request-sell-001",
        username="demo",
        account_id="demo-wallet-1",
        pair="EQTY_USDT",
        side="sell",
        price="0.0043",
        amount="100000",
        time_in_force="gtc",
        confirmation=(
            DEMO_TRADING_REQUIRED_CONFIRMATION
        ),
        occurred_at=(
            "2026-10-17T14:31:00+00:00"
        ),
    )

    order = result["order"]

    assert order["status"] == "open"
    assert order["funding_asset"] == "EQTY"
    assert order["reserved_amount"] == "100000"

    available, locked = _asset(
        database,
        "demo-wallet-1",
        "EQTY",
    )

    assert available == "650000"
    assert locked == "200000"


def test_exact_request_replay_occurs_before_fresh_preview_and_never_reserves_twice(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    first = _create_growth_buy(
        orders,
        request_id=
            "demo-order-request-replay-001",
    )

    assert (
        first[
            "idempotent_replay"
        ]
        is False
    )

    db = sqlite3.connect(
        database
    )

    try:
        db.execute(
            """
            UPDATE demo_wallet_assets
            SET available = '0'
            WHERE
                account_id = 'demo-wallet-1'
                AND currency = 'USDT'
            """
        )

        db.commit()

    finally:
        db.close()

    replay = _create_growth_buy(
        orders,
        request_id=
            "demo-order-request-replay-001",
    )

    assert (
        replay[
            "idempotent_replay"
        ]
        is True
    )

    assert (
        replay[
            "balance_reservation_performed"
        ]
        is False
    )

    assert (
        replay[
            "demo_write_performed"
        ]
        is False
    )

    available, locked = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    assert available == "0"
    assert locked == "670"

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 1
    )

    assert (
        _count(
            database,
            "demo_trading_order_events",
        )
        == 1
    )


def test_request_id_conflict_does_not_change_reservation(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    _create_growth_buy(
        orders,
        request_id=
            "demo-order-request-conflict-001",
    )

    before = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    with pytest.raises(
        DemoTradingOrderConflict
    ):
        _create_growth_buy(
            orders,
            request_id=
                "demo-order-request-conflict-001",
            amount="120000",
        )

    after = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    assert after == before

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 1
    )

    assert (
        _count(
            database,
            "demo_trading_order_events",
        )
        == 1
    )


def test_wrong_demo_confirmation_creates_no_order_or_reservation(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    orders.ensure_ready()

    before = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    with pytest.raises(
        DemoTradingOrderError
    ):
        orders.create_limit_order(
            request_id=
                "demo-order-request-confirm-001",
            username="demo",
            account_id="demo-wallet-1",
            pair="EQTY_USDT",
            side="buy",
            price="0.0042",
            amount="100000",
            time_in_force="gtc",
            confirmation=(
                "PLACE LIVE LIMIT ORDER"
            ),
        )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == before
    )

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 0
    )

    assert (
        _count(
            database,
            "demo_trading_order_events",
        )
        == 0
    )


def test_blocked_preview_creates_no_order_or_reservation(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    orders.ensure_ready()

    usdt_before = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    with pytest.raises(
        DemoTradingOrderError
    ):
        orders.create_limit_order(
            request_id=
                "demo-order-request-poc-001",
            username="demo",
            account_id="demo-wallet-1",
            pair="EQTY_USDT",
            side="buy",
            price="0.0043",
            amount="100000",
            time_in_force="poc",
            confirmation=(
                DEMO_TRADING_REQUIRED_CONFIRMATION
            ),
        )

    with pytest.raises(
        DemoTradingOrderError
    ):
        orders.create_limit_order(
            request_id=
                "demo-order-request-funds-001",
            username="demo",
            account_id="demo-wallet-1",
            pair="BTC_USDT",
            side="buy",
            price="65000",
            amount="1",
            time_in_force="gtc",
            confirmation=(
                DEMO_TRADING_REQUIRED_CONFIRMATION
            ),
        )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == usdt_before
    )

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 0
    )


def test_order_reads_and_events_are_account_scoped(
    tmp_path,
):
    _database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    growth = _create_growth_buy(
        orders,
        request_id=
            "demo-order-request-scope-001",
    )

    treasury = orders.create_limit_order(
        request_id=
            "demo-order-request-scope-002",
        username="demo",
        account_id="demo-wallet-2",
        pair="EQTY_USDT",
        side="buy",
        price="0.0041",
        amount="100000",
        time_in_force="gtc",
        confirmation=(
            DEMO_TRADING_REQUIRED_CONFIRMATION
        ),
        occurred_at=(
            "2026-10-17T14:32:00+00:00"
        ),
    )

    growth_rows = orders.list_orders(
        account_ids={
            "demo-wallet-1",
        }
    )

    assert len(growth_rows) == 1

    assert (
        growth_rows[0][
            "request_id"
        ]
        == growth[
            "order"
        ][
            "request_id"
        ]
    )

    assert (
        treasury[
            "order"
        ][
            "account_id"
        ]
        == "demo-wallet-2"
    )

    with pytest.raises(
        KeyError
    ):
        orders.get_order(
            treasury[
                "order"
            ][
                "request_id"
            ],
            account_ids={
                "demo-wallet-1",
            },
        )

    events = orders.list_events(
        growth[
            "order"
        ][
            "request_id"
        ],
        account_ids={
            "demo-wallet-1",
        },
    )

    assert len(events) == 1
    assert events[0]["action"] == "created"
    assert events[0]["to_status"] == "open"

    with pytest.raises(
        KeyError
    ):
        orders.list_events(
            growth[
                "order"
            ][
                "request_id"
            ],
            account_ids={
                "demo-wallet-2",
            },
        )


def test_new_order_uses_current_reserved_balance_and_cannot_overcommit(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    first = orders.create_limit_order(
        request_id=
            "demo-order-request-budget-001",
        username="demo",
        account_id="demo-wallet-1",
        pair="BTC_USDT",
        side="buy",
        price="65000",
        amount="0.1",
        time_in_force="gtc",
        confirmation=(
            DEMO_TRADING_REQUIRED_CONFIRMATION
        ),
    )

    assert (
        first[
            "order"
        ][
            "reserved_amount"
        ]
        == "6500"
    )

    available, locked = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    assert available == "6000"
    assert locked == "6750"

    with pytest.raises(
        DemoTradingOrderError
    ):
        orders.create_limit_order(
            request_id=
                "demo-order-request-budget-002",
            username="demo",
            account_id="demo-wallet-1",
            pair="BTC_USDT",
            side="buy",
            price="65000",
            amount="0.1",
            time_in_force="gtc",
            confirmation=(
                DEMO_TRADING_REQUIRED_CONFIRMATION
            ),
        )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == (
            "6000",
            "6750",
        )
    )

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 1
    )


def test_demo_order_store_has_no_gate_production_route_or_recovery_dependency():
    path = Path(
        "app/demo_trading_orders.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    imports = set()

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            imports.update(
                alias.name
                for alias
                in node.names
            )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            imports.add(
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

    for module in imports:
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
        "sessionStorage",
        "localStorage",
        "/api/trading",
    )

    for marker in (
        forbidden_source_markers
    ):
        assert marker not in source

    assert (
        "demo_trading_cancellations"
        not in source
    )

    assert (
        "demo_trading_amendments"
        not in source
    )

    assert (
        "demo_trading_fills"
        not in source
    )


def test_external_public_preview_is_persisted_without_gate_transport(
    tmp_path,
    monkeypatch,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    def forbidden_synthetic_preview(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "synthetic preview must not be used"
        )

    monkeypatch.setattr(
        orders.trading,
        "preview_limit_order",
        forbidden_synthetic_preview,
    )

    preview = {
        "source":
            "demo",
        "simulation":
            True,
        "market_data_source":
            "gate",
        "gate_read_performed":
            True,
        "gate_write_performed":
            False,
        "write_performed":
            False,
        "account_id":
            "demo-wallet-1",
        "status":
            "ready",
        "demo_execution_ready":
            True,
        "pair": {
            "id":
                "EQTY_USDT",
            "base":
                "EQTY",
            "quote":
                "USDT",
            "trade_status":
                "tradable",
            "precision":
                6,
            "amount_precision":
                2,
            "min_base_amount":
                "100",
            "min_quote_amount":
                "5",
        },
        "order": {
            "type":
                "limit",
            "account":
                "spot",
            "side":
                "buy",
            "price":
                "0.0042",
            "amount":
                "100000",
            "total":
                "420",
            "time_in_force":
                "gtc",
        },
        "market": {
            "best_bid":
                "0.00424",
            "best_ask":
                "0.00426",
            "marketable":
                False,
        },
        "funds": {
            "asset":
                "USDT",
            "available":
                "12500",
            "required":
                "420",
            "remaining":
                "12080",
        },
        "blockers":
            [],
        "warnings":
            [],
    }

    result = orders.create_limit_order(
        request_id=(
            "demo-order-request-public-preview-001"
        ),
        username="demo",
        account_id="demo-wallet-1",
        pair="EQTY_USDT",
        side="buy",
        price="0.0042",
        amount="100000",
        time_in_force="gtc",
        confirmation=(
            DEMO_TRADING_REQUIRED_CONFIRMATION
        ),
        preview=preview,
    )

    assert (
        result[
            "balance_reservation_performed"
        ]
        is True
    )

    # The store itself performed no Gate read.
    assert (
        result[
            "gate_read_performed"
        ]
        is False
    )

    stored = result[
        "order"
    ][
        "preview"
    ]

    assert (
        stored[
            "market_data_source"
        ]
        == "gate"
    )

    assert (
        stored[
            "gate_read_performed"
        ]
        is True
    )

    assert (
        stored[
            "market"
        ][
            "best_ask"
        ]
        == "0.00426"
    )

    available, locked = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    assert available == "12080"
    assert locked == "670"


def test_external_preview_safety_contract_fails_closed(
    tmp_path,
):
    database, *_, orders = (
        _stores(
            tmp_path
        )
    )

    orders.ensure_ready()

    before = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    unsafe_preview = {
        "source":
            "demo",
        "market_data_source":
            "gate",
        "gate_read_performed":
            True,
        "gate_write_performed":
            True,
        "write_performed":
            False,
        "account_id":
            "demo-wallet-1",
        "status":
            "ready",
        "demo_execution_ready":
            True,
        "pair": {
            "id":
                "EQTY_USDT",
        },
        "order": {
            "side":
                "buy",
            "price":
                "0.0042",
            "amount":
                "100000",
            "total":
                "420",
            "time_in_force":
                "gtc",
        },
        "funds": {
            "asset":
                "USDT",
            "available":
                "12500",
            "required":
                "420",
            "remaining":
                "12080",
        },
    }

    with pytest.raises(
        DemoTradingOrderError
    ):
        orders.create_limit_order(
            request_id=(
                "demo-order-request-public-preview-unsafe"
            ),
            username="demo",
            account_id="demo-wallet-1",
            pair="EQTY_USDT",
            side="buy",
            price="0.0042",
            amount="100000",
            time_in_force="gtc",
            confirmation=(
                DEMO_TRADING_REQUIRED_CONFIRMATION
            ),
            preview=unsafe_preview,
        )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == before
    )

    assert (
        _count(
            database,
            "demo_trading_orders",
        )
        == 0
    )
