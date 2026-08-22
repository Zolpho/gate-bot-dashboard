from pathlib import Path


CORE = Path(
    "frontend/trading.js"
)

LIMIT = Path(
    "frontend/trading-limit.js"
)

CSS = Path(
    "frontend/trading-limit.css"
)


def _core() -> str:
    return CORE.read_text()


def _function(
    name: str,
) -> str:
    text = _core()

    markers = (
        f"function {name}(",
        f"async function {name}(",
    )

    starts = [
        text.find(marker)
        for marker in markers
        if text.find(marker) >= 0
    ]

    assert starts

    start = min(starts)

    candidates = []

    for marker in (
        "\nfunction ",
        "\nasync function ",
    ):
        position = text.find(
            marker,
            start + 10,
        )

        if position >= 0:
            candidates.append(position)

    end = (
        min(candidates)
        if candidates
        else len(text)
    )

    return text[start:end]


def test_manual_reconcile_adds_exactly_one_post_caller():
    core = _core()
    limit = LIMIT.read_text()

    assert core.count(
        "method: 'POST'"
    ) == 3

    assert limit.count(
        "method: 'POST'"
    ) == 5

    assert core.count(
        "+ '/amend'"
    ) == 1

    assert core.count(
        "+ '/amendments/'"
    ) == 1

    assert core.count(
        "+ '/reconcile'"
    ) == 1


def test_manual_reconcile_eligibility_requires_active_unresolved_audit():
    block = _function(
        "tradingPersistentAmendReconcileEligibility"
    )

    required = (
        "row?.active_amendment",
        "'amending'",
        "'uncertain'",
        "'attention'",
        "amendment.write_performed !== true",
        "amendment.completed_at",
        "amendment?.order_request_id",
        "amendment?.amend_request_id",
        "amendment?.gate_order_id",
    )

    for value in required:
        assert value in block


def test_manual_reconcile_is_not_gated_by_amend_write_arm():
    block = _function(
        "tradingPersistentAmendReconcileEligibility"
    )

    assert (
        "amend_reconciliation_implemented"
        in block
    )

    assert (
        "amend_reconciliation_route_available"
        in block
    )

    assert (
        "amend_reconciliation_gate_get_only"
        in block
    )

    # The explanatory source comment names the
    # arm, so check for actual property access.
    assert ".amend_arm_enabled" not in block


def test_manual_reconcile_requires_account_scope_and_gate_identity():
    block = _function(
        "tradingPersistentAmendReconcileEligibility"
    )

    required = (
        "authorized_account_ids",
        "configured_account_ids",
        "scope_mismatch",
        "sourceGateOrderId !== gateOrderId",
        "amendmentGateOrderId !== gateOrderId",
    )

    for value in required:
        assert value in block


def test_manual_reconcile_has_only_in_memory_pending_guard():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    assert (
        "persistentAmendReconcilePending"
        in block
    )

    assert "checkpointWriter" not in block

    assert (
        "tradingLimitRecoveryCheckpointWrite"
        not in block
    )

    assert "persistentAmendFrozen" not in block


def test_manual_reconcile_resolves_authenticated_open_or_recent_rows():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    assert (
        "tradingState.openOrders || []"
        in block
    )

    assert (
        "tradingState.recentOrders || []"
        in block
    )

    assert (
        "tradingPersistentAmendReconcileEligibility("
        in block
    )

    assert "identities.size !== 1" in block


def test_manual_reconcile_calls_exact_backend_route_once():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    assert block.count(
        "method: 'POST'"
    ) == 1

    required = (
        "'/api/trading/limit-orders/requests/'",
        "+ '/amendments/'",
        "+ '/reconcile'",
        "normalizedRequestId",
        "normalizedAmendRequestId",
    )

    for value in required:
        assert value in block


def test_manual_reconcile_validates_get_only_response_contract():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    required = (
        "result?.gate_read_performed",
        "result?.gate_write_performed",
        "result?.write_performed",
        "!== false",
        ".gate_read_performed",
        ".gate_write_performed",
        ".write_performed",
        ".manual_reconciliation",
        ".historical_amend_write_performed",
        ".order_request_id",
        ".amend_request_id",
    )

    for value in required:
        assert value in block


def test_manual_reconcile_validates_returned_amendment_identity():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    required = (
        "amendment.order_request_id",
        "amendment.amend_request_id",
        "amendment.gate_order_id",
        "amendment.requested_price",
        "expectedRequestedPrice",
        "audit identity mismatch",
    )

    for value in required:
        assert value in block


def test_manual_reconcile_failure_is_manually_retryable():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    assert (
        "This check cannot write Gate"
        in block
    )

    assert (
        "you may retry it manually"
        in block
    )

    assert "checkpointWriter" not in block
    assert "persistentAmendFrozen" not in block


def test_manual_reconcile_refreshes_and_rechecks_session_checkpoint():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    assert (
        "tradingRefreshPersistentOrders({"
        in block
    )

    assert (
        "tradingLoadSnapshot({"
        in block
    )

    assert (
        "tradingRecoverSessionCheckpoint({"
        in block
    )


def test_open_orders_expose_check_amendment_action():
    block = _function(
        "tradingRenderOpenOrders"
    )

    assert (
        "tradingPersistentAmendReconcileEligibility("
        in block
    )

    assert (
        "data-trading-amend-reconcile-request"
        in block
    )

    assert (
        "data-trading-amend-reconcile-id"
        in block
    )

    assert "Check amendment" in block


def test_recent_orders_expose_check_and_existing_recover_actions():
    block = _function(
        "tradingRenderRecentOrders"
    )

    assert (
        "tradingPersistentAmendReconcileEligibility("
        in block
    )

    assert (
        "data-trading-amend-reconcile-request"
        in block
    )

    assert (
        "data-trading-recover-request"
        in block
    )

    assert "Check amendment" in block
    assert "Recover" in block


def test_click_delegation_supports_reconcile_from_both_tables():
    block = _function(
        "bindTradingEvents"
    )

    assert block.count(
        "[data-trading-amend-reconcile-request]"
    ) == 2

    assert block.count(
        "tradingReconcilePersistentAmendment("
    ) == 2

    assert (
        "tradingAmendReconcileRequest"
        in block
    )

    assert (
        "tradingAmendReconcileId"
        in block
    )


def test_reconcile_button_has_dedicated_style():
    css = CSS.read_text()

    assert (
        ".trading-orders-reconcile-button"
        in css
    )


def test_b1_amend_write_remains_isolated_from_b2_reconcile():
    block = _function(
        "tradingAmendPersistentOpenOrder"
    )

    assert block.count(
        "method: 'POST'"
    ) == 1

    assert "+ '/amend'" in block
    assert "/amendments/" not in block
    assert "/reconcile" not in block


def test_manual_reconcile_fails_closed_on_any_conflicting_duplicate():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    assert (
        "eligible.length"
        in block
    )

    assert (
        "!== candidates.length"
        in block
    )

    assert (
        "Amendment reconciliation candidate "
        in block
    )

    assert (
        "conflict detected"
        in block
    )


def test_manual_reconcile_requires_positive_gate_get_proof():
    block = _function(
        "tradingReconcilePersistentAmendment"
    )

    assert (
        "result?.gate_read_performed"
        in block
    )

    assert (
        "reconciliation\n"
        "        .gate_read_performed\n"
        "        !== true"
        in block
    )

    assert (
        "result?.gate_read_performed\n"
        "        !== true"
        in block
    )
