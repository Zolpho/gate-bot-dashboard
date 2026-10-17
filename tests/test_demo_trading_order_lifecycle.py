from __future__ import annotations

import ast
import sqlite3

from pathlib import Path

import pytest

from app.demo_trading import (
    DEMO_TRADING_REQUIRED_CONFIRMATION,
)
from app.demo_trading_order_lifecycle import (
    DemoTradingOrderAmendmentConflict,
    DemoTradingOrderLifecycleError,
    DemoTradingOrderLifecycleStore,
    demo_trading_amend_confirmation_text,
    demo_trading_cancel_confirmation_text,
)
from app.demo_trading_orders import (
    DemoTradingOrderStore,
)


def _stores(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "demo.db"
    )

    orders = DemoTradingOrderStore(
        database
    )

    lifecycle = (
        DemoTradingOrderLifecycleStore(
            database
        )
    )

    return (
        database,
        orders,
        lifecycle,
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


def _buy(
    orders: DemoTradingOrderStore,
    request_id: str,
    *,
    price: str = "0.0042",
    tif: str = "gtc",
):
    return orders.create_limit_order(
        request_id=request_id,
        username="demo",
        account_id="demo-wallet-1",
        pair="EQTY_USDT",
        side="buy",
        price=price,
        amount="100000",
        time_in_force=tif,
        confirmation=(
            DEMO_TRADING_REQUIRED_CONFIRMATION
        ),
        occurred_at=(
            "2026-10-17T15:00:00+00:00"
        ),
    )


def _sell(
    orders: DemoTradingOrderStore,
    request_id: str,
):
    return orders.create_limit_order(
        request_id=request_id,
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
            "2026-10-17T15:00:00+00:00"
        ),
    )


