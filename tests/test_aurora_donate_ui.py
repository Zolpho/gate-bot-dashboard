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
    / "aurora-donate.css"
).read_text(
    encoding="utf-8"
)


def test_aurora_donate_stylesheet_is_mode_scoped():
    marker = (
        'href="./aurora-donate.css?'
        'v=20261010-m416g3-mobile-donate-polish-v1'
        '&amp;m417e1=20261010-public-ledger-ui-v1"'
    )

    assert marker in HTML

    start = HTML.index(marker)

    link_start = HTML.rfind(
        "<link",
        0,
        start,
    )

    link_end = HTML.index(
        ">",
        start,
    )

    link = HTML[
        link_start:
        link_end + 1
    ]

    assert (
        'data-dashboard-ui-stylesheet="aurora"'
        in link
    )

    assert "disabled" in link


def test_aurora_donate_load_order_preserves_shared_layers():
    assert (
        HTML.index(
            "./donate.css?"
        )
        <
        HTML.index(
            "./aurora-donate.css?"
        )
    )

    assert (
        HTML.index(
            "./aurora-symbols.css?"
        )
        <
        HTML.index(
            "./aurora-donate.css?"
        )
        <
        HTML.index(
            "./aurora-mobile-topbar.css?"
        )
    )


def test_aurora_donate_has_distinct_mission_identity():
    for token in (
        'html[data-dashboard-ui="aurora"]',
        "#tab-donate",
        "PUBLIC DONATION ROUTE",
        "SERVER LOCKED",
        ".donate-hero::before",
        ".donate-destination-card::before",
        "radial-gradient(",
    ):
        assert token in CSS


def test_aurora_donate_uses_three_surface_desktop_workflow():
    for token in (
        ".donate-flow",
        "minmax(220px, 0.72fr)",
        "minmax(520px, 1.56fr)",
        "align-items: start;",
        ".deposit-step:not(.deposit-step-disabled)",
        "#donateDetailsStep",
    ):
        assert token in CSS


def test_aurora_donate_has_dedicated_destination_console():
    for token in (
        "#donateDetails",
        ".deposit-qr-card",
        ".deposit-qr-surface",
        ".deposit-address-fields",
        ".deposit-selected-summary",
        ".deposit-definition-list",
    ):
        assert token in CSS


def test_aurora_donate_responsive_layout_collapses_cleanly():
    for token in (
        "@media (max-width: 1320px)",
        "repeat(2, minmax(0, 1fr))",
        "minmax(320px, 1.56fr)",
        "@media (max-width: 900px)",
        "@media (max-width: 700px)",
        "grid-template-columns:\n      1fr;",
    ):
        assert token in CSS


def test_aurora_donate_ipad_band_promotes_send_surface_full_width():
    media_start = CSS.index(
        "@media (max-width: 1320px)"
    )

    media_end = CSS.index(
        "/* ------------------------------------------------------------\n"
        "   RESPONSIVE — TABLET",
        media_start,
    )

    tablet_band = CSS[
        media_start:
        media_end
    ]

    assert "#donateDetailsStep" in tablet_band
    assert "grid-column:\n      1 / -1;" in tablet_band
    assert "min-height: 0;" in tablet_band
    assert "minmax(180px, 0.44fr)" in tablet_band
    assert "minmax(320px, 1.56fr)" in tablet_band


def test_aurora_donate_mobile_network_and_tracking_fit_viewport():
    for token in (
        "M4.16G3 — MOBILE OVERFLOW POLISH",
        "#donateNetworkList",
        "overflow-x: hidden;",
        ".deposit-option-main > span",
        "text-overflow: ellipsis;",
        "white-space: nowrap;",
        ".deposit-option-status",
        "margin-left: auto;",
        ".donate-intent-head",
        ".mode-badge",
        "width: max-content;",
        "justify-self: start;",
    ):
        assert token in CSS


def test_aurora_donate_does_not_define_classic_mode():
    assert (
        'data-dashboard-ui="classic"'
        not in CSS
    )
