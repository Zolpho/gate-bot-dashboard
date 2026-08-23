from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT / "frontend" / "index.html"
).read_text(encoding="utf-8")

APP = (
    ROOT / "frontend" / "app.js"
).read_text(encoding="utf-8")

CSS = (
    ROOT / "frontend" / "treasury.css"
).read_text(encoding="utf-8")


def test_treasury_assets_are_versioned():
    assert (
        "./treasury.css?"
        "v=20260823-withdraw-polish-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260823-withdraw-polish-v1"
        in HTML
    )


def test_treasury_four_status_cards_are_removed():
    assert (
        'class="treasury-safety-grid"'
        not in HTML
    )

    assert (
        'class="treasury-safety-card"'
        not in HTML
    )

    assert 'id="treasuryConfigured"' not in HTML
    assert 'id="treasuryPhase"' not in HTML
    assert 'id="treasuryTransferState"' not in HTML


def test_treasury_capabilities_are_shown_where_used():
    assert (
        'id="treasurySafetyBadge"'
        not in HTML
    )

    assert (
        'id="treasuryUserTransferState"'
        in HTML
    )

    assert (
        'id="treasuryWithdrawalState"'
        in HTML
    )

    assert (
        "treasury-capability-badge"
        in HTML
    )


def test_treasury_capability_colors_are_semantic():
    assert (
        ".treasury-capability-badge.enabled"
        in CSS
    )

    assert (
        ".treasury-capability-badge.disabled"
        in CSS
    )

    assert "color: var(--positive);" in CSS
    assert "color: var(--warning);" in CSS

    assert (
        "setTreasuryCapabilityBadge("
        in APP
    )


def test_treasury_status_copy_is_explicit():
    for token in (
        "USER TRANSFERS ENABLED",
        "USER TRANSFERS DISABLED",
        "WITHDRAWAL ARM ENABLED",
        "WITHDRAWAL ARM DISABLED",
    ):
        assert token in APP

    assert (
        "TREASURY TRANSFER ARM ENABLED"
        not in APP
    )

    assert (
        "TREASURY TRANSFER ARM DISABLED"
        not in APP
    )

    assert "LIVE TRANSFERS DISABLED" not in APP
    assert "LIVE TRANSFERS ENABLED" not in APP


def test_configuration_only_surfaces_when_unavailable():
    assert (
        'id="treasuryConfigurationWarning"'
        in HTML
    )

    assert (
        "Treasury configuration is unavailable."
        in APP
    )

    assert (
        "configurationKnown"
        in APP
    )

    assert "T2B_TRANSFER_CONTROL" not in HTML


def test_treasury_has_compact_action_workspace():
    assert (
        'class="treasury-actions-grid"'
        in HTML
    )

    assert (
        'id="treasuryWithdrawalAction"'
        in HTML
    )

    assert (
        'id="treasuryWithdrawalUnavailable"'
        in HTML
    )

    assert (
        "/* 3J18 Treasury compact workspace v1 */"
        in CSS
    )


def test_withdrawal_without_destinations_is_compacted():
    start = APP.index(
        "function renderTreasuryWithdrawalDestinations()"
    )

    end = APP.index(
        "\nfunction renderTreasuryWithdrawalDestinationSummary()",
        start,
    )

    renderer = APP[start:end]

    for token in (
        "'has-no-destinations'",
        "treasuryWithdrawalUnavailable",
        "amount.disabled = !rows.length",
        "preflightButton.disabled = !rows.length",
    ):
        assert token in renderer


def test_treasury_records_are_collapsible():
    assert (
        'class="treasury-records"'
        in HTML
    )

    assert 'id="treasuryRecords"' in HTML

    assert "Records &amp; audit" in HTML

    assert (
        ".treasury-records-summary"
        in CSS
    )


def test_lock_badge_is_hidden_when_zero():
    assert (
        'id="treasuryLockCount"'
        in HTML
    )

    assert (
        "treasury-lock-count hidden"
        in HTML
    )

    assert (
        "lockCount === 0"
        in APP
    )

    assert (
        "'attention'"
        in APP
    )


