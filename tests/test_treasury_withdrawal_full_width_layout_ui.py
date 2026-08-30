from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

CSS = (
    ROOT / "frontend" / "treasury.css"
).read_text()

INDEX = (
    ROOT / "frontend" / "index.html"
).read_text()

START = (
    "/* 3J39 Withdrawal full-width execution layout v1 */"
)

END = (
    "/* End 3J39 Withdrawal full-width execution layout v1 */"
)


def layout_block():
    assert CSS.count(START) == 1
    assert CSS.count(END) == 1

    start = CSS.index(START)
    end = (
        CSS.index(
            END,
            start,
        )
        + len(END)
    )

    return CSS[start:end]


def test_withdrawal_form_is_full_width():
    block = layout_block()

    assert re.search(
        r"\.treasury-withdrawal-form\s*\{"
        r"[^}]*grid-template-columns:\s*1fr;",
        block,
        re.S,
    )


def test_desktop_execution_row_has_three_columns():
    block = layout_block()

    assert re.search(
        r"\.treasury-withdrawal-execution-row\s*\{"
        r"[^}]*grid-template-columns:\s*"
        r"minmax\(150px,\s*\.55fr\)\s*"
        r"minmax\(320px,\s*1\.35fr\)\s*"
        r"minmax\(220px,\s*\.8fr\);",
        block,
        re.S,
    )


def test_medium_execution_row_falls_back_to_two_columns():
    block = layout_block()

    assert re.search(
        r"@media\s*\(max-width:\s*960px\)"
        r"\s*\{.*?"
        r"\.treasury-withdrawal-execution-row\s*\{"
        r"[^}]*grid-template-columns:\s*"
        r"minmax\(160px,\s*\.65fr\)\s*"
        r"minmax\(260px,\s*1\.35fr\);",
        block,
        re.S,
    )


def test_mobile_execution_row_falls_back_to_one_column():
    block = layout_block()

    assert re.search(
        r"@media\s*\(max-width:\s*700px\)"
        r"\s*\{.*?"
        r"\.treasury-withdrawal-execution-row\s*\{"
        r"[^}]*grid-template-columns:\s*1fr;",
        block,
        re.S,
    )


def test_layout_patch_contains_no_behavior_selectors():
    block = layout_block()

    for forbidden in (
        "has-valid-preflight",
        "createTreasuryWithdrawalRequest",
        "treasuryWithdrawalPreflightButton",
        "Preflight passed",
    ):
        assert forbidden not in block


def test_css_cache_key_is_bumped_for_full_width_layout():
    expected = (
        './treasury.css?v=20260830-wallet-ux-j19-v2'
    )

    assert INDEX.count(expected) == 1
