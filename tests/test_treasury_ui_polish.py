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
        "v=20260829-withdraw-destination-review-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260829-withdraw-destination-review-v1"
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
    load_core = _stage4_js_function_block("loadCore")

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
        "v=20260829-withdraw-destination-review-v1"
        in HTML
    )


def test_app_version_marks_withdraw_polish():
    assert (
        "./app.js?"
        "v=20260829-withdraw-destination-review-v1"
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

def _stage4_js_function_block(name: str) -> str:
    import re

    pattern = re.compile(
        rf"(?m)^(?:async\s+)?function\s+"
        rf"{re.escape(name)}\s*\("
    )

    match = pattern.search(APP)

    assert match is not None, name

    next_pattern = re.compile(
        r"(?m)^(?:async\s+)?function\s+"
        r"[A-Za-z_$][A-Za-z0-9_$]*\s*\("
    )

    next_match = next_pattern.search(
        APP,
        match.end(),
    )

    end = (
        next_match.start()
        if next_match is not None
        else len(APP)
    )

    return APP[
        match.start():end
    ]


def test_withdraw_asset_network_recipient_builder_precedes_legacy_destination():
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

    ids = (
        "treasuryWithdrawalAsset",
        "treasuryWithdrawalNetwork",
        "treasuryWithdrawalRecipient",
        "treasuryWithdrawalRecipientMemo",
        "prepareTreasuryWithdrawalDestination",
        "treasuryWithdrawalDestination",
        "treasuryWithdrawalAmount",
    )

    positions = {}

    for element_id in ids:
        token = (
            f'id="{element_id}"'
        )

        assert block.count(
            token
        ) == 1

        positions[
            element_id
        ] = block.index(
            token
        )

    assert (
        positions[
            "treasuryWithdrawalAsset"
        ]
        <
        positions[
            "treasuryWithdrawalNetwork"
        ]
        <
        positions[
            "treasuryWithdrawalRecipient"
        ]
        <
        positions[
            "treasuryWithdrawalRecipientMemo"
        ]
        <
        positions[
            "prepareTreasuryWithdrawalDestination"
        ]
        <
        positions[
            "treasuryWithdrawalDestination"
        ]
        <
        positions[
            "treasuryWithdrawalAmount"
        ]
    )


def test_withdraw_preparation_state_is_account_scoped_and_cleared():
    for token in (
        "treasuryWithdrawalRecipients: []",
        "treasuryWithdrawalCapabilities: null",
        "treasuryWithdrawalAsset: ''",
        "treasuryWithdrawalNetwork: ''",
        "treasuryWithdrawalRecipient: ''",
    ):
        assert token in APP

    block = _stage4_js_function_block(
        "clearTreasurySession"
    )

    for token in (
        "state.treasuryWithdrawalRecipients = [];",
        "state.treasuryWithdrawalCapabilities = null;",
        "state.treasuryWithdrawalAsset = '';",
        "state.treasuryWithdrawalNetwork = '';",
        "state.treasuryWithdrawalRecipient = '';",
    ):
        assert token in block


def test_withdraw_recipient_list_is_loaded_for_selected_owner_only():
    block = _stage4_js_function_block(
        "loadTreasuryOverview"
    )

    assert (
        "'/api/treasury/withdrawals/recipients'"
        in block
    )

    assert (
        "owner_account_id: withdrawalRecipientOwner"
        in block
    )

    assert (
        "status: 'active'"
        in block
    )

    assert (
        "privateBalanceTargetAccount()"
        in block
    )


def test_withdraw_capabilities_are_loaded_read_only_after_asset_selection():
    block = _stage4_js_function_block(
        "loadTreasuryWithdrawalCapabilities"
    )

    assert (
        "/api/treasury/withdrawals/capabilities/"
        in block
    )

    assert (
        "owner_account_id: owner"
        in block
    )

    assert (
        "if (response.gate_write_performed)"
        in block
    )

    asset_block = _stage4_js_function_block(
        "changeTreasuryWithdrawalAsset"
    )

    assert (
        "void loadTreasuryWithdrawalCapabilities();"
        in asset_block
    )


def test_withdraw_recipient_route_post_never_sends_address_or_owner():
    block = _stage4_js_function_block(
        "prepareTreasuryWithdrawalRecipientDestination"
    )

    assert (
        "/destinations"
        in block
    )

    assert (
        "method: 'POST'"
        in block
    )

    assert (
        "body: JSON.stringify({"
        in block
    )

    for token in (
        "currency,",
        "chain: String(",
        "memo,",
    ):
        assert token in block

    assert (
        "owner_account_id:"
        not in block
    )

    assert (
        "address:"
        not in block
    )

    assert (
        "if (result.gate_write_performed)"
        in block
    )

    assert (
        "must approve it before withdrawal"
        in block
    )


def test_wallet_account_switch_refreshes_all_account_scoped_wallet_state():
    block = _stage4_js_function_block(
        "changeSelectedAccount"
    )

    for token in (
        "clearPrivateBalance();",
        "clearDepositHistory();",
        "clearTreasurySession();",
        "await loadCore();",
        "state.activeTab === 'wallet'",
        "loadPrivateBalance({",
        "loadDepositHistory({",
        "loadTreasuryOverview({",
    ):
        assert token in block

    bind_block = _stage4_js_function_block(
        "bindEvents"
    )

    assert (
        "changeSelectedAccount,"
        in bind_block
    )


def test_withdraw_flow_css_marks_asset_network_recipient_preparation():
    assert (
        "/* 3J25 Withdraw asset/network/recipient preparation v1 */"
        in CSS
    )

    for token in (
        ".treasury-withdrawal-route-builder",
        ".treasury-withdrawal-route-grid",
        "#prepareTreasuryWithdrawalDestination",
        ".treasury-withdrawal-route-status.error",
        ".treasury-withdrawal-route-status.success",
    ):
        assert token in CSS

def test_withdraw_prepare_destination_uses_three_plus_two_layout():
    for token in (
        'class="treasury-withdrawal-route-asset"',
        'class="treasury-withdrawal-route-network"',
        'class="treasury-withdrawal-route-recipient"',
        'class="treasury-withdrawal-route-actions"',
    ):
        assert token in HTML

    marker = (
        "/* 3J25 Withdraw asset/network/recipient "
        "preparation v1 */"
    )

    block = CSS[
        CSS.index(marker):
    ]

    assert (
        "grid-template-columns:\n"
        "    minmax(120px, .8fr)\n"
        "    minmax(150px, 1fr)\n"
        "    minmax(220px, 1.45fr);"
        in block
    )

    assert (
        ".treasury-withdrawal-route-memo {\n"
        "  grid-column: 1 / 3;"
        in block
    )

    assert (
        ".treasury-withdrawal-route-actions {\n"
        "  grid-column: 3;"
        in block
    )


def test_withdraw_prepare_destination_has_scoped_reset_control():
    start = HTML.index(
        'id="treasuryWithdrawalAction"'
    )

    end = HTML.index(
        'id="treasuryRecords"',
        start,
    )

    block = HTML[
        start:end
    ]

    assert (
        block.count(
            'id="resetTreasuryWithdrawalRoute"'
        )
        == 1
    )

    assert (
        block.index(
            'id="resetTreasuryWithdrawalRoute"'
        )
        <
        block.index(
            'id="prepareTreasuryWithdrawalDestination"'
        )
    )

    reset = _stage4_js_function_block(
        "resetTreasuryWithdrawalRoutePreparation"
    )

    for token in (
        "state.treasuryWithdrawalCapabilities = null;",
        "state.treasuryWithdrawalCapabilitiesKey = '';",
        "state.treasuryWithdrawalCapabilitiesRequestKey = '';",
        "state.treasuryWithdrawalCapabilitiesLoading = false;",
        "state.treasuryWithdrawalAsset = '';",
        "state.treasuryWithdrawalNetwork = '';",
        "state.treasuryWithdrawalRecipient = '';",
        "state.treasuryWithdrawalRouteMessage = '';",
        "state.treasuryWithdrawalRouteMessageError = false;",
        "state.treasuryWithdrawalRoutePreparing = false;",
        "memo.value = '';",
        "renderTreasuryWithdrawalRoutePreparation();",
    ):
        assert token in reset

    for forbidden in (
        "treasuryWithdrawalDestinations",
        "treasuryWithdrawalRequests",
        "treasuryWithdrawalPreflight",
        "treasuryWithdrawalRequestDetail",
        "treasuryWithdrawalRequiredConfirmation",
        "treasuryWithdrawalAmount",
        "treasuryWithdrawalDestination",
        "adminApi(",
        "method:",
    ):
        assert forbidden not in reset


def test_withdraw_prepare_reset_is_bound_and_blocked_during_route_post():
    bind = _stage4_js_function_block(
        "bindEvents"
    )

    assert (
        "'#resetTreasuryWithdrawalRoute'"
        in bind
    )

    assert (
        "resetTreasuryWithdrawalRoutePreparation"
        in bind
    )

    reset = _stage4_js_function_block(
        "resetTreasuryWithdrawalRoutePreparation"
    )

    assert (
        "if (state.treasuryWithdrawalRoutePreparing)"
        in reset
    )

    render = _stage4_js_function_block(
        "renderTreasuryWithdrawalRoutePreparation"
    )

    assert (
        "'#resetTreasuryWithdrawalRoute'"
        in render
    )

    assert (
        "resetButton.disabled = Boolean("
        in render
    )


def test_withdraw_prepare_destination_resets_layout_responsively():
    marker = (
        "/* 3J25 Withdraw asset/network/recipient "
        "preparation v1 */"
    )

    block = CSS[
        CSS.index(marker):
    ]

    assert "@media (max-width: 980px)" in block
    assert "@media (max-width: 620px)" in block

    assert (
        ".treasury-withdrawal-route-recipient {\n"
        "    grid-column: 1 / 3;"
        in block
    )

    assert (
        ".treasury-withdrawal-route-actions {\n"
        "    grid-column: 2;"
        in block
    )

    assert (
        ".treasury-withdrawal-route-actions {\n"
        "    grid-column: 1;"
        in block
    )


def test_withdraw_header_copy_mentions_choose_or_prepare_flow():
    start = HTML.index(
        'id="treasuryWithdrawalAction"'
    )

    end = HTML.index(
        'id="treasuryRecords"',
        start,
    )

    block = HTML[
        start:end
    ]

    normalized = " ".join(
        block.split()
    )

    expected = (
        "Choose an approved destination or prepare one from "
        "a saved recipient, then enter the amount. "
        "Preflight performs Gate reads only; creating the "
        "request does not submit a withdrawal to Gate."
    )

    assert expected in normalized

def test_withdraw_recipient_manager_dialog_is_account_scoped_and_explains_approval():
    withdraw_start = HTML.index(
        'id="treasuryWithdrawalAction"'
    )

    withdraw_end = HTML.index(
        'id="treasuryRecords"',
        withdraw_start,
    )

    withdraw = HTML[
        withdraw_start:withdraw_end
    ]

    assert (
        'id="manageTreasuryWithdrawalRecipients"'
        in withdraw
    )

    assert (
        'id="treasuryWithdrawalRecipientDialog"'
        in HTML
    )

    dialog_start = HTML.index(
        'id="treasuryWithdrawalRecipientDialog"'
    )

    dialog = " ".join(
        HTML[
            dialog_start:
        ].split()
    )

    assert (
        "Saving an address does not approve a withdrawal destination."
        in dialog
    )

    assert (
        "administrator approval before it can be used."
        in dialog
    )

    bind = _stage4_js_function_block(
        "bindEvents"
    )

    assert (
        "'#manageTreasuryWithdrawalRecipients'"
        in bind
    )

    assert (
        "openTreasuryWithdrawalRecipientManager"
        in bind
    )


def test_withdraw_recipient_manager_loads_all_statuses_for_selected_owner():
    block = _stage4_js_function_block(
        "loadTreasuryWithdrawalRecipientManager"
    )

    assert (
        "treasuryWithdrawalPreparationOwner()"
        in block
    )

    assert (
        "'/api/treasury/withdrawals/recipients'"
        in block
    )

    assert (
        "owner_account_id: owner"
        in block
    )

    assert (
        "limit: 500"
        in block
    )

    assert (
        "status:"
        not in block
    )

    assert (
        "if (result.gate_write_performed)"
        in block
    )


def test_withdraw_recipient_manager_create_sends_only_owner_address_and_description():
    block = _stage4_js_function_block(
        "createTreasuryWithdrawalRecipientFromManager"
    )

    for token in (
        "method: 'POST'",
        "owner_account_id: owner",
        "address,",
        "label,",
        "if (result.gate_write_performed)",
    ):
        assert token in block

    for forbidden in (
        "currency:",
        "chain:",
        "memo:",
        "destination_id:",
        "GateClient",
        "DELETE",
    ):
        assert forbidden not in block


def test_withdraw_recipient_manager_rename_never_edits_address():
    block = _stage4_js_function_block(
        "mutateTreasuryWithdrawalRecipientFromManager"
    )

    assert (
        "action === 'rename'"
        in block
    )

    assert (
        "method = 'PATCH';"
        in block
    )

    assert (
        "body = {\n"
        "      label:"
        in block
    )

    assert (
        "address:"
        not in block
    )

    assert (
        "if (result.gate_write_performed)"
        in block
    )

    dialog_start = HTML.index(
        'id="treasuryWithdrawalRecipientDialog"'
    )

    dialog = " ".join(
        HTML[
            dialog_start:
        ].split()
    )

    assert (
        "Addresses cannot be edited in place."
        in dialog
    )


def test_withdraw_recipient_manager_archive_restore_are_local_and_have_no_delete():
    block = _stage4_js_function_block(
        "mutateTreasuryWithdrawalRecipientFromManager"
    )

    for token in (
        "action === 'archive'",
        "action === 'restore'",
        "method = 'POST';",
        "reason: '',",
        "if (result.gate_write_performed)",
    ):
        assert token in block

    assert "DELETE" not in block

    render = _stage4_js_function_block(
        "renderTreasuryWithdrawalRecipientManager"
    )

    assert "'restore'" in render
    assert "'archive'" in render
    assert "Archived" in render
    assert "Active" in render


def test_withdraw_recipient_manager_refreshes_dropdown_and_closes_with_session():
    create = _stage4_js_function_block(
        "createTreasuryWithdrawalRecipientFromManager"
    )

    mutate = _stage4_js_function_block(
        "mutateTreasuryWithdrawalRecipientFromManager"
    )

    for block in (
        create,
        mutate,
    ):
        assert (
            "loadTreasuryWithdrawalRecipientManager({"
            in block
        )

        assert (
            "loadTreasuryOverview({"
            in block
        )

    clear = _stage4_js_function_block(
        "clearTreasurySession"
    )

    assert (
        "'#treasuryWithdrawalRecipientDialog'"
        in clear
    )

    assert (
        "recipientDialog.close();"
        in clear
    )


def test_withdraw_recipient_manager_css_is_compact_and_responsive():
    marker = (
        "/* 3J26 Withdrawal recipient manager v1 */"
    )

    assert marker in CSS

    block = CSS[
        CSS.index(marker):
    ]

    for token in (
        ".treasury-withdrawal-recipient-dialog[open]",
        ".treasury-recipient-safety-note",
        ".treasury-recipient-card",
        ".treasury-recipient-status.active",
        ".treasury-recipient-status.archived",
        ".treasury-recipient-actions",
        "@media (max-width: 620px)",
    ):
        assert token in block

def test_treasury_withdrawal_css_uses_defined_theme_tokens():
    for invalid in (
        "var(--text-muted)",
        "var(--success)",
        "var(--danger)",
    ):
        assert invalid not in CSS

    for canonical in (
        "var(--muted)",
        "var(--positive)",
        "var(--negative)",
    ):
        assert canonical in CSS

def _stage5_js_function_block(name):
    from pathlib import Path
    import re

    source = Path(
        "frontend/app.js"
    ).read_text(
        encoding="utf-8"
    )

    pattern = re.compile(
        r"(?m)^(?:async\s+)?function\s+"
        + re.escape(name)
        + r"\s*\("
    )

    matches = list(
        pattern.finditer(source)
    )

    assert len(matches) == 1

    match = matches[0]

    parameter_opening = (
        match.end() - 1
    )

    assert (
        source[parameter_opening]
        == "("
    )

    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False

    index = parameter_opening

    while index < len(source):
        char = source[index]

        next_char = (
            source[index + 1]
            if index + 1 < len(source)
            else ""
        )

        if line_comment:
            if char == "\n":
                line_comment = False

            index += 1
            continue

        if block_comment:
            if (
                char == "*"
                and next_char == "/"
            ):
                block_comment = False
                index += 2
                continue

            index += 1
            continue

        if quote is not None:
            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == quote:
                quote = None

            index += 1
            continue

        if char in (
            "'",
            '"',
            "`",
        ):
            quote = char
            index += 1
            continue

        if (
            char == "/"
            and next_char == "/"
        ):
            line_comment = True
            index += 2
            continue

        if (
            char == "/"
            and next_char == "*"
        ):
            block_comment = True
            index += 2
            continue

        if char == "(":
            depth += 1

        elif char == ")":
            depth -= 1

            if depth == 0:
                index += 1
                break

        index += 1

    body_opening = source.find(
        "{",
        index,
    )

    assert body_opening >= 0

    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False

    index = body_opening

    while index < len(source):
        char = source[index]

        next_char = (
            source[index + 1]
            if index + 1 < len(source)
            else ""
        )

        if line_comment:
            if char == "\n":
                line_comment = False

            index += 1
            continue

        if block_comment:
            if (
                char == "*"
                and next_char == "/"
            ):
                block_comment = False
                index += 2
                continue

            index += 1
            continue

        if quote is not None:
            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == quote:
                quote = None

            index += 1
            continue

        if char in (
            "'",
            '"',
            "`",
        ):
            quote = char
            index += 1
            continue

        if (
            char == "/"
            and next_char == "/"
        ):
            line_comment = True
            index += 2
            continue

        if (
            char == "/"
            and next_char == "*"
        ):
            block_comment = True
            index += 2
            continue

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return source[
                    match.start():
                    index + 1
                ]

        index += 1

    raise AssertionError(
        f"Unable to extract JS function {name}"
    )


def test_withdraw_destination_review_is_super_admin_only_and_gate_distinct():
    normalized_html = " ".join(
        HTML.split()
    )

    assert (
        'id="reviewTreasuryWithdrawalDestinations"'
        in HTML
    )

    assert (
        'id="treasuryWithdrawalDestinationReviewDialog"'
        in HTML
    )

    assert (
        "Dashboard approval and Gate eligibility are separate."
        in normalized_html
    )

    assert (
        "does not add the address to Gate"
        in normalized_html
    )

    block = _stage5_js_function_block(
        "openTreasuryWithdrawalDestinationReview"
    )

    normalized = " ".join(
        block.split()
    )

    assert (
        "state.adminUser.role !== 'super_admin'"
        in normalized
    )

    render = _stage5_js_function_block(
        "renderTreasuryWithdrawalDestinations"
    )

    assert (
        "state.adminUser?.role === 'super_admin'"
        in render
    )

    assert (
        "'#reviewTreasuryWithdrawalDestinations'"
        in render
    )


def test_withdraw_destination_review_load_is_selected_owner_scoped_and_read_only():
    block = _stage5_js_function_block(
        "loadTreasuryWithdrawalDestinationReview"
    )

    normalized = " ".join(
        block.split()
    )

    for token in (
        "treasuryWithdrawalPreparationOwner()",
        "'/api/treasury/withdrawals/destinations'",
        "owner_account_id: owner",
        "limit: 500",
        "if (result.gate_write_performed)",
    ):
        assert token in block

    assert "status:" not in block

    assert (
        "treasuryWithdrawalPreparationOwner() !== owner"
        in normalized
    )


def test_withdraw_destination_review_requires_reason_and_exact_confirmation():
    required = _stage5_js_function_block(
        "treasuryWithdrawalDestinationDecisionConfirmation"
    )

    assert (
        "WITHDRAWAL DESTINATION"
        in required
    )

    update = _stage5_js_function_block(
        "updateTreasuryWithdrawalDestinationReviewActions"
    )

    normalized_update = " ".join(
        update.split()
    )

    assert (
        "reason.length >= 20"
        in normalized_update
    )

    assert (
        "confirmation === required"
        in normalized_update
    )

    mutate = _stage5_js_function_block(
        "mutateTreasuryWithdrawalDestinationReview"
    )

    normalized_mutate = " ".join(
        mutate.split()
    )

    assert (
        "reason.length < 20"
        in normalized_mutate
    )

    assert (
        "confirmation !== required"
        in normalized_mutate
    )


def test_withdraw_destination_review_mutation_is_local_approve_revoke_only():
    block = _stage5_js_function_block(
        "mutateTreasuryWithdrawalDestinationReview"
    )

    for token in (
        "'approve'",
        "'revoke'",
        "method: 'POST'",
        "confirmation,",
        "reason,",
        "if (result.gate_write_performed)",
        "clearTreasuryWithdrawalPreflight();",
        "loadTreasuryOverview({",
    ):
        assert token in block

    for forbidden in (
        "address:",
        "currency:",
        "chain:",
        "memo:",
        "/execute",
        "GateClient",
        "DELETE",
    ):
        assert forbidden not in block


def test_withdraw_destination_review_renders_full_security_states():
    block = _stage5_js_function_block(
        "renderTreasuryWithdrawalDestinationReview"
    )

    for token in (
        "'candidate'",
        "'pending_verification'",
        "'approved'",
        "'revoked'",
        "Approve confirmation",
        "Revoke confirmation",
        "Dashboard verification",
        "Legacy / unlinked",
        "Revoked destinations are terminal",
    ):
        assert token in block


def test_withdraw_approved_destinations_are_selected_account_scoped():
    block = _stage5_js_function_block(
        "loadTreasuryOverview"
    )

    normalized = " ".join(
        block.split()
    )

    for token in (
        "const withdrawalDestinationRequest",
        "'/api/treasury/withdrawals/destinations'",
        "owner_account_id: withdrawalRecipientOwner",
        "status: 'approved'",
        "withdrawalDestinationRequest,",
        "privateBalanceTargetAccount()",
    ):
        assert token in block

    assert (
        "privateBalanceTargetAccount() === withdrawalRecipientOwner"
        in normalized
    )

    assert (
        "destinations?status=approved&limit=100"
        not in block
    )


def test_withdraw_destination_review_follows_selected_account_when_dialog_is_open():
    block = _stage5_js_function_block(
        "loadTreasuryOverview"
    )

    normalized = " ".join(
        block.split()
    )

    assert (
        "'#treasuryWithdrawalDestinationReviewDialog'"
        in block
    )

    assert (
        "destinationReviewDialog?.open"
        in block
    )

    assert (
        "Reviewing destination routes for ${reviewOwner}"
        in block
    )

    assert (
        "await loadTreasuryWithdrawalDestinationReview({ quiet: true, });"
        in normalized
    )


def test_withdraw_destination_review_closes_with_treasury_session_and_is_responsive():
    clear = _stage5_js_function_block(
        "clearTreasurySession"
    )

    assert (
        "'#treasuryWithdrawalDestinationReviewDialog'"
        in clear
    )

    assert (
        "destinationReviewDialog.close();"
        in clear
    )

    marker = (
        "/* 3J27 Withdrawal destination review v1 */"
    )

    assert marker in CSS

    block = CSS[
        CSS.index(marker):
    ]

    for token in (
        ".treasury-withdrawal-destination-review-dialog[open]",
        ".treasury-destination-review-card",
        ".treasury-destination-review-status.candidate",
        ".treasury-destination-review-status.approved",
        ".treasury-destination-review-status.revoked",
        ".treasury-destination-review-actions",
        "@media (max-width: 760px)",
        "@media (max-width: 520px)",
    ):
        assert token in block
