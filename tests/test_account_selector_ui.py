from pathlib import Path


HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)

CSS = Path(
    "frontend/styles.css"
).read_text(
    encoding="utf-8"
)


def test_account_selector_is_single_shared_control():
    assert (
        HTML.count('id="accountSelector"')
        == 1
    )

    assert (
        'id="globalAccountSelector"'
        in HTML
    )


def test_account_selector_has_compact_label_markup():
    assert (
        'class="account-selector-label"'
        in HTML
    )

    assert (
        ">Account</span>"
        in HTML
    )

    assert (
        'aria-label="Gate account"'
        in HTML
    )


def test_desktop_account_selector_is_compact():
    assert (
        "/* 3J16 Compact shared account selector */"
        in CSS
    )

    assert (
        ".account-selector-label"
        in CSS
    )

    assert "width: 156px;" in CSS
    assert "min-width: 156px;" in CSS
    assert "height: 32px;" in CSS
    assert "font-size: .76rem;" in CSS


def test_account_selector_label_is_inline_on_desktop():
    marker = (
        "/* 3J16 Compact shared account selector */"
    )

    start = CSS.index(marker)

    end = CSS.index(
        "/* End 3J16 Compact shared account selector */",
        start,
    )

    block = CSS[start:end]

    assert "display: inline-flex;" in block
    assert "align-items: center;" in block
    assert "gap: 6px;" in block


def test_account_selector_remains_responsive():
    marker = (
        "/* 3J16 Compact shared account selector */"
    )

    start = CSS.index(marker)

    block = CSS[start:]

    assert (
        "@media (max-width: 820px)"
        in block
    )

    assert (
        "grid-template-columns:"
        in block
    )

    assert "width: 100%;" in block
    assert "min-width: 0;" in block

    assert (
        "@media (max-width: 560px)"
        in block
    )

    assert "flex-basis: 100%;" in block


def test_stylesheet_cache_version_is_bumped():
    assert (
        "./styles.css?"
        "v=20260823-account-selector-wide-v1"
        in HTML
    )