def test_active_locks_force_records_visible():
    start = APP.index(
        "function renderTreasuryLocks()"
    )

    end = APP.index(
        "\nfunction renderTreasuryTransfers()",
        start,
    )

    renderer = APP[start:end]

    assert (
        "const records = $('#treasuryRecords');"
        in renderer
    )

    assert (
        "if (rows.length && records)"
        in renderer
    )

    assert "records.open = true;" in renderer


def test_existing_treasury_action_ids_are_preserved():
    for element_id in (
        "treasuryUserTransferForm",
        "treasuryUserTransferResetButton",
        "treasuryUserTransferPreviewButton",
        "executeTreasuryUserTransfer",
        "treasuryWithdrawalForm",
        "treasuryWithdrawalPreflightButton",
        "createTreasuryWithdrawalRequest",
        "treasuryWithdrawalRequestBody",
        "treasuryOwnershipBalanceBody",
        "treasuryOwnershipLedgerBody",
        "treasuryLockList",
        "treasuryActivityBody",
    ):
        assert (
            HTML.count(
                f'id="{element_id}"'
            )
            == 1
        )


def test_treasury_backend_semantics_remain_separate():
    assert (
        "health.treasury_withdrawals_enabled"
        in APP
    )

    assert (
        "state.treasuryUserTransfersEnabled"
        in APP
    )

def test_user_transfer_source_is_static_and_account_scoped():
    assert (
        'id="treasuryUserTransferSourceDisplay"'
        in HTML
    )

    assert (
        'id="treasuryUserTransferSource"'
        in HTML
    )

    source_id = HTML.index(
        'id="treasuryUserTransferSource"'
    )

    assert "<select" not in HTML[
        max(0, source_id - 120):source_id
    ]

    assert 'type="hidden"' in HTML[
        max(0, source_id - 160):source_id + 160
    ]

    assert (
        "function treasuryScopedUserTransferSource("
        in APP
    )

    assert "sourceIds.length === 1" in APP

    assert (
        "sourceIds.includes(state.selectedAccount)"
        in APP
    )

    assert "sourceIds[0] || ''" not in APP


def test_user_transfer_asset_option_omits_available_word():
    start = APP.index(
        "function renderTreasuryUserTransferParticipants()"
    )

    end = APP.index(
        "\nfunction treasuryUserTransferPathLabel(",
        start,
    )

    renderer = APP[start:end]

    assert "fmtAssetQuantity(item.available)" in renderer

    assert "} available" not in renderer


def test_user_transfer_empty_review_does_not_render_large_box():
    assert (
        'class="treasury-user-transfer-preview hidden"'
        in HTML
    )

    start = APP.index(
        "function renderTreasuryUserTransferPreview()"
    )

    end = APP.index(
        "\nfunction clearTreasuryUserTransferPreview()",
        start,
    )

    renderer = APP[start:end]

    assert (
        "Select a registered recipient and run a review."
        not in renderer
    )

    assert "container.classList.add('hidden')" in renderer
    assert "container.classList.remove('hidden')" in renderer


def test_user_transfer_review_has_six_user_facing_facts_only():
    start = APP.index(
        "function renderTreasuryUserTransferPreview()"
    )

    end = APP.index(
        "\nfunction clearTreasuryUserTransferPreview()",
        start,
    )

    renderer = APP[start:end]

    for label in (
        "<span>From</span>",
        "<span>To</span>",
        "<span>Asset</span>",
        "<span>Amount</span>",
        "<span>Balance before</span>",
        "<span>Balance after</span>",
    ):
        assert label in renderer

    for removed in (
        "Gate transfer path",
        "<span>Gate write</span>",
        "<span>Operation blockers</span>",
        "<span>Execution</span>",
        "Live transfer arm",
    ):
        assert removed not in renderer

    assert (
        renderer.count(
            'class="treasury-user-transfer-card"'
        )
        == 6
    )


