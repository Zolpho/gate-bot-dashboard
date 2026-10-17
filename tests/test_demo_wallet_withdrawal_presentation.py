from __future__ import annotations

import re
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

APP = (
    ROOT
    / "frontend"
    / "app.js"
).read_text(
    encoding="utf-8"
)

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)


def _function_source(
    name: str,
) -> str:
    pattern = re.compile(
        rf"(?m)^(?:async\s+)?function\s+"
        rf"{re.escape(name)}\s*\("
    )

    match = pattern.search(
        APP
    )

    assert match, name

    next_match = re.compile(
        r"(?m)^(?:async\s+)?function\s+"
        r"[A-Za-z_$][A-Za-z0-9_$]*\s*\("
    ).search(
        APP,
        match.end(),
    )

    end = (
        next_match.start()
        if next_match
        else len(APP)
    )

    return APP[
        match.start():
        end
    ]


def test_demo_wallet_admits_withdrawals_and_keeps_banner():
    wallet = _function_source(
        "walletViewForSession"
    )

    presentation = _function_source(
        "renderDemoPresentation"
    )

    allowed = wallet.split(
        "].includes(",
        1,
    )[0]

    assert "'withdrawals'" in allowed

    assert (
        "withdrawalsButton.classList.remove"
        in presentation
    )

    assert (
        "Demo withdrawals"
        in presentation
    )

    assert (
        "DEMO MODE · simulated actions · no real funds"
        in presentation
    )


def test_demo_withdrawal_owner_flows_through_demo_wallet_account():
    owner = _function_source(
        "treasuryWithdrawalPreparationOwner"
    )

    balance_target = _function_source(
        "privateBalanceTargetAccount"
    )

    assert (
        "privateBalanceTargetAccount()"
        in owner
    )

    assert (
        "if (isDemoSession())"
        in balance_target
    )

    assert (
        "ensureDemoWalletAccount()"
        in balance_target
    )

    demo_branch = balance_target.split(
        "if (isDemoSession())",
        1,
    )[1].split(
        "if (",
        1,
    )[0]

    assert (
        "state.selectedAccount"
        not in demo_branch
    )


def test_demo_withdrawal_loader_uses_only_safe_list_contracts():
    block = _function_source(
        "loadDemoWithdrawalOverview"
    )

    required = (
        "/api/treasury/withdrawals/destinations",
        "/api/treasury/withdrawals/recipients",
        "/api/treasury/withdrawals/requests?limit=50",
    )

    for marker in required:
        assert marker in block

    forbidden = (
        "/api/health",
        "/reconcile",
        "/settle",
        "/approve",
        "/revoke",
        "/hold-on-main",
        "/cancel",
        "/abandon",
        "/api/treasury/transfers/",
    )

    for marker in forbidden:
        assert marker not in block


def test_demo_withdrawal_loader_is_wallet_scoped_and_contract_checked():
    block = _function_source(
        "loadDemoWithdrawalOverview"
    )

    assert (
        "treasuryWithdrawalPreparationOwner()"
        in block
    )

    assert (
        "assertDemoWithdrawalPayload"
        in block
    )

    assert (
        "item.owner_account_id"
        in block
    )

    assert (
        "=== owner"
        in block
    )


def test_demo_wallet_loader_never_routes_withdrawals_through_live_loader():
    block = _function_source(
        "loadWalletViewData"
    )

    demo_start = block.index(
        "isDemoSession()"
    )

    live_start = block.index(
        "if (target === 'balance')",
        demo_start,
    )

    demo = block[
        demo_start:
        live_start
    ]

    assert (
        "target === 'withdrawals'"
        in demo
    )

    assert (
        "loadPrivateBalance"
        in demo
    )

    assert (
        "loadDemoWithdrawalOverview"
        in demo
    )

    assert (
        "loadTreasuryOverview"
        not in demo
    )


