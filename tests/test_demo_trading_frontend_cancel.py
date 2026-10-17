from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

TRADING_JS = (
    ROOT / "frontend" / "trading.js"
).read_text(encoding="utf-8")

TRADING_LIMIT_JS = (
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
        r"(?m)^(?:async\s+)?function\s+"
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


def test_demo_cancel_confirmation_is_request_id_scoped():
    body = _function(
        TRADING_JS,
        "tradingDemoCancelConfirmation",
    )

    assert (
        "'CANCEL DEMO LIMIT ORDER '"
        in body
    )

    assert "normalizedRequestId" in body


def test_demo_cancel_id_generator_is_separate_from_live_factory():
    body = _function(
        TRADING_JS,
        "tradingDemoCancelRequestId",
    )

    assert "demo-cancel-" in body
    assert "randomUUID" in body

    assert (
        "tradingLimitCancelRequestId"
        not in body
    )

    assert "Recovery" not in body


def test_demo_cancel_eligibility_uses_only_demo_request_state():
    body = _function(
        TRADING_JS,
        "tradingDemoCancelEligibility",
    )

    assert "isDemoSession()" in body
    assert "request.request_id" in body
    assert (
        "row?.order_state?.effective_status"
        in body
    )
    assert "demoOrder.status" in body
    assert "demoCancelPending" in body

    for forbidden in (
        "gateOrder",
        "gate_order",
        "cancel_arm_enabled",
        "tradingPersistentCancelEligibility",
        "tradingLimitRecovery",
        "sessionStorage",
    ):
        assert forbidden not in body


def test_demo_open_row_exposes_demo_cancel_only():
    body = _function(
        TRADING_JS,
        "tradingRenderDemoOpenOrderRow",
    )

    assert (
        "tradingDemoCancelEligibility"
        in body
    )

    assert (
        "data-trading-demo-cancel-request"
        in body
    )

    assert "Cancel Demo" in body

    for forbidden in (
        "data-trading-persistent-cancel-request",
        "data-trading-persistent-amend-request",
        "gateOrderId",
    ):
        assert forbidden not in body


def test_demo_recent_row_remains_action_free():
    body = _function(
        TRADING_JS,
        "tradingRenderDemoRecentOrderRow",
    )

    assert (
        "data-trading-demo-cancel-request"
        not in body
    )

    assert "Actions deferred" in body


def test_demo_cancel_resolves_exactly_one_authenticated_open_row():
    body = _function(
        TRADING_JS,
        "tradingCancelDemoOpenOrder",
    )

    assert (
        "tradingState.openOrders || []"
        in body
    )

    assert "matches.length !== 1" in body
    assert "row = matches[0]" in body

    assert (
        "tradingDemoCancelEligibility"
        in body
    )


def test_demo_cancel_requires_exact_confirmation():
    body = _function(
        TRADING_JS,
        "tradingCancelDemoOpenOrder",
    )

    assert "window.prompt" in body
    assert "expectedConfirmation" in body
    assert "typedConfirmation" in body

    assert (
        "!== expectedConfirmation"
        in body
    )

    assert (
        "No Gate order or real funds are involved."
        in body
    )


def test_demo_cancel_posts_only_demo_contract_fields():
    body = _function(
        TRADING_JS,
        "tradingCancelDemoOpenOrder",
    )

    assert (
        "'/api/trading/limit-orders/requests/'"
        in body
    )

    assert "'/cancel'" in body
    assert "method: 'POST'" in body
    assert "cancel_request_id:" in body
    assert "confirmation:" in body

    for forbidden in (
        "gate_order_id",
        "gateOrderId",
        "account_id:",
        "pair:",
    ):
        assert forbidden not in body


def test_demo_cancel_response_requires_isolated_demo_contract():
    body = _function(
        TRADING_JS,
        "tradingDemoCancellationResultValid",
    )

    for marker in (
        "result.source === 'demo'",
        "result.simulation === true",
        "result.gate_read_performed === false",
        "result.gate_write_performed === false",
        "result.write_performed === false",
        "result?.demo_write_performed === true",
        "result?.idempotent_replay === true",
        "result?.balance_release_performed === true",
        "cancellation.request_id",
        "cancellation.account_id",
        "cancellation.source === 'demo'",
        "=== 'cancelled'",
    ):
        assert marker in body


def test_demo_cancel_never_uses_live_recovery_or_cancel_arm():
    body = _function(
        TRADING_JS,
        "tradingCancelDemoOpenOrder",
    )

    for forbidden in (
        "cancel_arm_enabled",
        "tradingPersistentCancelEligibility",
        "tradingLimitRecoveryCheckpointWrite",
        "tradingLimitRecoveryClearKnownDefinitive",
        "sessionStorage",
        "/cancel/reconcile",
    ):
        assert forbidden not in body


def test_demo_cancel_refreshes_orders_and_balance_without_reconcile():
    body = _function(
        TRADING_JS,
        "tradingCancelDemoOpenOrder",
    )

    assert "Promise.allSettled" in body

    assert (
        "tradingRefreshPersistentOrders"
        in body
    )

    assert "tradingLoadSnapshot" in body
    assert "quiet: true" in body

    assert (
        "/cancel/reconcile"
        not in body
    )


def test_demo_cancel_event_binding_precedes_live_persistent_cancel():
    body = _function(
        TRADING_JS,
        "bindTradingEvents",
    )

    demo = body.index(
        "[data-trading-demo-cancel-request]"
    )

    live = body.index(
        "[data-trading-persistent-cancel-request]"
    )

    assert demo < live

    segment = body[
        demo:live
    ]

    assert (
        "tradingCancelDemoOpenOrder"
        in segment
    )

    assert "isDemoSession()" in segment

    assert (
        "tradingCancelPersistentOpenOrder"
        not in segment
    )

    assert (
        "tradingLimitRecoveryCheckpointWrite"
        not in segment
    )