def test_user_transfer_review_uses_compact_helpers():
    start = APP.index(
        "function renderTreasuryUserTransferPreview()"
    )

    end = APP.index(
        "\nfunction clearTreasuryUserTransferPreview()",
        start,
    )

    renderer = APP[start:end]

    assert "USER TRANSFERS ENABLED" not in renderer
    assert "USER TRANSFERS DISABLED" not in renderer
    assert "NO BLOCKERS" in renderer

    assert (
        "Gate action happens only after final confirmation."
        in renderer
    )

    assert (
        ".treasury-user-transfer-helper.success"
        in CSS
    )

    assert (
        ".treasury-user-transfer-helper.warning"
        in CSS
    )


def test_transfer_review_balances_use_compact_quantity_formatting():
    start = APP.index(
        "function renderTreasuryUserTransferPreview()"
    )

    end = APP.index(
        "\nfunction clearTreasuryUserTransferPreview()",
        start,
    )

    renderer = APP[start:end]

    assert (
        "fmtAssetQuantity("
        in renderer
    )

    assert "Balance before" in renderer
    assert "Balance after" in renderer


def test_periodic_core_refresh_does_not_reload_wallet_data():
    start = APP.index(
        "async function loadCore()"
    )

    end = APP.index(
        "\nasync function syncNow()",
        start,
    )

    load_core = APP[start:end]

    assert "loadPrivateBalance(" not in load_core
    assert "loadDepositHistory(" not in load_core

    assert "setInterval(loadCore, 60000);" in APP


def test_wallet_activation_still_performs_initial_private_load():
    start = APP.index(
        "function switchTab("
    )

    end = APP.index(
        "\nfunction setMetric(",
        start,
    )

    switch_tab = APP[start:end]

    assert "target === 'wallet'" in switch_tab
    assert "loadPrivateBalance({ quiet: true })" in switch_tab
    assert "loadDepositHistory({ quiet: true })" in switch_tab
    assert "loadTreasuryOverview({ quiet: true })" in switch_tab


def test_successful_user_transfer_refreshes_balance_once_explicitly():
    start = APP.index(
        "async function executeTreasuryUserTransfer()"
    )

    end = APP.index(
        "\nfunction invalidateTreasuryUserTransferPreview()",
        start,
    )

    executor = APP[start:end]

    assert "loadPrivateBalance({" in executor
    assert "force: true" in executor
    assert (
        "A balance-refresh failure must not change its outcome."
        in executor
    )


def test_zero_destination_withdrawal_hides_form():
    assert (
        "#treasuryWithdrawalAction.has-no-destinations"
        in CSS
    )

    assert (
        ".treasury-withdrawal-form"
        in CSS
    )

    assert "display: none;" in CSS

def test_generic_treasury_arm_is_removed_from_wallet():
    assert 'id="treasurySafetyBadge"' not in HTML

    assert (
        "TREASURY TRANSFER ARM ENABLED"
        not in APP
    )

    assert (
        "TREASURY TRANSFER ARM DISABLED"
        not in APP
    )


def test_user_transfer_asset_does_not_repeat_currency():
    start = APP.index(
        "function renderTreasuryUserTransferParticipants()"
    )

    end = APP.index(
        "\nfunction treasuryUserTransferPathLabel(",
        start,
    )

    renderer = APP[start:end]

    amount_start = renderer.index(
        "const displayAmount"
    )

    amount_end = renderer.index(
        "return (",
        amount_start,
    )

    amount_block = renderer[
        amount_start:amount_end
    ]

    assert "fmtAssetQuantity(item.available)" in amount_block
    assert "+ currency" not in amount_block


def test_user_transfer_reset_exists_and_is_bound():
    assert (
        'id="treasuryUserTransferResetButton"'
        in HTML
    )

    assert (
        "function resetTreasuryUserTransferForm()"
        in APP
    )

    binder_start = APP.index(
        "function bindTreasuryUserTransferEvents()"
    )

    binder = APP[binder_start:]

    assert (
        "'#treasuryUserTransferResetButton'"
        in binder
    )

    assert (
        "resetTreasuryUserTransferForm"
        in binder
    )