def test_demo_withdrawal_contract_requires_no_gate_read_or_write():
    block = _function_source(
        "assertDemoWithdrawalPayload"
    )

    assert (
        "payload?.source !== 'demo'"
        in block
    )

    assert (
        "payload?.simulation !== true"
        in block
    )

    assert (
        "payload?.gate_read_performed !== false"
        in block
    )

    assert (
        "payload?.gate_write_performed !== false"
        in block
    )


def test_destination_review_and_production_recovery_fail_closed_in_demo():
    destinations = _function_source(
        "renderTreasuryWithdrawalDestinations"
    )

    assert (
        "!isDemoSession()"
        in destinations
    )

    guarded = (
        "loadTreasuryWithdrawalDestinationReview",
        "openTreasuryWithdrawalDestinationReview",
        "mutateTreasuryWithdrawalDestinationReview",
        "reconcileCurrentTreasuryWithdrawalJit",
        "reconcileCurrentTreasuryExternalWithdrawal",
        "settleCurrentTreasuryWithdrawal",
    )

    for name in guarded:
        block = _function_source(
            name
        )

        assert (
            "if (isDemoSession())"
            in block[:500]
        ), name



def test_f6e2b_demo_lifecycle_exposes_only_simulated_local_actions():
    controls = _function_source(
        "updateTreasuryWithdrawalLifecycleButtons"
    )

    runner = _function_source(
        "runDemoWithdrawalLifecycleAction"
    )

    assert (
        "demoWithdrawalNextAction"
        in controls
    )

    assert (
        "demoWithdrawalRequiredConfirmation"
        in controls
    )

    for action in (
        "'reserve'",
        "'confirm'",
        "'jit_prepare'",
        "'jit_execute'",
        "'execute'",
    ):
        assert action in runner

    for suffix in (
        "suffix: 'reserve'",
        "suffix: 'confirm'",
        "suffix: 'jit/prepare'",
        "suffix: 'jit/execute'",
        "suffix: 'execute'",
    ):
        assert suffix in runner

    for forbidden in (
        "/reconcile",
        "/settle",
        "/approve",
        "/revoke",
        "/hold-on-main",
        "/cancel",
        "/abandon",
    ):
        assert forbidden not in runner


def test_demo_preflight_normalizes_direct_adapter_contract():
    block = _function_source(
        "runTreasuryWithdrawalPreflight"
    )

    assert (
        "assertDemoWithdrawalPayload"
        in block
    )

    assert (
        "response.preflight"
        in block
    )

    assert (
        "|| response"
        in block
    )

    render = _function_source(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        "Simulation preflight passed"
        in render
    )

    assert (
        "No Gate request has been made."
        in render
    )


def test_demo_withdrawal_copy_and_cache_marker_are_additive():
    presentation = _function_source(
        "renderTreasuryWithdrawalPresentationCopy"
    )

    assert (
        "No Gate request"
        in presentation
    )

    assert (
        "Simulation"
        in presentation
    )

    assert (
        "Gate status"
        in presentation
    )

    assert (
        "m424f4=20261017-demo-wallet-read-ui-v1"
        in HTML
    )

    assert (
        "m424f5e=20261017-demo-ownership-transfers-ui-v1"
        in HTML
    )

    assert (
        "m424f6e2a=20261017-demo-withdrawal-workspace-v1"
        in HTML
    )


def test_demo_lifecycle_controls_use_backend_next_action_and_exact_confirmation():
    block = _function_source(
        "updateTreasuryWithdrawalLifecycleButtons"
    )

    assert (
        "demoWithdrawalNextAction"
        in block
    )

    assert (
        "demoWithdrawalRequiredConfirmation"
        in block
    )

    assert (
        "activeButton.disabled = !exact"
        in block
    )

    assert (
        "demoWithdrawalLifecycleButtonLabel"
        in block
    )


def test_demo_lifecycle_runner_requires_exact_confirmation():
    block = _function_source(
        "runDemoWithdrawalLifecycleAction"
    )

    assert (
        "confirmation !== required"
        in block
    )

    assert (
        "allowed.includes"
        in block
    )

    assert (
        "assertDemoWithdrawalMutationPayload"
        in block
    )


