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


def test_demo_wallet_view_allows_transfers_but_not_withdrawals():
    block = _function_source(
        "walletViewForSession"
    )

    assert "'balance'" in block
    assert "'deposits'" in block
    assert "'transfers'" in block

    allowed_region = block.split(
        "].includes(",
        1,
    )[0]

    assert "'withdrawals'" not in allowed_region


def test_demo_presentation_exposes_transfer_and_ownership_but_hides_withdrawal():
    block = _function_source(
        "renderDemoPresentation"
    )

    assert (
        "transfersButton.classList.remove"
        in block
    )

    assert (
        "withdrawalsButton?.classList.toggle"
        in block
    )

    assert (
        "ownershipRecords.hidden = false"
        in block
    )

    assert (
        "state.walletView"
        in block
        and "!== 'transfers'"
        in block
    )

    assert (
        ".treasury-lock-section"
        in block
    )

    assert (
        "#treasuryDonationAttributionPanel"
        in block
    )

    assert (
        "Simulated Wallet-account transfers"
        in block
    )


def test_demo_transfer_source_uses_demo_wallet_scope_not_aggregate_scope():
    block = _function_source(
        "treasuryScopedUserTransferSource"
    )

    assert (
        "isDemoSession()"
        in block
    )

    assert (
        "ensureDemoWalletAccount()"
        in block
    )

    assert (
        "sourceIds.includes(state.selectedAccount)"
        in block
    )

    assert (
        "sourceIds.includes(demoWalletAccount)"
        in block
    )


def test_demo_loader_uses_only_f5d_reviewed_treasury_contracts():
    block = _function_source(
        "loadDemoTreasuryOverview"
    )

    allowed = (
        "/api/treasury/user-transfers/participants",
        "/api/treasury/transfers/requests?limit=50",
        "/api/treasury/ownership/balances",
        "/api/treasury/ownership/ledger?limit=200",
    )

    for path in allowed:
        assert path in block

    forbidden = (
        "/api/health",
        "/withdraw",
        "/reconcile",
        "/donation-attribution",
        "/transfers/locks",
        "/transfers/execute",
        "/transfers/simulate",
    )

    for marker in forbidden:
        assert marker not in block


def test_live_treasury_loader_exits_to_demo_loader_before_withdrawals():
    block = _function_source(
        "loadTreasuryOverview"
    )

    demo_branch = block.index(
        "if (isDemoSession())"
    )

    live_withdrawal = block.index(
        "const withdrawalRecipientOwner"
    )

    assert (
        demo_branch
        < live_withdrawal
    )

    assert (
        "await loadDemoTreasuryOverview"
        in block[
            demo_branch:
            live_withdrawal
        ]
    )


def test_demo_preview_requires_isolated_simulation_contract():
    block = _function_source(
        "runTreasuryUserTransferPreview"
    )

    assert (
        "response?.source !== 'demo'"
        in block
    )

    assert (
        "response?.simulation !== true"
        in block
    )

    assert (
        "response?.gate_write_required !== false"
        in block
    )

    assert (
        "response?.gate_write_performed !== false"
        in block
    )


def test_demo_execute_requires_zero_gate_write_while_live_guard_remains():
    block = _function_source(
        "executeTreasuryUserTransfer"
    )

    assert (
        "result?.source !== 'demo'"
        in block
    )

    assert (
        "result?.simulation !== true"
        in block
    )

    assert (
        "result?.gate_write_required !== false"
        in block
    )

    assert (
        "result?.gate_write_performed !== false"
        in block
    )

    assert (
        "!result.gate_write_performed"
        in block
    )

    assert (
        "!result.audit?.write_performed"
        in block
    )

    assert (
        "Simulation completed ✓"
        in block
    )


def test_demo_request_detail_never_exposes_reconcile_or_lock_release():
    detail = _function_source(
        "renderTreasuryRequestDetail"
    )

    reconcile = _function_source(
        "reconcileCurrentTreasuryRequest"
    )

    release = _function_source(
        "releaseCurrentTreasuryLock"
    )

    assert (
        "isDemoSession()"
        in detail
    )

    assert (
        "!isDemoSession()"
        in detail
    )

    assert (
        "if (isDemoSession())"
        in reconcile
    )

    assert (
        "if (isDemoSession())"
        in release
    )


def test_demo_donation_paths_fail_closed():
    option = _function_source(
        "renderTreasuryUserTransferDonationOption"
    )

    panel = _function_source(
        "renderTreasuryDonationAttributionPanel"
    )

    save = _function_source(
        "saveTreasuryDonationAttribution"
    )

    assert (
        "!isDemoSession()"
        in option
    )

    assert (
        "if (isDemoSession())"
        in panel
    )

    assert (
        "if (isDemoSession())"
        in save
    )


def test_demo_wallet_data_loading_exposes_ownership_and_transfers_safely():
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

    demo_block = block[
        demo_start:
        live_start
    ]

    assert (
        "target === 'deposits'"
        in demo_block
    )

    assert (
        "target === 'transfers'"
        in demo_block
    )

    assert (
        "loadPrivateBalance"
        in demo_block
    )

    assert (
        "loadDemoTreasuryOverview"
        in demo_block
    )

    assert (
        "loadTreasuryOverview"
        not in demo_block
    )


def test_demo_management_authority_remains_false():
    block = _function_source(
        "canManageAccount"
    )

    assert (
        "user.execution_mode === 'demo'"
        in block
    )

    demo_branch = block.split(
        "user.execution_mode === 'demo'",
        1,
    )[1]

    assert (
        "return false;"
        in demo_branch
    )


def test_f5e_cache_marker_is_additive():
    assert (
        "m424f4=20261017-demo-wallet-read-ui-v1"
        in HTML
    )

    assert (
        "m424f5e="
        "20261017-demo-ownership-transfers-ui-v1"
        in HTML
    )
