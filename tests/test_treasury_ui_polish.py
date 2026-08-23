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
        "v=20260823-treasury-polish-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260823-treasury-polish-v1"
        in HTML
    )


def test_treasury_status_copy_distinguishes_transfer_paths():
    assert "Treasury transfer arm" in HTML
    assert "Separate from registered-user transfers" in HTML

    assert (
        "TREASURY TRANSFER ARM ENABLED"
        in APP
    )

    assert (
        "TREASURY TRANSFER ARM DISABLED"
        in APP
    )

    assert (
        "USER TRANSFERS ENABLED"
        in APP
    )

    assert (
        "USER TRANSFERS DISABLED"
        in APP
    )

    assert "LIVE TRANSFERS DISABLED" not in APP
    assert "LIVE TRANSFERS ENABLED" not in APP


def test_treasury_has_compact_action_workspace():
    assert 'class="treasury-actions-grid"' in HTML

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

    assert (
        "Records &amp; audit"
        in HTML
    )

    assert (
        ".treasury-records-summary"
        in CSS
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


def test_treasury_backend_semantics_remain_named_separately():
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