def test_reset_preserves_execution_immutability():
    start = APP.index(
        "function resetTreasuryUserTransferForm()"
    )

    end = APP.index(
        "\n\nasync function startNewTreasuryUserTransfer()",
        start,
    )

    resetter = APP[start:end]

    assert (
        "state.treasuryUserTransferExecutionAttempted"
        in resetter
    )

    assert "snapshot?.executionResult" in resetter

    assert (
        "clearTreasuryUserTransferPreview();"
        in resetter
    )

    assert (
        "renderTreasuryUserTransferParticipants();"
        in resetter
    )


def test_reset_is_locked_with_transfer_form():
    start = APP.index(
        "function setTreasuryUserTransferFormLocked("
    )

    end = APP.index(
        "\n\nfunction treasuryScopedUserTransferSource(",
        start,
    )

    locker = APP[start:end]

    assert (
        "'#treasuryUserTransferResetButton'"
        in locker
    )


def test_final_confirmation_is_compact():
    assert "Final confirmation" in HTML

    assert (
        "treasury-user-transfer-confirmation-head"
        in HTML
    )

    assert (
        "treasury-user-transfer-confirmation-row"
        in HTML
    )

    assert (
        ".treasury-user-transfer-confirmation-row"
        in CSS
    )


def test_source_scope_is_in_transfer_header():
    source_display = HTML.index(
        'id="treasuryUserTransferSourceDisplay"'
    )

    form = HTML.index(
        'id="treasuryUserTransferForm"'
    )

    assert source_display < form

    assert (
        "treasury-user-transfer-scope"
        in HTML
    )

    assert (
        "treasury-user-transfer-static-field"
        not in HTML
    )

    assert (
        ".treasury-user-transfer-scope"
        in CSS
    )


def test_review_capability_is_not_duplicated():
    start = APP.index(
        "function renderTreasuryUserTransferPreview()"
    )

    end = APP.index(
        "\nfunction clearTreasuryUserTransferPreview()",
        start,
    )

    renderer = APP[start:end]

    assert "NO BLOCKERS" in renderer

    assert (
        "USER TRANSFERS ENABLED"
        not in renderer
    )

    assert (
        "USER TRANSFERS DISABLED"
        not in renderer
    )

def test_transfer_form_has_three_editable_fields():
    form_start = HTML.index(
        'id="treasuryUserTransferForm"'
    )

    form_end = HTML.index(
        "</form>",
        form_start,
    )

    form = HTML[
        form_start:form_end
    ]

    assert "<span>From</span>" not in form

    assert (
        'id="treasuryUserTransferSource"'
        in form
    )

    assert 'type="hidden"' in form

    assert form.count("<label>") == 3

    for label in (
        "To",
        "Asset",
        "Amount",
    ):
        assert label in form


def test_confirmation_phrase_is_above_input_row():
    code = HTML.index(
        'id="treasuryUserTransferRequiredConfirmation"'
    )

    row = HTML.index(
        'class="treasury-user-transfer-confirmation-row"'
    )

    input_index = HTML.index(
        'id="treasuryUserTransferConfirmation"',
        code,
    )

    assert code < row < input_index


def test_final_confirmation_is_flat():
    marker = (
        "/* 3J18 Treasury final operational polish v1 */"
    )

    final_css = CSS[
        CSS.index(marker):
    ]

    start = final_css.index(
        ".treasury-user-transfer-confirmation {"
    )

    end = final_css.index(
        "}",
        start,
    )

    block = final_css[
        start:end
    ]

    assert "border: 0;" in block
    assert "border-top:" in block
    assert "background: transparent;" in block


def test_user_transfer_credential_footer_is_removed():
    assert (
        "Transfers use the isolated Treasury credential "
        "and are"
        not in HTML
    )


def test_confirmation_helper_copy_is_short():
    assert (
        "Type the exact phrase shown below."
        in HTML
    )

