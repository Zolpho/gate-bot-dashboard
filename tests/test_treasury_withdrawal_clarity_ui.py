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
        "Review funding and run preflight"
        in HTML
    )


def test_funding_renderer_uses_existing_capability_snapshot():
    assert (
        "function "
        "renderTreasuryWithdrawalFundingSummary()"
        in JS
    )

    for field in (
        "source_spot_available",
        "owner_liquid_main_held",
        "withdrawal_funding_available",
        "gate_limits",
        "fixed_fee",
        "percent_fee",
    ):
        assert field in JS


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


def test_funding_summary_explains_balance_model():
    assert (
        "Funding available = owner spot balance "
        in JS
    )

    assert (
        "+ liquid ownership already held in main custody."
        in JS
    )


def test_preflight_uses_operator_facing_labels():
    expected = (
        "Withdrawal amount",
        "Recipient receives (est.)",
        "Already in main custody",
        "Funding required",
        "JIT funding",
        "Additional main funding",
    )

    for label in expected:
        assert label in JS


def test_jit_required_has_plain_language_explanation():
    assert (
        "Additional main custody funding required"
        in JS
    )

    assert (
        "from the owner account into main custody"
        in JS
    )

    assert (
        "before the Gate withdrawal can proceed."
        in JS
    )


def test_no_jit_has_plain_language_ready_message():
    assert (
        "Funding ready"
        in JS
    )

    assert (
        "No JIT transfer is required before withdrawal."
        in JS
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


def test_asset_cache_keys_are_intentionally_unchanged_for_now():
    assert (
        "./treasury.css?"
        "v=20260829-withdraw-clarity-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260829-withdraw-clarity-v1"
        in HTML
    )
