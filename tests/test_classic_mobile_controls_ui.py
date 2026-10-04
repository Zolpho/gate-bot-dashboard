from html.parser import HTMLParser
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
    / "classic-mobile-controls.css"
).read_text(
    encoding="utf-8"
)


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        if tag != "link":
            return

        self.links.append(
            dict(attrs)
        )


def classic_mobile_link():
    parser = LinkCollector()
    parser.feed(HTML)

    matches = [
        link
        for link in parser.links
        if str(
            link.get(
                "href",
                "",
            )
        ).startswith(
            "./classic-mobile-controls.css?"
        )
    ]

    assert len(matches) == 1

    return matches[0]


def test_classic_mobile_stylesheet_is_classic_only():
    link = classic_mobile_link()

    assert (
        link["href"]
        == (
            "./classic-mobile-controls.css?"
            "v=20261004-m414c4b-classic-mobile-controls-v1"
        )
    )

    assert (
        link.get(
            "data-dashboard-ui-stylesheet"
        )
        == "classic"
    )

    assert "disabled" in link


def test_classic_mobile_stylesheet_loads_after_shared_donate():
    assert (
        HTML.index(
            "./donate.css?"
        )
        <
        HTML.index(
            "./classic-mobile-controls.css?"
        )
    )

    assert (
        HTML.index(
            "./ui-mode.css?"
        )
        <
        HTML.index(
            "./classic-mobile-controls.css?"
        )
    )


def test_classic_mobile_layer_is_mobile_and_classic_scoped():
    assert (
        "@media (max-width: 560px)"
        in CSS
    )

    assert (
        'html[data-dashboard-ui="classic"]'
        in CSS
    )

    assert (
        'data-dashboard-ui="aurora"'
        not in CSS
    )


def test_classic_header_uses_one_three_cell_action_row():
    for token in (
        ".top-actions",
        "grid-template-columns:",
        "auto\n      minmax(0, 1fr)\n      minmax(0, 1fr)",
        "#modeBadge",
        "#adminButton",
        "#syncButton",
    ):
        assert token in CSS


def test_donate_reuses_shared_classic_action_geometry():
    for token in (
        "body:has(#tab-donate.active)",
        ".top-actions",
        "grid-template-columns:",
        "#adminButton",
        "#syncButton",
    ):
        assert token in CSS


def test_account_and_interface_controls_share_mobile_height():
    for token in (
        "#globalAccountSelector",
        ".dashboard-ui-switcher",
        ".dashboard-ui-select",
        "min-height: 44px",
        "height: 44px",
        "border-radius: 11px",
    ):
        assert token in CSS


def test_login_and_sync_share_mobile_button_geometry():
    assert (
        "#adminButton,"
        in CSS
    )

    assert (
        "#syncButton {"
        in CSS
    )

    for token in (
        "min-height: 44px",
        "height: 44px",
        "border-radius: 11px",
        "white-space: nowrap",
    ):
        assert token in CSS


def test_mobile_page_actions_are_normalized():
    for token in (
        "#exportCsv",
        "#addRuleButton",
        "#testAccountButton",
        "#loadRecommendations",
        ".alerts-rules-panel",
        "#tab-system\n  .button-row",
    ):
        assert token in CSS