def test_logout_is_hard_treasury_session_boundary():
    start = APP.index(
        "function lockAdmin("
    )

    end = APP.index(
        "\n\nasync function unlockAdmin(",
        start,
    )

    block = APP[start:end]

    assert (
        "state.adminSessionEpoch += 1;"
        in block
    )

    assert "clearTreasurySession();" in block

    assert (
        block.index(
            "state.adminSessionEpoch += 1;"
        )
        < block.index(
            "state.adminAuthorization = '';"
        )
    )


def test_clear_treasury_session_removes_user_private_state():
    start = APP.index(
        "function clearTreasurySession()"
    )

    end = APP.index(
        "\n\nfunction lockAdmin(",
        start,
    )

    block = APP[start:end]

    required = (
        "state.treasuryTransfers = [];",
        "state.treasuryLocks = [];",
        "state.treasuryOwnershipBalances = [];",
        "state.treasuryOwnershipLedger = [];",
        "state.treasuryUserTransferParticipants = [];",
        "state.treasuryUserTransfersEnabled = false;",
        "state.treasuryUserTransferPreview = null;",
        (
            "state.treasuryUserTransferExecutionAttempted "
            "= false;"
        ),
        "state.treasuryWithdrawalDestinations = [];",
        "state.treasuryWithdrawalRequests = [];",
        "state.treasuryWithdrawalPreflight = null;",
        "state.treasuryWithdrawalRequestDetail = null;",
        "state.treasuryRequestDetail = null;",
    )

    for token in required:
        assert token in block

    assert (
        "renderTreasuryUserTransferPreview();"
        in block
    )

    assert (
        "renderTreasuryWithdrawalPreflight();"
        in block
    )


def test_new_login_clears_treasury_before_wallet_load():
    start = APP.index(
        "async function unlockAdmin("
    )

    end = APP.index(
        "\n\nasync function changeOwnPassword(",
        start,
    )

    block = APP[start:end]

    epoch = block.index(
        "state.adminSessionEpoch += 1;"
    )

    authorization = block.index(
        "state.adminAuthorization = authorization;"
    )

    user = block.index(
        "state.adminUser = result.user;"
    )

    clear = block.index(
        "clearTreasurySession();"
    )

    wallet = block.index(
        "switchTab('wallet');"
    )

    assert (
        epoch
        < authorization
        < user
        < clear
        < wallet
    )


def test_admin_api_rejects_old_login_response():
    start = APP.index(
        "function adminApi("
    )

    end = APP.index(
        "\n\nfunction staleAdminSessionError(",
        start,
    )

    block = APP[start:end]

    assert (
        "const sessionEpoch = state.adminSessionEpoch;"
        in block
    )

    assert (
        "const authorization = state.adminAuthorization;"
        in block
    )

    assert (
        "state.adminSessionEpoch !== sessionEpoch"
        in block
    )

    assert (
        "state.adminAuthorization !== authorization"
        in block
    )

    assert "stale_admin_session: true" in block

    # Old-session 401 must not call lockAdmin against
    # a different/new authenticated browser session.
    assert (
        "state.adminSessionEpoch === sessionEpoch"
        in block
    )

    assert (
        "state.adminAuthorization === authorization"
        in block
    )


def test_wallet_loaders_ignore_stale_admin_response():
    function_names = (
        "loadPrivateBalance",
        "loadDepositHistory",
        "loadTreasuryOverview",
    )

    for name in function_names:
        start = APP.index(
            f"async function {name}("
        )

        remainder = APP[start:]

        next_functions = [
            value
            for value in (
                remainder.find(
                    "\nfunction ",
                    1,
                ),
                remainder.find(
                    "\nasync function ",
                    1,
                ),
            )
            if value >= 0
        ]

        assert next_functions

        block = remainder[
            :min(next_functions)
        ]

        assert (
            "if (staleAdminSessionError(error))"
            in block
        )


