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
        "v=20260823-treasury-status-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260823-treasury-status-v1"
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
        in HTML
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
        "TREASURY TRANSFER ARM ENABLED",
        "TREASURY TRANSFER ARM DISABLED",
        "USER TRANSFERS ENABLED",
        "USER TRANSFERS DISABLED",
        "WITHDRAWAL ARM ENABLED",
        "WITHDRAWAL ARM DISABLED",
    ):
        assert token in APP

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
        "health.treasury_transfers_enabled"
        in APP
    )

    assert (
        "health.treasury_withdrawals_enabled"
        in APP
    )

    assert (
        "state.treasuryUserTransfersEnabled"
        in APP
    )
