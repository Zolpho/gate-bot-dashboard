from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

JS = (
    ROOT / "frontend" / "app.js"
).read_text()


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(name):
    matches = list(
        FUNCTION_PATTERN.finditer(JS)
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


def destination_lookup(block):
    start = block.index(
        "const destinationRecipient ="
    )

    end = block.index(
        "const destinationLabel =",
        start,
    )

    return block[start:end]


def test_current_destination_match_uses_exact_recipient_link():
    block = function(
        "treasuryWithdrawalDestinationMatchesRoute"
    )

    for token in (
        "const destinationRecipientId = String(",
        "destination.recipient_id || ''",
        "destinationRecipientId",
        "=== route.recipientId",
        "&& recipientMatches",
    ):
        assert token in block


def test_selected_recipient_lookup_does_not_infer_by_address():
    block = function(
        "treasurySelectedWithdrawalRecipient"
    )

    for token in (
        "state.treasuryWithdrawalRecipient",
        "treasuryWithdrawalActiveRecipients()",
        "item.recipient_id || ''",
        "=== recipientId",
    ):
        assert token in block

    for forbidden in (
        "item.address",
        "destination?.address",
        "AddressMatch",
        "addressMatch",
        "treasuryWithdrawalAddressMatchKey",
    ):
        assert forbidden not in block


def test_visible_route_carries_current_selected_recipient_id():
    block = function(
        "treasuryWithdrawalVisibleRoute"
    )

    for token in (
        "treasurySelectedWithdrawalRecipient()",
        "recipient?.recipient_id || ''",
        "recipientId,",
        "&& recipient",
        "&& recipientId",
    ):
        assert token in block


def test_legacy_unlinked_destination_route_fallback_remains_available():
    block = function(
        "treasuryWithdrawalDestinationMatchesRoute"
    )

    for token in (
        "const destinationRecipientId = String(",
        "destination.recipient_id || ''",
        "const recipientMatches = (",
        "destinationRecipientId",
        "=== route.recipientId",
        ": true",
        "destination.owner_account_id || ''",
        "destination.currency || ''",
        "destination.chain || ''",
        "treasuryWithdrawalAddressMatchKey(",
        "destination.memo || ''",
        "&& recipientMatches",
    ):
        assert token in block


def test_preflight_validity_contract_is_unchanged():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert re.search(
        r"const valid = Boolean\(\s*"
        r"preflight\.preflight_valid\s*"
        r"&& treasuryWithdrawalPreflightMatchesForm\(\)"
        r"\s*\);",
        block,
        re.S,
    )

    assert (
        "createButton.disabled = !valid;"
        in block
    )


def test_preflight_does_not_repeat_destination_but_form_match_pins_it():
    preflight = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert "<span>Destination</span>" not in preflight
    assert "destinationLabel" not in preflight

    matcher = function(
        "treasuryWithdrawalPreflightMatchesForm"
    )

    for token in (
        "state.treasuryWithdrawalPreflight",
        "treasurySelectedWithdrawalDestination()",
        "snapshot.destinationId",
        "destination.destination_id || ''",
        "snapshot.owner",
        "snapshot.currency",
        "snapshot.amount",
    ):
        assert token in matcher
