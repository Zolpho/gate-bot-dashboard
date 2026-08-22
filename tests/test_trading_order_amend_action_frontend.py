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


def _limit() -> str:
    return LIMIT.read_text()


def _function(
    text: str,
    name: str,
) -> str:
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


def test_amend_action_has_exactly_one_write_surface():
    core = _core()
    limit = _limit()

    amend = _function(
        core,
        "tradingAmendPersistentOpenOrder",
    )

    assert amend.count(
        "method: 'POST'"
    ) == 1

    assert amend.count(
        "+ '/amend'"
    ) == 1

    assert "/amendments/" not in amend
    assert "/reconcile" not in amend

    # Recovery module itself still owns no
    # amendment write route.
    assert limit.count(
        "method: 'POST'"
    ) == 5

    assert "/amend" not in limit


def test_amend_eligibility_is_capability_and_arm_gated():
    block = _function(
        _core(),
        "tradingPersistentAmendEligibility",
    )

    required = (
        "amendment_implemented",
        "amendment_route_available",
        "amend_arm_enabled",
        "amend_required_confirmation",
        "authorized_account_ids",
        "configured_account_ids",
        "Amend disabled",
    )

    for value in required:
        assert value in block


def test_amend_eligibility_requires_managed_open_limit_identity():
    block = _function(
        _core(),
        "tradingPersistentAmendEligibility",
    )

    required = (
        "row?.managed",
        "identity_conflict",
        "state_conflict",
        "request.write_performed",
        "request.order_type",
        "'submitted'",
        "'confirmed_open'",
        "gateStatus !== 'open'",
        "localGateOrderId !== gateOrderId",
        "scope_mismatch",
    )

    for value in required:
        assert value in block


def test_amendment_and_cancellation_conflict_in_both_directions():
    core = _core()

    amend = _function(
        core,
        "tradingPersistentAmendEligibility",
    )

    cancel = _function(
        core,
        "tradingPersistentCancelEligibility",
    )

    assert "row?.cancellation" in amend
    assert "row?.active_amendment" in amend
    assert "persistentCancelPending" in amend
    assert "persistentCancelFrozen" in amend

    assert "row?.active_amendment" in cancel
    assert "persistentAmendPending" in cancel
    assert "persistentAmendFrozen" in cancel


def test_amend_action_rechecks_authenticated_row_not_dom_identity():
    block = _function(
        _core(),
        "tradingAmendPersistentOpenOrder",
    )

    assert "tradingState.openOrders || []" in block
    assert "matches.length !== 1" in block
    assert "tradingPersistentAmendEligibility(" in block


def test_amend_checkpoint_is_written_before_post():
    block = _function(
        _core(),
        "tradingAmendPersistentOpenOrder",
    )

    checkpoint = block.index(
        "checkpointWriter({"
    )

    post = block.index(
        "method: 'POST'"
    )

    assert checkpoint < post

    required = (
        "kind: 'amendment'",
        "amendRequestId",
        "gateOrderId:",
        "requestedPrice",
    )

    for value in required:
        assert value in block[
            checkpoint:post
        ]


def test_amend_post_body_uses_exact_backend_contract():
    block = _function(
        _core(),
        "tradingAmendPersistentOpenOrder",
    )

    assert (
        "'/api/trading/limit-orders/requests/'"
        in block
    )

    assert "+ '/amend'" in block

    required = (
        "amend_request_id:",
        "requested_price:",
        "confirmation:",
    )

    for value in required:
        assert value in block


def test_amend_response_identity_is_fail_closed():
    block = _function(
        _core(),
        "tradingAmendPersistentOpenOrder",
    )

    required = (
        "result?.status",
        "result?.definitive",
        "result?.gate_write_performed",
        "result?.write_performed",
        "result?.manual_review_required",
        "result?.order_request_id",
        "result?.amend_request_id",
        "amendment.order_request_id",
        "amendment.amend_request_id",
        "amendment.gate_order_id",
        "amendment.requested_price",
        "audit identity mismatch",
    )

    for value in required:
        assert value in block


def test_structured_no_write_denial_clears_checkpoint():
    block = _function(
        _core(),
        "tradingAmendPersistentOpenOrder",
    )

    required = (
        "structuredNoWriteDenial",
        "detail.gate_write_performed",
        "detail.write_performed",
        "=== false",
        "tradingLimitRecoveryClearKnownDefinitive",
        "kind: 'amendment'",
    )

    for value in required:
        assert value in block


def test_ambiguous_amendment_never_auto_retries():
    block = _function(
        _core(),
        "tradingAmendPersistentOpenOrder",
    )

    assert block.count(
        "method: 'POST'"
    ) == 1

    assert "'client_uncertain'" in block
    assert "persistentAmendFrozen" in block
    assert "Do not send another Trading write" in block
    assert "/reconcile" not in block
    assert "/amendments/" not in block


def test_amend_request_id_generator_is_exported():
    limit = _limit()

    generator = _function(
        limit,
        "tradingLimitAmendRequestId",
    )

    assert "`amend-ui-${timestamp}-${random}`" in generator
    assert ".slice(0, 128)" in generator

    assert (
        "window.tradingLimitAmendRequestId = ("
        in limit
    )

    assert (
        "window.tradingLimitRecoveryDecimalIdentity = ("
        in limit
    )


def test_open_orders_delegates_amend_click():
    core = _core()

    assert (
        "data-trading-persistent-amend-request"
        in core
    )

    assert (
        "tradingPersistentAmendRequest"
        in core
    )

    assert (
        "tradingAmendPersistentOpenOrder("
        in core
    )


def test_amend_button_has_dedicated_style():
    css = CSS.read_text()

    assert (
        ".trading-orders-amend-button"
        in css
    )

    assert (
        ".trading-orders-action-buttons"
        in css
    )


def test_cancel_blocks_global_unresolved_recovery_state():
    block = _function(
        _core(),
        "tradingPersistentCancelEligibility",
    )

    required = (
        "limitOrderExecutionAttempt",
        "limitOrderCancellationAttempt",
        "limitOrderAmendmentAttempt",
        "unresolvedAttempt",
        "Recovery required",
        "tradingLimitRecoveryCheckpointForUser",
        "checkpoint_present",
        "checkpoint_error",
    )

    for value in required:
        assert value in block


def test_no_write_denial_requires_matching_http_status_identity():
    block = _function(
        _core(),
        "tradingAmendPersistentOpenOrder",
    )

    required = (
        "const errorStatus = Number(",
        "error?.status || 0",
        "const detailStatus = Number(",
        "detail?.status_code || 0",
        "detailStatus === errorStatus",
        "detail.code || ''",
        "detail.message || ''",
        "detail.gate_write_performed",
        "detail.write_performed",
    )

    for value in required:
        assert value in block


def test_admin_api_preserves_backend_error_payload_for_no_write_denial():
    app = Path(
        "frontend/app.js"
    ).read_text()

    assert "class ApiError extends Error" in app
    assert "this.payload = payload;" in app
    assert "const response = await fetch(" in app
    assert "payload = text ? JSON.parse(text)" in app
    assert "throw new ApiError(" in app

    # ApiError receives the parsed payload as
    # its third constructor argument.
    assert (
        "response.status,\n      payload,"
        in app
    )
