from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT / "frontend" / "index.html"
).read_text()

APP = (
    ROOT / "frontend" / "app.js"
).read_text()

CSS = (
    ROOT / "frontend" / "wallet-tab.css"
).read_text()


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(name):
    matches = list(
        FUNCTION_PATTERN.finditer(APP)
    )

    found = []

    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(APP)
        )

        found.append(
            APP[
                match.start():
                end
            ]
        )

    assert len(found) == 1

    return found[0]


def workspace_slice(
    current_id,
    next_id,
):
    start = HTML.index(
        f'id="{current_id}"'
    )

    end = HTML.index(
        f'id="{next_id}"',
        start,
    )

    return HTML[
        start:end
    ]


def test_wallet_menu_order():
    positions = [
        HTML.index(
            f'data-wallet-view="{view}"'
        )
        for view in (
            "balance",
            "deposits",
            "transfers",
            "withdrawals",
        )
    ]

    assert positions == sorted(
        positions
    )


def test_wallet_menu_labels_are_concise():
    for label in (
        "Balance",
        "Deposits",
        "Transfers",
        "Withdrawals",
    ):
        assert (
            f">\n            {label}\n"
            in HTML
        )


def test_balance_is_initial_markup_selection():
    assert (
        'data-wallet-view="balance"'
        in HTML
    )

    balance_button_start = HTML.index(
        'id="walletBalanceTab"'
    )

    balance_button_end = HTML.index(
        "</button>",
        balance_button_start,
    )

    button = HTML[
        balance_button_start:
        balance_button_end
    ]

    assert (
        'aria-selected="true"'
        in button
    )


def test_balance_owns_balance_and_ownership_records():
    balance = workspace_slice(
        "walletBalanceWorkspace",
        "walletDepositsWorkspace",
    )

    assert (
        'id="privateBalancePanel"'
        in balance
    )

    assert (
        'id="refreshPrivateBalance"'
        in balance
    )

    assert (
        'id="walletBalanceRecords"'
        in balance
    )

    assert (
        'id="treasuryOwnershipBalanceBody"'
        in balance
    )

    assert (
        'id="treasuryOwnershipLedgerBody"'
        in balance
    )

    assert (
        'id="depositButton"'
        not in balance
    )

    assert (
        'id="depositHistorySection"'
        not in balance
    )


def test_deposits_owns_new_deposit_and_history():
    deposits = workspace_slice(
        "walletDepositsWorkspace",
        "treasuryPanel",
    )

    assert (
        'id="depositButton"'
        in deposits
    )

    assert (
        "New deposit"
        in deposits
    )

    assert (
        'id="depositHistorySection"'
        in deposits
    )

    assert (
        'id="walletDepositRecords"'
        in deposits
    )


def test_deposit_button_remains_globally_unique():
    assert HTML.count(
        'id="depositButton"'
    ) == 1


def test_transfer_and_withdrawal_workspaces_are_separate():
    withdrawals_start = HTML.index(
        'id="walletWithdrawalsWorkspace"'
    )

    transfers_start = HTML.index(
        'id="walletTransfersWorkspace"'
    )

    assert (
        withdrawals_start
        < transfers_start
    )

    withdrawals = HTML[
        withdrawals_start:
        transfers_start
    ]

    transfers = HTML[
        transfers_start:
        HTML.index(
            "</article>",
            transfers_start,
        )
    ]

    assert (
        'id="treasuryWithdrawalAction"'
        in withdrawals
    )

    assert (
        'id="treasuryWithdrawalRequestBody"'
        in withdrawals
    )

    assert (
        'id="treasuryUserTransferForm"'
        not in withdrawals
    )

    assert (
        'id="treasuryUserTransferForm"'
        in transfers
    )

    assert (
        'id="treasuryLockList"'
        in transfers
    )

    assert (
        'id="treasuryActivityBody"'
        in transfers
    )


