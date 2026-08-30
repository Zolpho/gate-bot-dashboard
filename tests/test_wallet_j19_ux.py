from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT / "frontend/index.html"
).read_text()

APP = (
    ROOT / "frontend/app.js"
).read_text()

DEPOSIT = (
    ROOT / "frontend/deposit.css"
).read_text()

TREASURY = (
    ROOT / "frontend/treasury.css"
).read_text()


def function(name: str) -> str:
    marker = f"function {name}("

    start = APP.index(marker)

    match = re.search(
        r"\nfunction\s+[A-Za-z0-9_$]+\s*\(",
        APP[start + len(marker):],
    )

    if match is None:
        return APP[start:]

    end = (
        start
        + len(marker)
        + match.start()
    )

    return APP[start:end]


def test_wallet_hides_unrelated_global_account_selector():
    block = function("switchTab")

    assert "const globalAccountVisible" in block

    visibility = block[
        block.index(
            "const globalAccountVisible"
        ):
        block.index(
            "globalAccountSelector?.classList.toggle"
        )
    ]

    for page in (
        "'wallet'",
        "'trading'",
        "'bot-control'",
    ):
        assert page in visibility

    assert ".includes(target)" in visibility


def test_wallet_account_context_remains_the_scope_surface():
    assert (
        'id="walletAccountContext"'
        in HTML
    )

    block = function(
        "renderWalletAccountContext"
    )

    assert (
        "privateBalanceTargetAccount()"
        in block
    )

    assert (
        "Wallet account ·"
        in block
    )


def test_deposit_inline_step_uses_full_width_column():
    assert (
        "/* Wallet Deposit structural correction J19 */"
        in DEPOSIT
    )

    assert re.search(
        r"\.wallet-deposit-workflow"
        r"\s+\.deposit-step\s*\{"
        r"[^}]*grid-template-columns:\s*"
        r"minmax\(0,\s*1fr\)",
        DEPOSIT,
        re.S,
    )


def test_deposit_progressively_hides_unavailable_steps():
    assert re.search(
        r"\.wallet-deposit-workflow"
        r"\s+\.deposit-step"
        r"\.deposit-step-disabled\s*\{"
        r"[^}]*display:\s*none",
        DEPOSIT,
        re.S,
    )

    assert (
        "$('#depositNetworkStep')"
        in APP
    )

    assert (
        "$('#depositDetailsStep')"
        in APP
    )


def test_deposit_inline_container_has_no_modal_height_cap():
    assert re.search(
        r"\.wallet-deposit-workflow\s*\{"
        r"[^}]*max-height:\s*none"
        r"[^}]*overflow:\s*visible",
        DEPOSIT,
        re.S,
    )


def test_original_transfer_reset_still_exists():
    assert (
        HTML.count(
            'id="treasuryUserTransferResetButton"'
        )
        == 1
    )

    block = function(
        "bindTreasuryUserTransferEvents"
    )

    assert (
        "'#treasuryUserTransferResetButton'"
        in block
    )

    assert (
        "resetTreasuryUserTransferForm"
        in block
    )


def test_review_state_has_visible_transfer_reset():
    assert (
        HTML.count(
            'id="treasuryUserTransferReviewResetButton"'
        )
        == 1
    )

    confirmation = HTML[
        HTML.index(
            'id="treasuryUserTransferConfirmationBlock"'
        ):
        HTML.index(
            'id="executeTreasuryUserTransfer"'
        )
        + len(
            'id="executeTreasuryUserTransfer"'
        )
    ]

    assert (
        'id="treasuryUserTransferReviewResetButton"'
        in confirmation
    )


def test_review_reset_reuses_existing_guarded_reset_function():
    block = function(
        "bindTreasuryUserTransferEvents"
    )

    assert (
        "'#treasuryUserTransferReviewResetButton'"
        in block
    )

    assert re.search(
        r"reviewReset\.addEventListener\("
        r"\s*'click',"
        r"\s*resetTreasuryUserTransferForm",
        block,
        re.S,
    )

    reset_block = function(
        "resetTreasuryUserTransferForm"
    )

    assert (
        "state.treasuryUserTransferExecutionAttempted"
        in reset_block
    )

    assert (
        "snapshot?.executionResult"
        in reset_block
    )


def test_review_reset_participates_in_form_lock():
    block = function(
        "setTreasuryUserTransferFormLocked"
    )

    assert (
        "'#treasuryUserTransferReviewResetButton'"
        in block
    )


def test_j19_does_not_change_withdrawal_api_contract():
    for endpoint in (
        "/api/treasury/withdrawals/preflight/",
        "/api/treasury/withdrawals/requests",
    ):
        assert endpoint in APP


def test_j19_cache_key_is_bumped_for_wallet_assets():
    for asset in (
        "app.js",
        "wallet-tab.css",
        "deposit.css",
        "treasury.css",
    ):
        assert (
            f"./{asset}?v=20260830-wallet-ux-j19-v2"
            in HTML
        )
