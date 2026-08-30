from pathlib import Path
import re


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


FUNCTION_RE = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def js_function(name):
    matches = list(
        FUNCTION_RE.finditer(JS)
    )

    found = []

    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(JS)
        )

        found.append(
            JS[
                match.start():
                end
            ]
        )

    assert len(found) == 1
    return found[0]


def test_step_two_talks_about_amount_and_fee():
    assert (
        "Review amount, fee and run preflight"
        in HTML
    )

    assert (
        "Review funding and run preflight"
        not in HTML
    )


def test_redundant_preflight_context_is_hidden():
    match = re.search(
        r'<div[^>]*'
        r'id="treasuryWithdrawalPreflightContext"'
        r'[^>]*>',
        HTML,
        re.S,
    )

    assert match is not None
    assert "hidden" in match.group(0)

    assert "Preflight uses:" not in HTML


def test_destination_summary_uses_delivery_language_only():
    block = js_function(
        "renderTreasuryWithdrawalDestinationSummary"
    )

    assert "<span>Address</span>" in block
    assert "<span>Memo / tag</span>" in block

    for repeated in (
        "<span>Account</span>",
        "<span>Asset</span>",
        "<span>Network</span>",
        "Economic owner",
        "Preflight uses",
    ):
        assert repeated not in block


def test_network_name_helper_adds_parenthesis_spacing():
    block = js_function(
        "treasuryWithdrawalDisplayNetworkName"
    )

    assert "/([^\\s])\\(/g" in block
    assert "'$1 ('" in block


def test_withdrawal_details_show_user_economic_constraints():
    block = js_function(
        "renderTreasuryWithdrawalFundingSummary"
    )

    for token in (
        "Withdrawal details",
        "Available to withdraw",
        "Withdrawal fee",
        "Minimum withdrawal",
        "withdrawal_funding_available",
    ):
        assert token in block

    assert "<span>Network</span>" not in block


def test_withdrawal_details_hide_internal_custody_model():
    block = js_function(
        "renderTreasuryWithdrawalFundingSummary"
    )

    for token in (
        "Source spot",
        "Already in main custody",
        "Total funding available",
        "Live read-only capability data",
        "Funding available =",
        "ownership liabilities",
    ):
        assert token not in block


def test_preflight_shows_only_transaction_outcome_fields():
    block = js_function(
        "renderTreasuryWithdrawalPreflight"
    )

    for token in (
        "Withdrawal amount",
        "Estimated fee",
        "Recipient receives (est.)",
    ):
        assert token in block

    for repeated in (
        "Available to withdraw",
        "<span>Network</span>",
        "<span>Destination</span>",
        'class="is-secondary"',
    ):
        assert repeated not in block

    for internal_label in (
        "Already in main custody",
        "Funding required",
        "JIT funding",
        "Additional main funding",
        "Address policy",
        "Eligible via",
    ):
        assert internal_label not in block


def test_preflight_hides_jit_and_address_policy_internals():
    block = js_function(
        "renderTreasuryWithdrawalPreflight"
    )

    for token in (
        "Already in main custody",
        "Funding required",
        "JIT funding",
        "Additional main funding",
        "Address policy",
        "Eligible via",
        "Additional main custody funding required",
        "No JIT transfer is required",
        "into main custody",
    ):
        assert token not in block


def test_valid_preflight_says_nothing_has_been_submitted():
    block = js_function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        "No withdrawal has been submitted yet."
        in block
    )


def test_internal_backend_fields_are_not_required_for_rendering():
    block = js_function(
        "renderTreasuryWithdrawalPreflight"
    )

    for token in (
        "owner_main_held",
        "conservative_funding_required",
        "jit_required",
        "minimum_jit_transfer",
        "gate_address_eligibility",
        "address_policy",
        "eligible_via",
    ):
        assert token not in block
