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
    / "bots-mobile-list.css"
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


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        if tag == "link":
            self.links.append(
                dict(attrs)
            )


def mobile_bots_link():
    parser = LinkCollector()
    parser.feed(HTML)

    matches = [
        item
        for item in parser.links
        if str(
            item.get(
                "href",
                "",
            )
        ).startswith(
            "./bots-mobile-list.css?"
        )
    ]

    assert len(matches) == 1

    return matches[0]


def test_mobile_bots_layer_is_shared_and_versioned():
    link = mobile_bots_link()

    assert (
        link["href"]
        == (
            "./bots-mobile-list.css?"
            "v=20261004-m414c5b-mobile-strategy-cards-v1"
        )
    )

    assert (
        "data-dashboard-ui-stylesheet"
        not in link
    )

    assert (
        "disabled"
        not in link
    )


def test_mobile_bots_layer_loads_after_theme_styles():
    mobile = HTML.index(
        "./bots-mobile-list.css?"
    )

    assert (
        HTML.index(
            "./aurora-bots.css?"
        )
        < mobile
    )

    assert (
        HTML.index(
            "./classic-mobile-controls.css?"
        )
        < mobile
    )

    assert (
        HTML.index(
            "./aurora-mobile-topbar.css?"
        )
        < mobile
    )


def test_mobile_bots_layer_is_phone_width_only():
    assert (
        "@media (max-width: 560px)"
        in CSS
    )

    assert (
        "#tab-bots"
        in CSS
    )

    for forbidden in (
        "#tab-overview",
        "#tab-alerts",
        "#tab-system",
        "#tab-donate",
        "#tab-wallet",
        "#tab-bot-control",
    ):
        assert forbidden not in CSS


def test_active_and_archived_tables_drop_desktop_min_width():
    for token in (
        "#tab-bots >",
        ".table-panel",
        ".archived-bots-content",
        ".table-scroll >",
        "table {",
        "min-width: 0;",
    ):
        assert token in CSS


def test_table_headers_remain_semantic_but_visually_hidden():
    assert "thead {" in CSS

    for token in (
        "position: absolute;",
        "width: 1px;",
        "height: 1px;",
        "clip-path: inset(50%);",
    ):
        assert token in CSS

    # Do not remove the semantic table headings.
    assert "thead {\n    display: none;" not in CSS


def test_mobile_rows_become_two_column_cards():
    assert "grid-template-columns:" in CSS

    assert (
        "repeat(\n        2,\n        minmax(0, 1fr)"
        in CSS
    )

    for token in (
        "border-radius:\n      14px;",
        "grid-column:\n      1 / -1;",
        ".strategy-cell",
    ):
        assert token in CSS


def test_active_mobile_field_labels_are_present():
    for label in (
        'content: "Account";',
        'content: "Status";',
        'content: "Invested";',
        'content: "Current value";',
        'content: "Total PnL";',
        'content: "ROI";',
        'content: "Runtime";',
    ):
        assert label in CSS


def test_archived_mobile_field_labels_are_present():
    for label in (
        'content: "Final value";',
        'content: "Archived";',
    ):
        assert label in CSS


def test_mobile_actions_are_reachable_and_expand_when_single():
    for token in (
        ".bot-row-actions",
        "> :only-child",
        "grid-column:",
        "1 / -1;",
        "min-height:",
        "40px;",
        ".bot-archive-action",
        ".bot-restore-action",
    ):
        assert token in CSS


def test_existing_renderers_and_actions_remain_canonical():
    for token in (
        "function renderBots()",
        "function renderArchivedBots()",
        'id="botsTableBody"',
        'id="archivedBotsTableBody"',
        'data-bot-id="${bot.id}"',
        'data-archive-bot-id="${bot.id}"',
        'data-restore-bot-id="${bot.id}"',
        ">Details →</button>",
        ">Archive</button>",
        ">Restore</button>",
    ):
        if token.startswith('id="'):
            assert token in HTML
        else:
            assert token in APP