def test_demo_lifecycle_progression_is_fail_closed():
    block = _function_source(
        "runDemoWithdrawalLifecycleAction"
    )

    expected = (
        "expectedNext: 'confirm'",
        "expectedNext: 'jit_prepare'",
        "expectedNext: 'jit_execute'",
        "expectedNext: 'execute'",
    )

    for marker in expected:
        assert marker in block

    assert (
        "Safety invariant failed: unexpected "
        in block
    )

    assert (
        "Demo withdrawal lifecycle transition."
        in block
    )


def test_demo_execution_requires_terminal_settlement_and_zero_gate_write():
    mutation = _function_source(
        "assertDemoWithdrawalMutationPayload"
    )

    runner = _function_source(
        "runDemoWithdrawalLifecycleAction"
    )

    assert (
        "payload?.source !== 'demo'"
        in mutation
    )

    assert (
        "payload?.simulation !== true"
        in mutation
    )

    assert (
        "payload?.gate_write_performed !== false"
        in mutation
    )

    assert (
        "result?.status !== 'withdrawal_settled'"
        in runner
    )

    assert (
        "detail?.workflow?.terminal !== true"
        in runner
    )

    assert (
        "result?.local_write_performed !== true"
        in runner
    )

    assert (
        "result?.local_write_performed !== false"
        in runner
    )


def test_demo_execution_refreshes_wallet_balance_immediately():
    block = _function_source(
        "runDemoWithdrawalLifecycleAction"
    )

    execution = block.index(
        "if (action === 'execute')"
    )

    balance = block.index(
        "await loadPrivateBalance",
        execution,
    )

    detail = block.index(
        "await refreshTreasuryWithdrawalRequestDetail",
        execution,
    )

    assert (
        execution
        < balance
        < detail
    )


def test_terminal_demo_request_has_no_second_actionable_withdrawal():
    detail = _function_source(
        "renderTreasuryWithdrawalRequestDetail"
    )

    runner = _function_source(
        "runDemoWithdrawalLifecycleAction"
    )

    assert (
        "payload?.workflow?.terminal === true"
        in detail
    )

    assert (
        "Demo Wallet balance was"
        in detail
    )

    assert (
        "allowed.includes"
        in runner
    )

    assert (
        "demoWithdrawalNextAction("
        in runner
    )


def test_demo_does_not_use_live_jit_or_external_preview_controls():
    for name in (
        "renderTreasuryWithdrawalJitExecutionPreview",
        "renderTreasuryWithdrawalExternalExecutionPreview",
        "renderTreasuryWithdrawalSettlementPreview",
        "executeCurrentTreasuryWithdrawalJit",
        "executeCurrentTreasuryExternalWithdrawal",
    ):
        block = _function_source(
            name
        )

        assert (
            "if (isDemoSession())"
            in block[:700]
        ), name


def test_production_recovery_and_settlement_actions_remain_blocked_in_demo():
    for name in (
        "loadTreasuryWithdrawalDestinationReview",
        "openTreasuryWithdrawalDestinationReview",
        "mutateTreasuryWithdrawalDestinationReview",
        "reconcileCurrentTreasuryWithdrawalJit",
        "reconcileCurrentTreasuryExternalWithdrawal",
        "settleCurrentTreasuryWithdrawal",
    ):
        block = _function_source(
            name
        )

        assert (
            "if (isDemoSession())"
            in block[:700]
        ), name


def test_f6e2b_cache_marker_is_additive():
    assert (
        "m424f4=20261017-demo-wallet-read-ui-v1"
        in HTML
    )

    assert (
        "m424f5e=20261017-demo-ownership-transfers-ui-v1"
        in HTML
    )

    assert (
        "m424f6e2a=20261017-demo-withdrawal-workspace-v1"
        in HTML
    )

    assert (
        "m424f6e2b=20261017-demo-withdrawal-lifecycle-v1"
        in HTML
    )
