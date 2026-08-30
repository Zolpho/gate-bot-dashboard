from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

JS = (
    ROOT / "frontend" / "app.js"
).read_text()

CSS = (
    ROOT / "frontend" / "treasury.css"
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

    blocks = []

    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(JS)
        )

        blocks.append(
            JS[
                match.start():
                end
            ]
        )

    assert len(blocks) == 1

    return blocks[0]


def test_clear_preflight_resets_success_button_wording():
    block = function(
        "clearTreasuryWithdrawalPreflight"
    )

    assert (
        "state.treasuryWithdrawalPreflight = null;"
        in block
    )

    assert (
        "renderTreasuryWithdrawalPreflight();"
        in block
    )

    assert (
        "button.textContent = 'Run safety preflight';"
        in block
    )


def test_renderer_clears_success_state_without_snapshot():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert re.search(
        r"if\s*\(!snapshot\)\s*\{.*?"
        r"classList\.remove\(\s*"
        r"'has-valid-preflight'",
        block,
        re.S,
    )


def test_renderer_success_state_is_tied_to_valid_preflight():
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

    assert re.search(
        r"classList\.toggle\(\s*"
        r"'has-valid-preflight',\s*"
        r"valid,\s*\);",
        block,
        re.S,
    )


def test_renderer_preserves_create_button_validity_contract():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        "createButton.disabled = !valid;"
        in block
    )


def test_preflight_economics_have_three_primary_cells():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        block.count(
            'class="is-primary'
        )
        == 3
    )

    assert (
        'class="is-primary is-recipient"'
        in block
    )

    for label in (
        "Withdrawal amount",
        "Estimated fee",
        "Recipient receives (est.)",
    ):
        assert re.search(
            r'class="is-primary[^"]*">\''
            r".*?"
            + re.escape(
                f"<span>{label}</span>"
            ),
            block,
            re.S,
        )


def test_preflight_has_three_primary_outcome_cells_and_no_secondary_cells():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        block.count(
            'class="is-primary">'
        )
        == 2
    )

    assert (
        block.count(
            'class="is-primary is-recipient">'
        )
        == 1
    )

    assert (
        'class="is-secondary"'
        not in block
    )

    for label in (
        "Withdrawal amount",
        "Estimated fee",
        "Recipient receives (est.)",
    ):
        assert (
            f"<span>{label}</span>"
            in block
        )

    for repeated in (
        "Available to withdraw",
        "Network",
        "Destination",
    ):
        assert (
            f"<span>{repeated}</span>"
            not in block
        )


def test_passed_rerun_label_requires_current_valid_snapshot():
    block = function(
        "runTreasuryWithdrawalPreflight"
    )

    assert (
        "preflightStillValid"
        in block
    )

    assert (
        "?.preflight_valid"
        in block
    )

    assert (
        "treasuryWithdrawalPreflightMatchesForm()"
        in block
    )

    assert (
        "Preflight passed · Run again"
        in block
    )


def test_route_barrier_still_precedes_preflight_get():
    block = function(
        "runTreasuryWithdrawalPreflight"
    )

    assert (
        block.index(
            "if (!routeMatchesDestination)"
        )
        <
        block.index(
            "adminApi("
        )
    )


def test_success_css_demotes_rerun_and_promotes_create():
    assert (
        "3J39 Withdrawal preflight success hierarchy v1"
        in CSS
    )

    assert re.search(
        r"#treasuryWithdrawalAction\.has-valid-preflight"
        r"\s*#treasuryWithdrawalPreflightButton\s*\{",
        CSS,
        re.S,
    )

    assert re.search(
        r"#treasuryWithdrawalAction\.has-valid-preflight"
        r"\s*#createTreasuryWithdrawalRequest"
        r":not\(:disabled\)\s*\{",
        CSS,
        re.S,
    )


def test_success_css_prioritizes_recipient_value():
    assert (
        "> .is-primary.is-recipient strong"
        in CSS
    )

    assert (
        "> .is-secondary strong"
        in CSS
    )
