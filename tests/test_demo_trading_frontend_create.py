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


def test_demo_ticket_is_visible_and_marked_simulation():
    body = _function(
        TRADING_JS,
        "tradingApplyDemoReadOnlyPresentation",
    )

    assert "#tradingLimitOrderForm" in body
    assert "classList.remove(" in body
    assert "SIMULATION" in body
    assert "simulated Demo balances" in body


def test_demo_capability_validator_requires_demo_not_live_arm():
    body = _function(
        LIMIT_JS,
        "tradingLimitDemoCapabilitiesValid",
    )

    for marker in (
        "result.source === 'demo'",
        "result.simulation === true",
        "result.gate_read_performed === false",
        "result.gate_write_performed === false",
        "result.write_performed === false",
        "result.live_arm_enabled === false",
        "result.demo_execution_enabled === true",
    ):
        assert marker in body


def test_demo_preview_validator_requires_executable_no_write_contract():
    body = _function(
        LIMIT_JS,
        "tradingLimitDemoPreviewValid",
    )

    assert "result.preview_only === true" in body
    assert "result.can_execute" in body
    assert "result.demo_execution_ready" in body
    assert "result.gate_write_required === false" in body
    assert "result.gate_write_performed === false" in body


def test_capability_loader_has_separate_demo_validation():
    body = _function(
        LIMIT_JS,
        "loadTradingExecutionCapabilities",
    )

    assert (
        "tradingLimitDemoExecutionMode()"
        in body
    )

    assert (
        "tradingLimitDemoCapabilitiesValid"
        in body
    )

    assert (
        "result.amend_reconciliation_implemented !== true"
        in body
    )

    assert (
        "result.gate_write_performed !== false"
        in body
    )


def test_preview_has_separate_demo_and_live_safety_contracts():
    body = _function(
        LIMIT_JS,
        "reviewTradingLimitOrder",
    )

    assert (
        "tradingLimitDemoPreviewValid"
        in body
    )

    assert (
        "result.execution_implemented !== false"
        in body
    )

    assert (
        "result.can_execute !== false"
        in body
    )

    assert (
        "await loadTradingExecutionCapabilities();"
        in body
    )


def test_demo_readiness_uses_demo_execution_enabled():
    body = _function(
        LIMIT_JS,
        "renderTradingLimitExecution",
    )

    assert "demo_execution_enabled" in body
    assert "executionSwitchEnabled" in body
    assert "SIMULATION READY" in body
    assert "No Gate order" in body
    assert "Simulate limit order" in body


def test_demo_create_does_not_require_live_arm():
    body = _function(
        LIMIT_JS,
        "placeTradingLimitOrder",
    )

    demo_pos = body.index(
        "demo_execution_enabled"
    )

    live_pos = body.index(
        "live_arm_enabled"
    )

    segment = body[
        max(0, demo_pos - 160):
        live_pos + 160
    ]

    assert "demo" in segment


def test_demo_create_skips_recovery_checkpoint_write():
    body = _function(
        LIMIT_JS,
        "placeTradingLimitOrder",
    )

    checkpoint = body.index(
        "tradingLimitRecoveryCheckpointWrite"
    )

    prefix = body[
        max(0, checkpoint - 1800):
        checkpoint
    ]

    assert "if (!demo)" in prefix

    post = body.index(
        "'/api/trading/limit-orders/execute'"
    )

    assert checkpoint < post


def test_demo_success_requires_isolated_open_order():
    body = _function(
        LIMIT_JS,
        "tradingLimitDemoExecutionResultValid",
    )

    assert "result.source === 'demo'" in body
    assert "result.gate_write_performed === false" in body
    assert "result.write_performed === false" in body
    assert "result?.order?.status" in body
    assert "=== 'open'" in body


def test_demo_success_message_never_claims_gate_submission():
    body = _function(
        LIMIT_JS,
        "tradingLimitDemoExecutionMessage",
    )

    assert (
        "Simulated Demo limit order"
        in body
    )

    assert (
        "No Gate order was submitted."
        in body
    )

    assert (
        "balance reservation"
        in body
        or "balance was reserved"
        in body
    )


def test_demo_create_does_not_clear_live_recovery_checkpoint():
    body = _function(
        LIMIT_JS,
        "placeTradingLimitOrder",
    )

    occurrences = list(
        re.finditer(
            "tradingLimitRecoveryClearKnownDefinitive",
            body,
        )
    )

    assert occurrences

    for match in occurrences:
        prefix = body[
            max(0, match.start() - 220):
            match.start()
        ]

        assert "!demo" in prefix


def test_demo_cancel_ui_remains_hard_hidden():
    body = _function(
        LIMIT_JS,
        "renderTradingLimitCancellationReadiness",
    )

    guard = body.index(
        "tradingLimitDemoExecutionMode()"
    )

    hidden = body.index(
        "classList.add(",
        guard,
    )

    early_return = body.index(
        "return;",
        hidden,
    )

    assert guard < hidden < early_return
    assert "#tradingLimitCancellation" in body
