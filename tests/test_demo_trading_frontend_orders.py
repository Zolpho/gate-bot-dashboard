from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

TRADING_JS = (
    ROOT / "frontend" / "trading.js"
).read_text(encoding="utf-8")

LIMIT_JS = (
    ROOT / "frontend" / "trading-limit.js"
).read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^(?:async\s+)?function\s+"
        rf"{re.escape(name)}\s*\(",
        source,
    )
    assert match is not None, name

    nxt = re.search(
        r"(?m)^(?:async\s+)?"
        r"function\s+"
        r"[A-Za-z0-9_$]+\s*\(",
        source[match.end():],
    )

    end = (
        match.end() + nxt.start()
        if nxt is not None
        else len(source)
    )

    return source[match.start():end]


def test_demo_orders_panel_copy_is_simulation_specific():
    body = _function(
        TRADING_JS,
        "tradingApplyDemoReadOnlyPresentation",
    )

    assert (
        "Simulated Demo open orders"
        in body
    )

    assert (
        "Isolated Demo history"
        in body
    )

    assert "'Demo ID'" in body
    assert "'Gate ID'" in body


def test_demo_open_loader_requires_no_gate_read():
    body = _function(
        TRADING_JS,
        "tradingLoadOpenOrders",
    )

    assert "const demo = isDemoSession();" in body
    assert "result?.source === 'demo'" in body
    assert "result?.simulation === true" in body
    assert "result?.gate_read_performed === false" in body
    assert "result?.gate_write_performed === false" in body
    assert "result?.write_performed === false" in body


def test_live_open_loader_still_requires_gate_read():
    body = _function(
        TRADING_JS,
        "tradingLoadOpenOrders",
    )

    assert (
        "result?.gate_read_performed === true"
        in body
    )

    assert (
        "'/api/trading/orders/open'"
        in body
    )


def test_demo_recent_loader_requires_demo_history_source():
    body = _function(
        TRADING_JS,
        "tradingLoadRecentOrders",
    )

    assert "const demo = isDemoSession();" in body
    assert "result?.source === 'demo'" in body
    assert "result?.simulation === true" in body

    assert (
        "result?.history_source === 'demo'"
        in body
    )

    assert (
        "result?.gate_read_performed === false"
        in body
    )


def test_live_recent_loader_keeps_dashboard_audit_contract():
    body = _function(
        TRADING_JS,
        "tradingLoadRecentOrders",
    )

    assert (
        "result?.history_source"
        in body
    )

    assert (
        "=== 'dashboard_audit'"
        in body
    )


def test_demo_refresh_calls_both_reviewed_order_reads():
    body = _function(
        TRADING_JS,
        "tradingRefreshPersistentOrders",
    )

    assert "if (isDemoSession())" not in body
    assert "tradingLoadOpenOrders" in body
    assert "tradingLoadRecentOrders" in body
    assert "Promise.all" in body


def test_demo_open_row_has_no_gate_or_live_action_dependency():
    body = _function(
        TRADING_JS,
        "tradingRenderDemoOpenOrderRow",
    )

    for forbidden in (
        "gate_order",
        "gate_order_id",
        "tradingPersistentCancelEligibility",
        "tradingPersistentAmendEligibility",
        "tradingPersistentAmendReconcileEligibility",
        "tradingLimitRecovery",
    ):
        assert forbidden not in body

    assert "tradingDemoCancelEligibility" in body
    assert ">Demo<" in body


def test_demo_open_renderer_returns_before_live_action_logic():
    body = _function(
        TRADING_JS,
        "tradingRenderOpenOrders",
    )

    demo_branch = body.index(
        "if (demo)"
    )

    demo_renderer = body.index(
        "tradingRenderDemoOpenOrderRow",
        demo_branch,
    )

    live_cancel = body.index(
        "tradingPersistentCancelEligibility"
    )

    assert (
        demo_branch
        < demo_renderer
        < live_cancel
    )


def test_demo_recent_row_has_no_recovery_or_reconcile_dependency():
    body = _function(
        TRADING_JS,
        "tradingRenderDemoRecentOrderRow",
    )

    for forbidden in (
        "gate_order",
        "gate_snapshot",
        "tradingRecentRecoveryEligibility",
        "tradingPersistentAmendReconcileEligibility",
        "recoverTradingLimit",
        "reconcile",
    ):
        assert forbidden not in body.lower()

    assert "Actions deferred" in body
    assert "request.request_id" in body


def test_demo_recent_renderer_returns_before_live_recovery_logic():
    body = _function(
        TRADING_JS,
        "tradingRenderRecentOrders",
    )

    demo_branch = body.index(
        "if (demo)"
    )

    demo_renderer = body.index(
        "tradingRenderDemoRecentOrderRow",
        demo_branch,
    )

    live_recovery = body.index(
        "tradingRecentRecoveryEligibility"
    )

    assert (
        demo_branch
        < demo_renderer
        < live_recovery
    )


def test_demo_create_refreshes_orders_and_balance_after_success():
    body = _function(
        LIMIT_JS,
        "placeTradingLimitOrder",
    )

    definitive = body.index(
        "if (definitive)"
    )

    demo_else = body.index(
        "} else {",
        definitive,
    )

    orders = body.index(
        "tradingRefreshPersistentOrders",
        demo_else,
    )

    snapshot = body.index(
        "tradingLoadSnapshot",
        orders,
    )

    assert definitive < demo_else < orders < snapshot

    segment = body[
        demo_else:
        snapshot + 200
    ]

    assert "Promise.allSettled" in segment
    assert "quiet: true" in segment


def test_demo_order_helpers_expose_only_demo_cancel_action():
    open_body = _function(
        TRADING_JS,
        "tradingRenderDemoOpenOrderRow",
    )

    recent_body = _function(
        TRADING_JS,
        "tradingRenderDemoRecentOrderRow",
    )

    assert (
        "data-trading-demo-cancel-request"
        in open_body
    )

    assert "Cancel Demo" in open_body

    assert (
        "data-trading-demo-cancel-request"
        not in recent_body
    )

    combined = open_body + recent_body

    for marker in (
        "data-trading-persistent-cancel-request",
        "data-trading-persistent-amend-request",
        "data-trading-amend-reconcile-request",
        "trading-orders-reconcile-button",
        "trading-orders-recover-button",
    ):
        assert marker not in combined