def test_operational_ids_remain_unique():
    for element_id in (
        "privateBalancePanel",
        "refreshPrivateBalance",
        "depositButton",
        "depositHistorySection",
        "refreshDepositHistory",
        "syncDepositHistory",
        "treasuryPanel",
        "refreshTreasury",
        "treasuryError",
        "treasuryConfigurationWarning",
        "treasuryWithdrawalAction",
        "treasuryWithdrawalForm",
        "treasuryUserTransferForm",
        "treasuryRecords",
        "treasuryWithdrawalRequestBody",
        "treasuryOwnershipBalanceBody",
        "treasuryOwnershipLedgerBody",
        "treasuryLockList",
        "treasuryActivityBody",
    ):
        assert HTML.count(
            f'id="{element_id}"'
        ) == 1


def test_wallet_state_defaults_to_balance():
    assert (
        "walletView: 'balance',"
        in APP
    )


def test_wallet_view_is_allowlisted():
    block = function(
        "normalizeWalletView"
    )

    assert (
        "WALLET_VIEWS.has(candidate)"
        in block
    )

    assert (
        ": 'balance'"
        in block
    )


def test_render_wallet_view_preserves_mounted_nodes():
    block = function(
        "renderWalletView"
    )

    assert (
        "$$('[data-wallet-workspace]').forEach"
        in block
    )

    assert (
        "workspace.hidden = !active;"
        in block
    )

    assert (
        "treasuryPanel.hidden = !treasuryVisible;"
        in block
    )

    assert (
        ".remove()"
        not in block
    )


def test_switching_wallet_subsections_resets_page_top():
    block = function(
        "switchWalletView"
    )

    assert (
        "state.walletView !== target"
        in block
    )

    assert (
        "state.activeTab === 'wallet'"
        in block
    )

    assert (
        "resetPageScroll();"
        in block
    )

    assert (
        "window.scrollTo("
        not in block
    )


def test_wallet_data_loading_is_contextual():
    block = function(
        "loadWalletViewData"
    )

    assert (
        "target === 'balance'"
        in block
    )

    assert (
        "loadPrivateBalance("
        in block
    )

    assert (
        "loadTreasuryOverview("
        in block
    )

    assert (
        "target === 'deposits'"
        in block
    )

    assert (
        "loadDepositHistory("
        in block
    )


def test_entering_wallet_from_another_main_tab_lands_on_balance():
    block = function(
        "switchTab"
    )

    assert (
        "const walletView = ("
        in block
    )

    assert (
        "tabChanged"
        in block
    )

    assert (
        "? 'balance'"
        in block
    )

    assert (
        "state.walletView"
        in block
    )

    assert (
        "switchWalletView("
        in block
    )

    assert (
        "resetScroll: false"
        in block
    )


def test_wallet_subnav_buttons_use_central_switcher():
    block = function(
        "bindEvents"
    )

    assert (
        "$$('[data-wallet-view]').forEach"
        in block
    )

    assert (
        "button.dataset.walletView"
        in block
    )

    assert (
        "switchWalletView("
        in block
    )


def test_global_scroll_primitive_remains_single():
    assert APP.count(
        "window.scrollTo("
    ) == 1


def test_wallet_subnav_has_sticky_desktop_layout():
    for token in (
        "/* Wallet contextual sub-navigation v1 */",
        "#tab-wallet .wallet-subnav",
        "position: sticky;",
        "grid-template-columns: repeat(4, minmax(0, 1fr));",
        "#tab-wallet .wallet-subnav-button.active",
        "#tab-wallet .wallet-workspace[hidden]",
        "#tab-wallet #treasuryPanel[hidden]",
    ):
        assert token in CSS


def test_wallet_subnav_has_horizontal_mobile_layout():
    assert (
        "@media (max-width: 720px)"
        in CSS
    )

    assert (
        "overflow-x: auto;"
        in CSS
    )

    assert (
        "min-width: 118px;"
        in CSS
    )


def test_wallet_subnav_respects_reduced_motion():
    assert (
        "@media (prefers-reduced-motion: reduce)"
        in CSS
    )

    assert (
        "transition: none;"
        in CSS
    )
