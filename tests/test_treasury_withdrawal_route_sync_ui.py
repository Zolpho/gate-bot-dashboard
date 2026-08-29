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

CSS = (
    ROOT
    / "frontend"
    / "treasury.css"
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


def test_route_builder_uses_agreed_user_wording():
    assert (
        "<strong>Withdrawal destination</strong>"
        in HTML
    )

    assert (
        "Request destination approval"
        in HTML
    )

    assert (
        "Selected withdrawal destination"
        in HTML
    )


def test_approval_action_is_hidden_before_resolution():
    match = re.search(
        r'<button[^>]*'
        r'id="prepareTreasuryWithdrawalDestination"'
        r'[^>]*>',
        HTML,
        re.S,
    )

    assert match is not None
    assert "hidden" in match.group(0)


def test_evm_address_match_is_case_insensitive():
    block = js_function(
        "treasuryWithdrawalAddressMatchKey"
    )

    assert "/^0x[0-9a-f]{40}$/i" in block
    assert "return address.toLowerCase();" in block
    assert "return address;" in block


def test_visible_route_contains_recipient_address_and_memo():
    block = js_function(
        "treasuryWithdrawalVisibleRoute"
    )

    for token in (
        "treasuryWithdrawalPreparationOwner()",
        "state.treasuryWithdrawalAsset",
        "treasurySelectedWithdrawalNetwork()",
        "treasurySelectedWithdrawalRecipient()",
        "recipient?.recipient_id",
        "recipient?.address",
        "treasuryWithdrawalRecipientMemo",
    ):
        assert token in block


def test_match_binds_exact_route_identity():
    block = js_function(
        "treasuryWithdrawalDestinationMatchesRoute"
    )

    for token in (
        "destination.status",
        "destination.owner_account_id",
        "destination.currency",
        "destination.chain",
        "destination.address",
        "destination.memo",
        "destination.recipient_id",
        "route.recipientId",
    ):
        assert token in block


def test_resolution_requires_exactly_one_match():
    block = js_function(
        "treasuryWithdrawalRouteResolution"
    )

    assert "matches.length === 1" in block
    assert "matches.length === 0" in block
    assert "'ambiguous'" in block


def test_destination_is_auto_selected_from_route():
    block = js_function(
        "syncTreasuryWithdrawalDestinationToRoute"
    )

    assert (
        "treasuryWithdrawalRouteResolution()"
        in block
    )

    assert (
        "resolution.destination?.destination_id"
        in block
    )


def test_legacy_destination_select_is_display_only():
    block = js_function(
        "renderTreasuryWithdrawalDestinations"
    )

    assert "select.disabled = true;" in block

    assert (
        "'Complete the route above'"
        in block
    )


def test_amount_and_preflight_require_exact_match():
    block = js_function(
        "renderTreasuryWithdrawalDestinations"
    )

    assert (
        "resolution.status === 'matched'"
        in block
    )

    assert "amount.disabled = !ready;" in block

    assert (
        "preflightButton.disabled = !ready;"
        in block
    )


def test_happy_path_has_no_approval_action():
    block = js_function(
        "updateTreasuryWithdrawalRoutePrepareButton"
    )

    assert (
        "resolution.status === 'missing'"
        in block
    )

    assert (
        "button.classList.toggle("
        in block
    )

    assert (
        "'Request destination approval'"
        in block
    )


def test_memo_change_re_resolves_route():
    block = js_function(
        "changeTreasuryWithdrawalMemo"
    )

    assert (
        "clearTreasuryWithdrawalPreflight();"
        in block
    )

    assert (
        "renderTreasuryWithdrawalRoutePreparation();"
        in block
    )


def test_existing_match_blocks_candidate_post():
    block = js_function(
        "prepareTreasuryWithdrawalRecipientDestination"
    )

    guard = block.index(
        "routeResolution.status === 'matched'"
    )

    post = block.index(
        "const result = await adminApi("
    )

    assert guard < post


def test_ambiguous_route_blocks_candidate_post():
    block = js_function(
        "prepareTreasuryWithdrawalRecipientDestination"
    )

    guard = block.index(
        "routeResolution.status !== 'missing'"
    )

    post = block.index(
        "const result = await adminApi("
    )

    assert guard < post


def test_preflight_has_authoritative_mismatch_barrier():
    block = js_function(
        "runTreasuryWithdrawalPreflight"
    )

    barrier = block.index(
        "if (!routeMatchesDestination)"
    )

    api_call = block.index(
        "const response = await adminApi("
    )

    assert barrier < api_call

    assert (
        "resolution.destination.destination_id"
        in block
    )

    assert (
        "destination.destination_id"
        in block
    )


def test_warning_style_exists():
    assert (
        "3J39 Withdrawal route auto-match safety v1"
        in CSS
    )

    assert (
        ".treasury-withdrawal-route-status.warning"
        in CSS
    )
