from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)

CSS = (
    ROOT
    / "frontend"
    / "aurora-mobile-topbar.css"
).read_text(
    encoding="utf-8"
)


def test_shared_mobile_topbar_stylesheet_is_aurora_only():
    marker = (
        'href="./aurora-mobile-topbar.css?'
        'v=20261003-m414c2j-nav-containment-v1"'
    )

    assert marker in HTML

    start = HTML.index(marker)

    block_start = HTML.rfind(
        "<link",
        0,
        start,
    )

    block_end = HTML.index(
        ">",
        start,
    )

    link = HTML[
        block_start:
        block_end + 1
    ]

    assert (
        'data-dashboard-ui-stylesheet="aurora"'
        in link
    )

    assert "disabled" in link


def test_shared_mobile_topbar_stylesheet_loads_after_aurora_symbols():
    assert (
        HTML.index(
            "./aurora-symbols.css?"
        )
        <
        HTML.index(
            "./aurora-mobile-topbar.css?"
        )
    )


def test_shared_mobile_topbar_rule_is_not_donate_specific():
    assert "#tab-donate" not in CSS
    assert ":has(" not in CSS

    assert (
        'html[data-dashboard-ui="aurora"] .topbar'
        in CSS
    )

    assert (
        ".topbar > div:first-child"
        in CSS
    )

    assert (
        ".top-actions"
        in CSS
    )


def test_mobile_title_and_actions_use_natural_height():
    for token in (
        "@media (max-width: 560px)",
        "min-height: 0 !important",
        "height: auto !important",
        "flex: 0 0 auto !important",
        "min-width: 0 !important",
        "align-self: stretch",
        "width: 100%",
    ):
        assert token in CSS


def test_shared_rule_does_not_redefine_page_control_layout():
    # Shared mobile CSS may own navigation geometry, but it
    # must not take over page-specific action controls.
    for forbidden in (
        "#adminButton",
        "#syncButton",
        "#globalAccountSelector",
        "#modeBadge",
    ):
        assert forbidden not in CSS

    marker = (
        'html[data-dashboard-ui="aurora"]\n'
        '  .top-actions {'
    )

    start = CSS.index(
        marker
    )

    body_start = CSS.index(
        "{",
        start,
    ) + 1

    body_end = CSS.index(
        "}",
        body_start,
    )

    body = CSS[
        body_start:
        body_end
    ]

    assert "display: grid" not in body
    assert "grid-template-columns" not in body


def test_shared_mobile_primary_navigation_stays_inside_viewport():
    required = (
        ".sidebar nav",
        "repeat(5, minmax(0, 1fr))",
        ".sidebar .nav-item",
        "width: 100%",
        "min-width: 0",
        "justify-content: center",
        "white-space: nowrap",
        "overflow: hidden",
        "text-overflow: ellipsis",
    )

    for token in required:
        assert token in CSS


def test_shared_mobile_navigation_disables_hover_translation():
    assert (
        ".sidebar .nav-item:hover"
        in CSS
    )

    assert (
        "transform: none"
        in CSS
    )
