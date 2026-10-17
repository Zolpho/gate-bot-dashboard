from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

APP_JS = (
    ROOT / "frontend" / "app.js"
).read_text(encoding="utf-8")

TRADING_JS = (
    ROOT / "frontend" / "trading.js"
).read_text(encoding="utf-8")

TRADING_LIMIT_JS = (
    ROOT / "frontend" / "trading-limit.js"
).read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^(?:async\s+)?"
        rf"function\s+"
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

    return source[
        match.start():end
    ]


def test_demo_navigation_admits_only_reviewed_trading_slice():
    presentation = _function(
        APP_JS,
        "renderDemoPresentation",
    )

    for tab in (
        "overview",
        "bots",
        "wallet",
        "trading",
    ):
        assert f"'{tab}'" in presentation

    switch = _function(
        APP_JS,
        "switchTab",
    )

    guard_start = switch.index(
        "isDemoSession()"
    )

    guard_end = switch.index(
        "].includes(",
        guard_start,
    )

    guard = switch[
        guard_start:guard_end
    ]

    assert "'trading'" in guard
    assert "'security'" not in guard
    assert "'alerts'" not in guard
    assert "'donate'" not in guard


def test_demo_trading_page_copy_is_explicitly_simulated():
    switch = _function(
        APP_JS,
        "switchTab",
    )

    assert (
        "Synthetic Demo spot market"
        in switch
    )

    assert "no real funds" in switch

    assert (
        "Live Gate spot chart"
        in switch
    )


def test_demo_market_workspace_now_exposes_simulation_ticket():
    body = _function(
        TRADING_JS,
        "tradingApplyDemoReadOnlyPresentation",
    )

    assert "isDemoSession()" in body
    assert "#tradingLimitOrderForm" in body
    assert "classList.remove(" in body
    assert "SIMULATION" in body
    assert "simulated Demo balances" in body
    assert "synthetic order-book prices" in body


def test_demo_recovery_scope_exits_before_checkpoint_reader():
    body = _function(
        TRADING_JS,
        "tradingApplyRecoveryCheckpointScope",
    )

    guard = body.index(
        "if (isDemoSession())"
    )

    early_return = body.index(
        "return false;",
        guard,
    )

    reader = body.index(
        "tradingLimitRecoveryCheckpointForUser"
    )

    assert guard < early_return < reader


def test_demo_recovery_lookup_exits_before_live_recover_function():
    body = _function(
        TRADING_JS,
        "tradingRecoverSessionCheckpoint",
    )

    guard = body.index(
        "if (isDemoSession())"
    )

    status = body.index(
        "demo_not_applicable",
        guard,
    )

    recover = body.index(
        "recoverTradingLimitCheckpoint"
    )

    assert guard < status < recover

    assert (
        "definitive: true"
        in body[guard:recover]
    )


def test_demo_refresh_now_loads_reviewed_persistent_order_reads():
    body = _function(
        TRADING_JS,
        "tradingRefreshPersistentOrders",
    )

    assert (
        "if (isDemoSession())"
        not in body
    )

    assert (
        "tradingLoadOpenOrders"
        in body
    )

    assert (
        "tradingLoadRecentOrders"
        in body
    )

    assert (
        "Promise.all"
        in body
    )


def test_demo_activation_still_skips_capability_load_until_preview():
    body = _function(
        TRADING_JS,
        "activateTradingTab",
    )

    guard = body.index(
        "if (!isDemoSession())"
    )

    loader = body.index(
        "loadTradingExecutionCapabilities",
        guard,
    )

    demo_reset = body.index(
        (
            "tradingState."
            "limitOrderExecutionCapabilities = null"
        ),
        loader,
    )

    assert guard < loader < demo_reset


def test_demo_snapshot_copy_does_not_claim_gate_balance():
    snapshot = _function(
        TRADING_JS,
        "tradingRenderSnapshot",
    )

    assert (
        "Simulated Demo balances"
        in snapshot
    )

    assert "Gate spot" in snapshot


def test_live_recovery_key_remains_but_demo_has_own_capability():
    assert (
        "gate-dashboard.trading-recovery.v1"
        in TRADING_LIMIT_JS
    )

    assert (
        "globalThis.sessionStorage"
        in TRADING_LIMIT_JS
    )

    assert (
        "demo_execution_enabled"
        in TRADING_LIMIT_JS
    )

    assert (
        "tradingLimitDemoExecutionMode"
        in TRADING_LIMIT_JS
    )
