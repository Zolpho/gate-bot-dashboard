from __future__ import annotations

import ast
import sqlite3

from pathlib import Path

import pytest

from app.demo_trading import (
    DEMO_TRADING_REQUIRED_CONFIRMATION,
)
from app.demo_trading_api import (
    DemoTradingApi,
    DemoTradingAuthorizationError,
)
from app.demo_trading_order_lifecycle import (
    demo_trading_amend_confirmation_text,
    demo_trading_cancel_confirmation_text,
)


def _api(
    tmp_path: Path,
) -> tuple[
    Path,
    DemoTradingApi,
]:
    database = (
        tmp_path
        / "demo.db"
    )

    return (
        database,
        DemoTradingApi(
            database
        ),
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


def _execute_buy(
    api: DemoTradingApi,
    request_id: str,
):
    return api.execute_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=request_id,
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
    )


def test_catalog_is_demo_scoped_and_live_shape_compatible(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    result = api.catalog_payload(
        account_ids={
            "demo-wallet-2",
        }
    )

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

    assert [
        row["id"]
        for row in result[
            "accounts"
        ]
    ] == [
        "demo-wallet-2",
    ]

    pair = next(
        row
        for row in result[
            "pairs"
        ]
        if row["id"]
        == "EQTY_USDT"
    )

    assert (
        pair[
            "trade_status"
        ]
        == "tradable"
    )

    assert (
        pair[
            "min_base_amount"
        ]
        == "100"
    )

    assert (
        pair[
            "min_quote_amount"
        ]
        == "5"
    )


def test_snapshot_is_wallet_scoped_and_never_reads_gate(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    result = api.snapshot_payload(
        account_ids={
            "demo-wallet-1",
        },
        account_id=
            "demo-wallet-1",
        pair="EQTY_USDT",
        depth=20,
        book_interval="0.0001",
    )

    assert (
        result[
            "account"
        ]["id"]
        == "demo-wallet-1"
    )

    assert (
        result["pair"]["id"]
        == "EQTY_USDT"
    )

    assert (
        result[
            "book_interval"
        ]
        == "0.0001"
    )

    assert (
        result[
            "balances"
        ][
            "quote"
        ][
            "available"
        ]
        == "12500"
    )

    assert (
        result[
            "gate_read_performed"
        ]
        is False
    )

    with pytest.raises(
        DemoTradingAuthorizationError
    ):
        api.snapshot_payload(
            account_ids={
                "demo-wallet-1",
            },
            account_id=
                "demo-wallet-2",
            pair="EQTY_USDT",
            depth=20,
            book_interval="0",
        )


def test_candles_and_trades_use_frontend_compatible_synthetic_shapes(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    candles = api.candles_payload(
        account_ids={
            "demo-wallet-1",
        },
        account_id=
            "demo-wallet-1",
        pair="ETH_USDT",
        interval="1h",
        limit=50,
    )

    trades = api.trades_payload(
        account_ids={
            "demo-wallet-1",
        },
        account_id=
            "demo-wallet-1",
        pair="ETH_USDT",
        limit=10,
    )

    assert (
        len(
            candles[
                "candles"
            ]
        )
        == 50
    )

    assert (
        len(
            trades[
                "trades"
            ]
        )
        == 10
    )

    trade = trades[
        "trades"
    ][0]

    assert (
        "time_ms"
        in trade
    )

    assert (
        "total"
        in trade
    )

    assert (
        candles[
            "gate_read_performed"
        ]
        is False
    )

    assert (
        trades[
            "gate_read_performed"
        ]
        is False
    )


def test_execution_capabilities_are_demo_only_and_have_no_recovery_authority(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    result = (
        api
        .execution_capabilities_payload(
            account_ids={
                "demo-wallet-1",
                "demo-wallet-2",
            }
        )
    )

    assert (
        result[
            "live_arm_enabled"
        ]
        is False
    )

    assert (
        result[
            "demo_execution_enabled"
        ]
        is True
    )

    assert (
        result[
            "demo_cancellation_enabled"
        ]
        is True
    )

    assert (
        result[
            "demo_amendment_enabled"
        ]
        is True
    )

    assert (
        result[
            "required_confirmation"
        ]
        == DEMO_TRADING_REQUIRED_CONFIRMATION
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )


def test_preview_preserves_demo_contract_and_exposes_execution_readiness(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    ready = api.preview_payload(
        account_ids={
            "demo-wallet-1",
        },
        account_id=
            "demo-wallet-1",
        pair="EQTY_USDT",
        side="buy",
        price="0.0042",
        amount="100000",
        time_in_force="gtc",
    )

    blocked = api.preview_payload(
        account_ids={
            "demo-wallet-1",
        },
        account_id=
            "demo-wallet-1",
        pair="EQTY_USDT",
        side="buy",
        price="0.0043",
        amount="100000",
        time_in_force="poc",
    )

    assert (
        ready["status"]
        == "ready"
    )

    assert (
        ready[
            "execution_enabled"
        ]
        is True
    )

    assert (
        ready[
            "gate_write_required"
        ]
        is False
    )

    assert (
        ready[
            "pair"
        ][
            "min_base_amount"
        ]
        == "100"
    )

    assert (
        blocked[
            "execution_enabled"
        ]
        is False
    )

    assert (
        blocked[
            "demo_execution_ready"
        ]
        is False
    )


def test_execute_adapter_reserves_only_demo_wallet_balance(
    tmp_path,
):
    database, api = _api(
        tmp_path
    )

    result = _execute_buy(
        api,
        "demo-api-execute-001",
    )

    assert (
        result[
            "source"
        ]
        == "demo"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        result[
            "balance_reservation_performed"
        ]
        is True
    )

    assert (
        result[
            "order"
        ][
            "status"
        ]
        == "open"
    )

    assert (
        _asset(
            database,
            "demo-wallet-1",
            "USDT",
        )
        == (
            "12080",
            "670",
        )
    )


def test_execute_adapter_replay_cannot_reserve_twice(
    tmp_path,
):
    database, api = _api(
        tmp_path
    )

    first = _execute_buy(
        api,
        "demo-api-execute-replay-001",
    )

    after_first = _asset(
        database,
        "demo-wallet-1",
        "USDT",
    )

    replay = _execute_buy(
        api,
        "demo-api-execute-replay-001",
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
            "balance_reservation_performed"
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


def test_open_and_recent_order_reads_are_demo_account_scoped(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    _execute_buy(
        api,
        "demo-api-orders-growth-001",
    )

    api.execute_payload(
        account_ids={
            "demo-wallet-2",
        },
        request_id=
            "demo-api-orders-treasury-001",
        username="demo",
        account_id=
            "demo-wallet-2",
        pair="EQTY_USDT",
        side="buy",
        price="0.0041",
        amount="100000",
        time_in_force="gtc",
        confirmation=(
            DEMO_TRADING_REQUIRED_CONFIRMATION
        ),
    )

    opened = api.open_orders_payload(
        account_ids={
            "demo-wallet-1",
        },
        account_id=
            "demo-wallet-1",
        pair=None,
        limit=100,
    )

    recent = api.recent_orders_payload(
        account_ids={
            "demo-wallet-1",
        },
        account_id=
            "demo-wallet-1",
        pair="EQTY_USDT",
        limit=100,
    )

    assert (
        opened["count"]
        == 1
    )

    assert (
        recent["count"]
        == 1
    )

    for result in (
        opened,
        recent,
    ):
        row = result[
            "orders"
        ][0]

        assert (
            row["managed"]
            is True
        )

        assert (
            row[
                "request"
            ][
                "account_id"
            ]
            == "demo-wallet-1"
        )

        assert (
            row[
                "order_state"
            ][
                "effective_status"
            ]
            == "confirmed_open"
        )

        assert (
            "demo_order"
            in row
        )


def test_detail_includes_events_amendments_and_cancellation_without_reconciliation(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    request_id = (
        "demo-api-detail-001"
    )

    _execute_buy(
        api,
        request_id,
    )

    amend_confirmation = (
        demo_trading_amend_confirmation_text(
            request_id,
            "0.005",
        )
    )

    api.amend_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
        amend_request_id=
            "demo-api-amend-detail-001",
        username="demo",
        requested_price="0.005",
        confirmation=
            amend_confirmation,
    )

    cancel_confirmation = (
        demo_trading_cancel_confirmation_text(
            request_id
        )
    )

    api.cancel_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
        cancel_request_id=
            "demo-api-cancel-detail-001",
        username="demo",
        confirmation=
            cancel_confirmation,
    )

    result = api.order_detail_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
    )

    assert (
        result[
            "order_state"
        ][
            "effective_status"
        ]
        == "confirmed_cancelled"
    )

    assert (
        result[
            "order_state"
        ][
            "terminal"
        ]
        is True
    )

    assert (
        len(
            result[
                "events"
            ]
        )
        == 3
    )

    assert (
        len(
            result[
                "amendments"
            ]
        )
        == 1
    )

    assert (
        result[
            "cancellation"
        ]
        is not None
    )

    assert (
        result[
            "reconciliations"
        ]
        == []
    )

    assert (
        result["lock"]
        is None
    )


def test_cancel_adapter_releases_once_and_preserves_demo_cancel_id(
    tmp_path,
):
    database, api = _api(
        tmp_path
    )

    request_id = (
        "demo-api-cancel-001"
    )

    _execute_buy(
        api,
        request_id,
    )

    confirmation = (
        demo_trading_cancel_confirmation_text(
            request_id
        )
    )

    first = api.cancel_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
        cancel_request_id=
            "demo-api-cancel-token-001",
        username="demo",
        confirmation=
            confirmation,
    )

    replay = api.cancel_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
        cancel_request_id=
            "demo-api-cancel-token-001",
        username="demo",
        confirmation=
            "STALE CONFIRMATION",
    )

    assert (
        first[
            "balance_release_performed"
        ]
        is True
    )

    assert (
        first[
            "cancel_request_id"
        ]
        == "demo-api-cancel-token-001"
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


def test_amend_adapter_uses_amend_request_id_and_adjusts_only_demo_reservation(
    tmp_path,
):
    database, api = _api(
        tmp_path
    )

    request_id = (
        "demo-api-amend-001"
    )

    _execute_buy(
        api,
        request_id,
    )

    result = api.amend_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
        amend_request_id=
            "demo-api-amend-token-001",
        username="demo",
        requested_price="0.005",
        confirmation=(
            demo_trading_amend_confirmation_text(
                request_id,
                "0.005",
            )
        ),
    )

    assert (
        result[
            "amendment"
        ][
            "amendment_id"
        ]
        == "demo-api-amend-token-001"
    )

    assert (
        result[
            "amendment"
        ][
            "reservation_delta"
        ]
        == "80"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
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


def test_confirmation_adapter_is_scoped_and_uses_explicit_demo_language(
    tmp_path,
):
    _database, api = _api(
        tmp_path
    )

    request_id = (
        "demo-api-confirmation-001"
    )

    _execute_buy(
        api,
        request_id,
    )

    cancel = api.confirmation_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
        operation="cancel",
    )

    amend = api.confirmation_payload(
        account_ids={
            "demo-wallet-1",
        },
        request_id=
            request_id,
        operation="amend",
        requested_price="0.005",
    )

    assert (
        cancel[
            "required_confirmation"
        ]
        == (
            "CANCEL DEMO LIMIT ORDER "
            + request_id
        )
    )

    assert (
        amend[
            "required_confirmation"
        ]
        == (
            "AMEND DEMO LIMIT ORDER "
            + request_id
            + " PRICE 0.005"
        )
    )

    with pytest.raises(
        KeyError
    ):
        api.confirmation_payload(
            account_ids={
                "demo-wallet-2",
            },
            request_id=
                request_id,
            operation="cancel",
        )


def test_demo_trading_api_has_no_live_gate_route_config_or_recovery_dependency():
    path = Path(
        "app/demo_trading_api.py"
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
        "api.trading",
    )

    for module in imports:
        lowered = module.lower()

        assert not any(
            fragment
            in lowered
            for fragment
            in forbidden_import_fragments
        ), module

    forbidden_markers = (
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

    for marker in forbidden_markers:
        assert marker not in source

    methods = {
        node.name
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    assert not any(
        "reconcile"
        in method.lower()
        for method in methods
    )
