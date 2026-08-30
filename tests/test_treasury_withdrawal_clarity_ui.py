from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text()

JS = (
    ROOT
    / "frontend"
    / "app.js"
).read_text()

CSS = (
    ROOT
    / "frontend"
    / "treasury.css"
).read_text()


def test_funding_summary_is_inside_withdrawal_workspace():
    withdrawal_start = HTML.index(
        'id="treasuryWithdrawalAction"'
    )

    amount = HTML.index(
        'id="treasuryWithdrawalAmount"'
    )

    funding = HTML.index(
        'id="treasuryWithdrawalFundingSummary"'
    )

    actions = HTML.index(
        'class="treasury-withdrawal-actions"'
    )

    assert (
        withdrawal_start
        < amount
        < funding
        < actions
    )


def test_stage_two_copy_mentions_funding():
    assert (
        "Review amount, fee and run preflight"
        in HTML
    )

    assert (
        "Review funding and run preflight"
        not in HTML
    )


def test_funding_renderer_uses_existing_capability_snapshot():
    start = JS.index(
        "function renderTreasuryWithdrawalFundingSummary()"
    )

    end = JS.index(
        "\nfunction ",
        start + 1,
    )

    renderer = JS[start:end]

    for field in (
        "withdrawal_funding_available",
        "gate_limits",
        "fixed_fee",
        "percent_fee",
    ):
        assert field in renderer

    for internal_field in (
        "source_spot_available",
        "owner_liquid_main_held",
    ):
        assert internal_field not in renderer


def test_funding_renderer_requires_matching_owner_asset_key():
    assert (
        "state.treasuryWithdrawalCapabilitiesKey"
        in JS
    )

    assert (
        "const capabilityKey ="
        in JS
    )

    assert (
        "=== capabilityKey"
        in JS
    )


def test_funding_summary_explains_withdrawal_constraints():
    start = JS.index(
        "function renderTreasuryWithdrawalFundingSummary()"
    )
    end = JS.index(
        "\nfunction ",
        start + 1,
    )
    renderer = JS[
        start:end
    ]

    for label in (
        "Withdrawal details",
        "Available to withdraw",
        "Withdrawal fee",
        "Minimum withdrawal",
    ):
        assert label in renderer

    assert "<span>Network</span>" not in renderer

    for semantic_source in (
        "availability.withdrawal_funding_available",
        "gateLimits.minimum",
        "network?.fixed_fee",
        "network?.percent_fee",
    ):
        assert semantic_source in renderer


def test_preflight_uses_transaction_outcome_labels():
    start = JS.index(
        "function renderTreasuryWithdrawalPreflight()"
    )
    end = JS.index(
        "\nfunction ",
        start + 1,
    )
    renderer = JS[
        start:end
    ]

    for label in (
        "Withdrawal amount",
        "Estimated fee",
        "Recipient receives (est.)",
    ):
        assert label in renderer

    for repeated in (
        "Available to withdraw",
        "<span>Network</span>",
        "<span>Destination</span>",
        'class="is-secondary"',
    ):
        assert repeated not in renderer

    for safety_anchor in (
        "preflight.preflight_valid",
        "treasuryWithdrawalPreflightMatchesForm()",
        "createButton.disabled = !valid",
        "Preflight passed",
        "Preflight blocked",
    ):
        assert safety_anchor in renderer


def test_jit_required_has_plain_language_explanation():
    start = JS.index(
        "function renderTreasuryWithdrawalPreflight()"
    )

    end = JS.index(
        "\nfunction ",
        start + 1,
    )

    renderer = JS[start:end]

    for internal_copy in (
        "Additional main custody funding required",
        "from the owner account into main custody",
        "minimum_jit_transfer",
        "jit_required",
    ):
        assert internal_copy not in renderer


def test_no_jit_has_plain_language_ready_message():
    start = JS.index(
        "function renderTreasuryWithdrawalPreflight()"
    )

    end = JS.index(
        "\nfunction ",
        start + 1,
    )

    renderer = JS[start:end]

    assert (
        "No withdrawal has been submitted yet."
        in renderer
    )

    assert "Funding ready" not in renderer

    assert (
        "No JIT transfer is required before withdrawal."
        not in renderer
    )


def test_clarity_css_is_present_and_responsive():
    assert (
        "3J39 Withdrawal clarity polish v1"
        in CSS
    )

    for selector in (
        ".treasury-withdrawal-funding-summary",
        ".treasury-withdrawal-funding-summary-grid",
        ".treasury-withdrawal-funding-callout",
    ):
        assert selector in CSS

    assert (
        "@media (max-width: 700px)"
        in CSS
    )


def test_j21_cache_keys_mark_current_wallet_assets():
    assert (
        './treasury.css?v=20260830-wallet-ux-j21-v1'
        in HTML
    )

    assert (
        './app.js?v=20260830-wallet-ux-j21-v1'
        in HTML
    )
