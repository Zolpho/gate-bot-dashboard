from __future__ import annotations

import re
from pathlib import Path


APP_JS = Path("frontend/app.js")


def javascript_function(name: str) -> str:
    text = APP_JS.read_text()

    marker = f"function {name}("

    start = text.find(marker)

    if start < 0:
        raise AssertionError(
            f"JavaScript function not found: {name}"
        )

    remainder = text[start + len(marker):]

    match = re.search(
        r"\n(?:async\s+)?function\s+[A-Za-z0-9_]+\(",
        remainder,
    )

    if match is None:
        return text[start:]

    end = (
        start
        + len(marker)
        + match.start()
    )

    return text[start:end]


def test_blocked_external_execution_omits_money_moving_controls():
    source = javascript_function(
        "renderTreasuryWithdrawalExternalExecutionPreview"
    )

    assert "const executionControls = (" in source

    assert (
        "barriersOpen\n"
        "      ? ("
        in source
    )

    assert (
        "      : ''\n"
        "  );"
        in source
    )

    assert (
        'id="treasuryExternalWithdrawalConfirmation"'
        in source
    )

    assert (
        'id="executeTreasuryExternalWithdrawal"'
        in source
    )

    assert (
        "if (!barriersOpen) {\n"
        "    return;\n"
        "  }"
        in source
    )


def test_external_execution_blocker_distinguishes_arm_and_owner_policy():
    source = javascript_function(
        "renderTreasuryWithdrawalExternalExecutionPreview"
    )

    assert (
        "const liveWithdrawalsArmed = Boolean("
        in source
    )

    assert (
        "preview.live_withdrawals_armed"
        in source
    )

    assert (
        "const ownerLiveEnabled = Boolean("
        in source
    )

    assert (
        "preview.owner_account_live_enabled"
        in source
    )

    assert (
        "!liveWithdrawalsArmed\n"
        "          && !ownerLiveEnabled"
        in source
    )

    assert (
        "is not allowlisted for live withdrawals."
        in source
    )

    assert (
        "is not allowlisted for live "
        in source
    )

    assert (
        "external withdrawals."
        in source
    )


def test_external_execution_action_still_requires_server_barriers():
    source = javascript_function(
        "executeCurrentTreasuryExternalWithdrawal"
    )

    assert (
        "!== 'jit_ready'"
        in source
    )

    assert (
        "|| !preview.application_barriers_open"
        in source
    )

    assert (
        "}/execute`"
        in source
    )

    barrier_index = source.index(
        "|| !preview.application_barriers_open"
    )

    post_index = source.index(
        "}/execute`"
    )

    assert barrier_index < post_index


def test_blocked_renderer_returns_before_control_event_binding():
    source = javascript_function(
        "renderTreasuryWithdrawalExternalExecutionPreview"
    )

    blocked_return = source.index(
        "if (!barriersOpen) {"
    )

    input_lookup = source.index(
        "const input = $("
    )

    listener = source.index(
        "input?.addEventListener("
    )

    assert blocked_return < input_lookup
    assert blocked_return < listener
