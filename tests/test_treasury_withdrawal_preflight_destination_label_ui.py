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


def test_preflight_destination_label_uses_exact_recipient_link():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        "const destinationRecipientId = String("
        in block
    )

    assert (
        "destination?.recipient_id || ''"
        in block
    )

    lookup = destination_lookup(block)

    assert (
        "state.treasuryWithdrawalRecipients || []"
        in lookup
    )

    assert (
        "item.recipient_id || ''"
        in lookup
    )

    assert (
        "=== destinationRecipientId"
        in lookup
    )


def test_recipient_lookup_does_not_infer_by_address():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    lookup = destination_lookup(block)

    assert (
        "item.address"
        not in lookup
    )

    assert (
        "destination?.address"
        not in lookup
    )

    assert (
        "AddressMatch"
        not in lookup
    )

    assert (
        "addressMatch"
        not in lookup
    )


def test_current_recipient_label_precedes_destination_label():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    label_start = block.index(
        "const destinationLabel ="
    )

    label_end = block.index(
        "element.innerHTML",
        label_start,
    )

    label_block = block[
        label_start:
        label_end
    ]

    assert (
        label_block.index(
            "destinationRecipient?.label"
        )
        <
        label_block.index(
            "destination?.label"
        )
    )


def test_legacy_destination_fallback_remains_available():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    label_start = block.index(
        "const destinationLabel ="
    )

    label_end = block.index(
        "element.innerHTML",
        label_start,
    )

    label_block = block[
        label_start:
        label_end
    ]

    assert (
        "destination?.label"
        in label_block
    )

    assert (
        "shortTreasuryGateId("
        in label_block
    )

    assert (
        "destination?.address"
        in label_block
    )

    assert (
        "snapshot.destinationId"
        in label_block
    )


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


def test_preflight_still_renders_destination_field():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        "<span>Destination</span>"
        in block
    )

    assert (
        "destinationLabel"
        in block
    )