def test_lifecycle_schema_is_additive_to_f7c_order_state(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    created = _buy(
        orders,
        "demo-order-life-schema-001",
    )

    before_order = orders.get_order(
        created["order"]["request_id"]
    )

    before_balance = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    lifecycle.ensure_ready()

    assert (
        _count(
            database,
            "demo_trading_order_cancellations",
        )
        == 0
    )

    assert (
        _count(
            database,
            "demo_trading_order_amendments",
        )
        == 0
    )

    assert (
        orders.get_order(
            created["order"]["request_id"]
        )
        == before_order
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == before_balance
    )


def test_cancel_buy_requires_demo_confirmation_and_releases_quote(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-cancel-buy-001"
    )

    _buy(
        orders,
        request_id,
    )

    before = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    assert before == (
        "12080",
        "670",
    )

    with pytest.raises(
        DemoTradingOrderLifecycleError
    ):
        lifecycle.cancel_order(
            request_id=request_id,
            username="demo",
            confirmation=(
                "CANCEL LIVE LIMIT ORDER"
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

    result = lifecycle.cancel_order(
        request_id=request_id,
        username="demo",
        confirmation=(
            demo_trading_cancel_confirmation_text(
                request_id
            )
        ),
        occurred_at=(
            "2026-10-17T15:01:00+00:00"
        ),
    )

    assert (
        result[
            "balance_release_performed"
        ]
        is True
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    order = result[
        "cancellation"
    ][
        "order"
    ]

    assert order["status"] == "cancelled"
    assert order["reserved_amount"] == "0"
    assert order["balance_reserved"] is False

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == (
            "12500",
            "250",
        )
    )

    assert (
        _count(
            database,
            "demo_trading_order_cancellations",
        )
        == 1
    )


def test_cancel_sell_releases_base_reservation(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-cancel-sell-001"
    )

    _sell(
        orders,
        request_id,
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "EQTY",
        )
        == (
            "650000",
            "200000",
        )
    )

    result = lifecycle.cancel_order(
        request_id=request_id,
        username="demo",
        confirmation=(
            demo_trading_cancel_confirmation_text(
                request_id
            )
        ),
    )

    assert (
        result[
            "cancellation"
        ][
            "released_asset"
        ]
        == "EQTY"
    )

    assert (
        result[
            "cancellation"
        ][
            "released_amount"
        ]
        == "100000"
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "EQTY",
        )
        == (
            "750000",
            "100000",
        )
    )


def test_cancel_replay_is_terminal_and_never_releases_twice(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-cancel-replay-001"
    )

    _buy(
        orders,
        request_id,
    )

    first = lifecycle.cancel_order(
        request_id=request_id,
        username="demo",
        confirmation=(
            demo_trading_cancel_confirmation_text(
                request_id
            )
        ),
    )

    after_first = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    replay = lifecycle.cancel_order(
        request_id=request_id,
        username="demo",
        confirmation="STALE CONFIRMATION",
    )

    assert (
        first[
            "idempotent_replay"
        ]
        is False
    )

    assert (
        replay[
            "idempotent_replay"
        ]
        is True
    )

    assert (
        replay[
            "balance_release_performed"
        ]
        is False
    )

    assert (
        replay[
            "demo_write_performed"
        ]
        is False
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == after_first
    )

    assert (
        _count(
            database,
            "demo_trading_order_cancellations",
        )
        == 1
    )

    assert (
        len(
            orders.list_events(
                request_id
            )
        )
        == 2
    )

    with pytest.raises(
        DemoTradingOrderLifecycleError
    ):
        lifecycle.amend_order_price(
            amendment_id=
                "demo-amend-cancelled-001",
            request_id=request_id,
            username="demo",
            new_price="0.0044",
            confirmation=(
                demo_trading_amend_confirmation_text(
                    request_id,
                    "0.0044",
                )
            ),
        )


def test_buy_amend_higher_reserves_only_quote_delta(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-amend-up-001"
    )

    _buy(
        orders,
        request_id,
    )

    result = lifecycle.amend_order_price(
        amendment_id=
            "demo-amend-up-001",
        request_id=request_id,
        username="demo",
        new_price="0.005",
        confirmation=(
            demo_trading_amend_confirmation_text(
                request_id,
                "0.005",
            )
        ),
    )

    amendment = result[
        "amendment"
    ]

    assert (
        amendment[
            "old_reserved_amount"
        ]
        == "420"
    )

    assert (
        amendment[
            "new_reserved_amount"
        ]
        == "500"
    )

    assert (
        amendment[
            "reservation_delta"
        ]
        == "80"
    )

    assert (
        amendment["order"]["price"]
        == "0.005"
    )

    assert (
        amendment[
            "order"
        ][
            "reserved_amount"
        ]
        == "500"
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == (
            "12000",
            "750",
        )
    )


def test_buy_amend_lower_releases_only_quote_delta(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-amend-down-001"
    )

    _buy(
        orders,
        request_id,
    )

    result = lifecycle.amend_order_price(
        amendment_id=
            "demo-amend-down-001",
        request_id=request_id,
        username="demo",
        new_price="0.004",
        confirmation=(
            demo_trading_amend_confirmation_text(
                request_id,
                "0.004",
            )
        ),
    )

    amendment = result[
        "amendment"
    ]

    assert (
        amendment[
            "reservation_delta"
        ]
        == "-20"
    )

    assert (
        amendment[
            "new_reserved_amount"
        ]
        == "400"
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == (
            "12100",
            "650",
        )
    )


def test_sell_price_amend_preserves_base_reservation(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-amend-sell-001"
    )

    _sell(
        orders,
        request_id,
    )

    before = _asset(
        database,
        "demo-wallet-1",
        "EQTY",
    )

    result = lifecycle.amend_order_price(
        amendment_id=
            "demo-amend-sell-001",
        request_id=request_id,
        username="demo",
        new_price="0.0044",
        confirmation=(
            demo_trading_amend_confirmation_text(
                request_id,
                "0.0044",
            )
        ),
    )

    amendment = result[
        "amendment"
    ]

    assert (
        amendment[
            "reservation_delta"
        ]
        == "0"
    )

    assert (
        amendment[
            "new_reserved_amount"
        ]
        == "100000"
    )

    assert (
        result[
            "balance_adjustment_performed"
        ]
        is False
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "EQTY",
        )
        == before
    )


