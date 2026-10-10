from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)

APP = (
    ROOT
    / "frontend"
    / "app.js"
).read_text(
    encoding="utf-8"
)

DONATE_CSS = (
    ROOT
    / "frontend"
    / "donate.css"
).read_text(
    encoding="utf-8"
)

TREASURY_CSS = (
    ROOT
    / "frontend"
    / "treasury.css"
).read_text(
    encoding="utf-8"
)


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(name):
    matches = list(
        FUNCTION_PATTERN.finditer(
            APP
        )
    )

    found = []

    for index, match in enumerate(
        matches
    ):
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


def test_public_attribution_is_optional_and_anonymous_by_default():
    for identifier in (
        "donateAttributionPanel",
        "donateAttributionMode",
        "donateAttributionNickname",
        "donateAttributionTelegram",
        "donateAttributionX",
        "donateAttributionSave",
        "donateAttributionStatus",
        "donateAttributionError",
    ):
        assert (
            f'id="{identifier}"'
            in HTML
        )

    for value in (
        "anonymous",
        "nickname",
        "telegram",
        "x",
        "telegram_x",
    ):
        assert (
            f'value="{value}"'
            in HTML
        )

    normalized = " ".join(
        HTML.lower().split()
    )

    assert (
        "anonymous by default"
        in normalized
    )

    assert "self-declared" in normalized
    assert "not verified" in normalized


def test_public_attribution_uses_only_matched_intent_capability():
    render = function(
        "renderDonateAttributionPanel"
    )

    save = function(
        "saveDonateAttribution"
    )

    assert (
        "donateIntentMatchesSelection()"
        in render
    )

    assert (
        "intent.status"
        in render
    )

    assert (
        "matched_event_id"
        in render
    )

    assert (
        "/api/donate/intents/${"
        in save
    )

    assert (
        "}/attribution`"
        in save
    )

    assert "api(" in save
    assert "adminApi(" not in save

    assert "claim_token" not in save
    assert "donateClaimToken" not in save

    assert "localStorage" not in save
    assert "sessionStorage" not in save


def test_internal_transfer_donation_is_explicit_and_eqtydao_only():
    assert (
        'id="treasuryUserTransferDonation"'
        in HTML
    )

    normalized = " ".join(
        HTML.lower().split()
    )

    assert (
        "treat this transfer as a donation to eqtydao"
        in normalized
    )

    option = function(
        "renderTreasuryUserTransferDonationOption"
    )

    assert (
        "destination === 'eqtydao'"
        in option
    )

    assert (
        "checkbox.checked = false"
        in option
    )


def test_internal_donation_choice_is_frozen_across_preview_and_execute():
    preview = function(
        "runTreasuryUserTransferPreview"
    )

    execute = function(
        "executeTreasuryUserTransfer"
    )

    assert (
        "destination.toLowerCase() === 'eqtydao'"
        in preview
    )

    assert (
        "treasuryUserTransferDonation"
        in preview
    )

    assert "donation," in preview

    assert (
        "response?.preview?.donation"
        in preview
    )

    assert (
        "donation,"
        in preview[
            preview.index(
                "state.treasuryUserTransferPreview"
            ):
        ]
    )

    assert (
        "snapshot.donation"
        in execute
    )

    assert (
        "donation: Boolean("
        in execute
    )

    assert (
        "result.donation"
        in execute
    )

    assert (
        "donationPublication"
        in execute
    )


def test_internal_donation_scope_is_all_authorized_registered_sources():
    source_rows = function(
        "treasuryUserTransferSourceRows"
    )

    scoped_source = function(
        "treasuryScopedUserTransferSource"
    )

    option = function(
        "renderTreasuryUserTransferDonationOption"
    )

    preview = function(
        "runTreasuryUserTransferPreview"
    )

    assert (
        "item.can_source"
        in source_rows
    )

    assert (
        "state.selectedAccount"
        in scoped_source
    )

    # Donation eligibility depends on the destination and
    # explicit opt-in, not on one named source Wallet account.
    assert (
        "destination === 'eqtydao'"
        in option
    )

    assert (
        "treasuryUserTransferSource"
        not in option
    )

    assert (
        "destination.toLowerCase() === 'eqtydao'"
        in preview
    )

    assert (
        "'zolnode'"
        not in option
    )

    assert (
        "'zolnode'"
        not in preview
    )


def test_internal_donation_publication_is_captured_in_both_success_paths():
    execute = function(
        "executeTreasuryUserTransfer"
    )

    normal_start = execute.index(
        "if (status === 'success') {"
    )

    normal_end = execute.index(
        "const terminal = [",
        normal_start,
    )

    normal_success = execute[
        normal_start:
        normal_end
    ]

    audit_start = execute.index(
        "if (successful) {"
    )

    audit_end = execute.index(
        "if (errorBox) {",
        audit_start,
    )

    audit_success = execute[
        audit_start:
        audit_end
    ]

    assert "snapshot.donation" in normal_success
    assert "result.donation" in normal_success
    assert "donationPublication" in normal_success
    assert "publication_error" in normal_success

    assert "snapshot.donation" in audit_success
    assert "detail?.donation" in audit_success
    assert "donationPublication" in audit_success
    assert "publication_error" in audit_success


def test_internal_attribution_is_post_success_and_authenticated():
    render = function(
        "renderTreasuryDonationAttributionPanel"
    )

    save = function(
        "saveTreasuryDonationAttribution"
    )

    assert (
        "executionResult?.kind === 'success'"
        in render
    )

    assert (
        "publicationStatus === 'recorded'"
        in render
    )

    assert (
        "/api/treasury/user-transfers/${"
        in save
    )

    assert (
        "}/donation-attribution`"
        in save
    )

    assert "adminApi(" in save
    assert "GateClient" not in save
    assert "claim_token" not in save

    assert "localStorage" not in save
    assert "sessionStorage" not in save


def test_anonymous_mode_does_not_require_identity_fields():
    payload = function(
        "donationAttributionPayload"
    )

    assert (
        "displayMode === 'anonymous'"
        in payload
    )

    assert (
        "return payload;"
        in payload
    )

    assert (
        "payload.nickname"
        in payload
    )

    assert (
        "payload.telegram_handle"
        in payload
    )

    assert (
        "payload.x_handle"
        in payload
    )


def test_b2_attribution_styles_are_responsive():
    for token in (
        ".donate-attribution-panel",
        ".donate-attribution-grid",
        ".donate-attribution-actions",
        "@media (max-width: 720px)",
    ):
        assert token in DONATE_CSS

    for token in (
        ".treasury-user-transfer-donation-option",
        ".treasury-donation-attribution-panel",
        ".treasury-donation-attribution-grid",
        "@media (max-width: 680px)",
    ):
        assert token in TREASURY_CSS


def test_b2_frontend_assets_are_cache_busted():
    assert (
        "m417b2=20261010-donor-attribution-ui-v1"
        in HTML
    )

    assert (
        "./donate.css?"
        in HTML
    )

    assert (
        "./treasury.css?"
        in HTML
    )

    assert (
        "./app.js?"
        in HTML
    )
