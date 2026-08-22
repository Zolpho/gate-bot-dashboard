from pathlib import Path


TRADING_LIMIT = Path(
    "frontend/trading-limit.js"
)


def _text() -> str:
    return TRADING_LIMIT.read_text()


def _function(
    name: str,
) -> str:
    text = _text()

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


def test_recovery_checkpoint_accepts_amendment_kind():
    text = _text()

    assert "'amendment'," in text

    reader = _function(
        "tradingLimitRecoveryCheckpointRead"
    )

    writer = _function(
        "tradingLimitRecoveryCheckpointWrite"
    )

    assert "'amendment'," in reader
    assert "'amendment'," in writer


def test_amendment_checkpoint_persists_full_identity():
    writer = _function(
        "tradingLimitRecoveryCheckpointWrite"
    )

    required = (
        "amendRequestId = ''",
        "requestedPrice = ''",
        "normalizedAmendRequestId",
        "normalizedRequestedPrice",
        "amend_request_id:",
        "requested_price:",
        "gate_order_id:",
        "No amendment write was sent.",
    )

    for value in required:
        assert value in writer


def test_amendment_checkpoint_requires_exact_clear_identity():
    clear = _function(
        "tradingLimitRecoveryCheckpointClear"
    )

    assert "amendRequestId = ''" in clear
    assert "expectedAmendRequestId" in clear
    assert "current.kind || ''" in clear
    assert "=== 'amendment'" in clear
    assert "current.amend_request_id" in clear


def test_amendment_attempt_participates_in_global_recovery_lock():
    text = _text()

    assert (
        "limitOrderAmendmentAttempt = null"
        in text
    )

    recovery = _function(
        "tradingLimitExecutionRecoveryRequired"
    )

    assert "amendmentAttempt" in recovery
    assert "!amendmentAttempt.definitive" in recovery


def test_amendment_hydration_uses_exact_durable_identity():
    hydrate = _function(
        "tradingLimitRecoveryHydrateAmendment"
    )

    required = (
        "expectedAmendRequestId",
        "expectedOrderRequestId",
        "expectedGateOrderId",
        "expectedRequestedPrice",
        "result?.amendments",
        "result?.active_amendment",
        "amendment.order_request_id",
        "amendment.amend_request_id",
        "amendment.gate_order_id",
        "amendment.requested_price",
        "limitOrderAmendmentAttempt",
    )

    for value in required:
        assert value in hydrate


def test_amendment_definitive_state_requires_completed_audit():
    definitive = _function(
        "tradingLimitAmendmentDefinitive"
    )

    assert "completed_at" in definitive
    assert "normalizedStatus" in definitive

    hydrate = _function(
        "tradingLimitRecoveryHydrateAmendment"
    )

    assert (
        "tradingLimitAmendmentDefinitive("
        in hydrate
    )


def test_missing_amendment_audit_is_uncertain_not_retryable():
    missing = _function(
        "tradingLimitRecoveryHydrateMissingAudit"
    )

    assert (
        "if (kind === 'amendment')"
        in missing
    )

    hydrate = _function(
        "tradingLimitRecoveryHydrateAmendment"
    )

    assert "'client_uncertain'" in hydrate
    assert "Do not repeat the amendment" in hydrate
    assert "definitive" in hydrate


def test_checkpoint_recovery_dispatches_amendment_without_post():
    recover = _function(
        "recoverTradingLimitCheckpoint"
    )

    assert (
        "=== 'amendment'"
        in recover
    )

    assert (
        "tradingLimitRecoveryHydrateAmendment("
        in recover
    )

    assert (
        "amendRequestId:"
        in recover
    )

    assert (
        "checkpoint.amend_request_id"
        in recover
    )

    # Recovery itself remains exact authenticated GET.
    assert (
        "'/api/trading/limit-orders/requests/'"
        in recover
    )

    assert "method: 'POST'" not in recover


def test_3j6b0_adds_no_amendment_api_surface():
    core = Path(
        "frontend/trading.js"
    ).read_text()

    limit = _text()

    assert core.count(
        "method: 'POST'"
    ) == 1

    assert limit.count(
        "method: 'POST'"
    ) == 5

    for text in (
        core,
        limit,
    ):
        assert "/amend" not in text
        assert "/amendments/" not in text
        assert (
            "data-trading-amend-action"
            not in text
        )


def test_amendment_recovery_validates_source_gate_order_without_amend_audit():
    hydrate = _function(
        "tradingLimitRecoveryHydrateAmendment"
    )

    assert (
        "durableSourceGateOrderId"
        in hydrate
    )

    assert (
        "request?.gate_order_id"
        in hydrate
    )

    assert (
        "durableSourceGateOrderId"
        + "\n      !== expectedGateOrderId"
        in hydrate
    )

    assert (
        "identity does not match the source "
        in hydrate
    )