def test_amendment_replay_precedes_fresh_validation_and_conflict_is_safe(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-amend-replay-001"
    )

    amendment_id = (
        "demo-amend-replay-001"
    )

    _buy(
        orders,
        request_id,
    )

    first = lifecycle.amend_order_price(
        amendment_id=amendment_id,
        request_id=request_id,
        username="demo",
        new_price="0.005",
        confirmation=(
            demo_trading_amend_confirmation_text(
                request_id,
                "0.005",
            )
        ),
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

    replay = lifecycle.amend_order_price(
        amendment_id=amendment_id,
        request_id=request_id,
        username="demo",
        new_price="0.005",
        confirmation="STALE CONFIRMATION",
    )

    assert (
        first[
            "idempotent_replay"
        ]
        is False
    )

    assert (
        replay[
            "idempotent_replay"
        ]
        is True
    )

    assert (
        replay[
            "demo_write_performed"
        ]
        is False
    )

    assert (
        replay[
            "balance_adjustment_performed"
        ]
        is False
    )

    assert (
        replay[
            "amendment"
        ][
            "new_price"
        ]
        == "0.005"
    )

    with pytest.raises(
        DemoTradingOrderAmendmentConflict
    ):
        lifecycle.amend_order_price(
            amendment_id=amendment_id,
            request_id=request_id,
            username="demo",
            new_price="0.006",
            confirmation="IGNORED",
        )

    assert (
        _count(
            database,
            "demo_trading_order_amendments",
        )
        == 1
    )

    assert (
        len(
            orders.list_events(
                request_id
            )
        )
        == 2
    )


def test_blocked_amendments_leave_order_and_balances_unchanged(
    tmp_path,
):
    database, orders, lifecycle = (
        _stores(
            tmp_path
        )
    )

    request_id = (
        "demo-order-life-amend-blocked-001"
    )

    _buy(
        orders,
        request_id,
        price="0.004",
        tif="poc",
    )

    before_order = orders.get_order(
        request_id
    )

    before_balance = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    with pytest.raises(
        DemoTradingOrderLifecycleError
    ):
        lifecycle.amend_order_price(
            amendment_id=
                "demo-amend-blocked-poc-001",
            request_id=request_id,
            username="demo",
            new_price="0.0043",
            confirmation=(
                demo_trading_amend_confirmation_text(
                    request_id,
                    "0.0043",
                )
            ),
        )

    with pytest.raises(
        DemoTradingOrderLifecycleError
    ):
        lifecycle.amend_order_price(
            amendment_id=
                "demo-amend-blocked-precision-001",
            request_id=request_id,
            username="demo",
            new_price="0.0042001",
            confirmation=(
                demo_trading_amend_confirmation_text(
                    request_id,
                    "0.0042001",
                )
            ),
        )

    with pytest.raises(
        DemoTradingOrderLifecycleError
    ):
        lifecycle.amend_order_price(
            amendment_id=
                "demo-amend-blocked-funds-001",
            request_id=request_id,
            username="demo",
            new_price="1",
            confirmation=(
                demo_trading_amend_confirmation_text(
                    request_id,
                    "1",
                )
            ),
        )

    assert (
        orders.get_order(
            request_id
        )
        == before_order
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == before_balance
    )

    assert (
        _count(
            database,
            "demo_trading_order_amendments",
        )
        == 0
    )


def test_demo_order_lifecycle_has_no_gate_production_route_or_recovery_dependency():
    path = Path(
        "app/demo_trading_order_lifecycle.py"
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

    for marker in (
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
        "reconcile",
    ):
        assert marker not in source