def test_logged_out_treasury_uses_canonical_session_reset():
    start = APP.index(
        "async function loadTreasuryOverview("
    )

    end = APP.index(
        "\n\nasync function openTreasuryRequestDetail(",
        start,
    )

    block = APP[start:end]

    logged_out_start = block.index(
        "if (\n    !state.adminUser"
    )

    logged_out_end = block.index(
        "const button =",
        logged_out_start,
    )

    logged_out = block[
        logged_out_start:logged_out_end
    ]

    assert "clearTreasurySession();" in logged_out

    assert (
        "state.treasuryUserTransferPreview = null"
        not in logged_out
    )


def test_treasury_css_version_marks_withdraw_polish():
    assert (
        "./treasury.css?"
        "v=20260823-withdraw-polish-v1"
        in HTML
    )


def test_app_version_marks_withdraw_polish():
    assert (
        "./app.js?"
        "v=20260823-withdraw-polish-v1"
        in HTML
    )

def test_withdraw_approved_destination_flow_is_compact():
    withdraw_start = HTML.index(
        'id="treasuryWithdrawalAction"'
    )

    records_start = HTML.index(
        'id="treasuryRecords"',
        withdraw_start,
    )

    block = HTML[
        withdraw_start:records_start
    ]

    assert (
        'class="treasury-withdrawal-destination-field"'
        in block
    )

    assert (
        'class="treasury-withdrawal-execution-row"'
        in block
    )

    assert (
        block.index(
            'id="treasuryWithdrawalDestination"'
        )
        < block.index(
            'id="treasuryWithdrawalDestinationSummary"'
        )
        < block.index(
            'id="treasuryWithdrawalAmount"'
        )
        < block.index(
            'id="treasuryWithdrawalPreflight"'
        )
    )


def test_withdraw_preflight_is_hidden_until_run():
    assert (
        'id="treasuryWithdrawalPreflight"\n'
        '              class="treasury-withdrawal-preflight hidden"'
        in HTML
    )

    start = APP.index(
        "function renderTreasuryWithdrawalPreflight()"
    )

    end = APP.index(
        "\nfunction treasuryWithdrawalRequestStatusClass(",
        start,
    )

    block = APP[start:end]

    assert "element.innerHTML = '';" in block

    assert (
        "element.classList.add('hidden');"
        in block
    )

    assert (
        "element.classList.remove('hidden');"
        in block
    )

    assert (
        "Run a preflight to review Gate limits"
        not in block
    )


def test_withdraw_preparation_card_drops_repetitive_safety_footer():
    withdraw_start = HTML.index(
        'id="treasuryWithdrawalAction"'
    )

    records_start = HTML.index(
        'id="treasuryRecords"',
        withdraw_start,
    )

    block = HTML[
        withdraw_start:records_start
    ]

    assert (
        "treasury-withdrawal-safety-note"
        not in block
    )

    assert (
        "The browser never supplies the withdrawal address"
        not in block
    )


def test_withdraw_polish_does_not_touch_records_boundary():
    withdraw_start = HTML.index(
        'id="treasuryWithdrawalAction"'
    )

    records_start = HTML.index(
        'id="treasuryRecords"',
        withdraw_start,
    )

    assert withdraw_start < records_start

    assert (
        "Records &amp; audit"
        in HTML[records_start:]
    )


def test_withdraw_polish_css_marks_compact_operational_flow():
    assert (
        "/* 3J19 Withdraw approved-destination polish v1 */"
        in CSS
    )

    for token in (
        ".treasury-withdrawal-execution-row",
        "repeat(5, minmax(0, 1fr))",
        "minmax(120px, .7fr)",
        ".treasury-withdrawal-preflight-grid",
    ):
        assert token in CSS


def test_withdraw_polish_preserves_operational_controls():
    for element_id in (
        "treasuryWithdrawalDestination",
        "treasuryWithdrawalAmount",
        "treasuryWithdrawalPreflightButton",
        "createTreasuryWithdrawalRequest",
    ):
        assert (
            HTML.count(
                f'id="{element_id}"'
            )
            == 1
        )
