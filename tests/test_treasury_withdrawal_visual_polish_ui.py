from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT / "frontend" / "index.html"
).read_text()

JS = (
    ROOT / "frontend" / "app.js"
).read_text()

CSS = (
    ROOT / "frontend" / "treasury.css"
).read_text()


class Node:
    def __init__(
        self,
        tag,
        attrs,
        parent=None,
    ):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []
        self.data = []

    @property
    def node_id(self):
        return self.attrs.get("id")


class Parser(HTMLParser):
    VOID = {
        "meta",
        "link",
        "input",
        "br",
        "hr",
        "img",
    }

    def __init__(self):
        super().__init__()
        self.root = Node(
            "root",
            [],
        )
        self.stack = [
            self.root
        ]

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        node = Node(
            tag,
            attrs,
            self.stack[-1],
        )

        self.stack[-1].children.append(
            node
        )

        if tag not in self.VOID:
            self.stack.append(
                node
            )

    def handle_endtag(
        self,
        tag,
    ):
        for index in range(
            len(self.stack) - 1,
            0,
            -1,
        ):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(
        self,
        data,
    ):
        self.stack[-1].data.append(
            data
        )


def find_id(
    node,
    wanted,
):
    if node.node_id == wanted:
        return node

    for child in node.children:
        found = find_id(
            child,
            wanted,
        )

        if found is not None:
            return found

    return None


def text_content(node):
    parts = [
        *node.data,
    ]

    for child in node.children:
        parts.append(
            text_content(child)
        )

    return " ".join(
        " ".join(parts).split()
    )


def tree():
    parser = Parser()
    parser.feed(HTML)
    return parser.root


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def js_function(name):
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


def test_header_describes_route_first_matching():
    action = find_id(
        tree(),
        "treasuryWithdrawalAction",
    )

    assert action is not None

    text = text_content(action)

    assert (
        "Approved routes match automatically"
        in text
    )

    assert (
        "Choose an approved destination "
        "or prepare one"
        not in text
    )


def test_matched_destination_is_summary_surface():
    root = tree()

    select = find_id(
        root,
        "treasuryWithdrawalDestination",
    )

    summary = find_id(
        root,
        "treasuryWithdrawalDestinationSummary",
    )

    assert select is not None
    assert summary is not None

    assert (
        "Matched withdrawal destination"
        in text_content(select.parent)
    )

    assert re.search(
        r"#treasuryWithdrawalDestination\s*"
        r"\{\s*display:\s*none;",
        CSS,
        re.S,
    )


def test_asset_selector_does_not_show_private_spot_balance():
    block = js_function(
        "renderTreasuryWithdrawalRoutePreparation"
    )

    start = block.index(
        "assetSelect.innerHTML"
    )

    end = block.index(
        "assetSelect.value",
        start,
    )

    asset_block = block[
        start:
        end
    ]

    assert (
        "escapeHtml(currency)"
        in asset_block
    )

    assert (
        "fmtAssetQuantity"
        not in asset_block
    )

    assert (
        " available"
        not in asset_block
    )


def test_network_selector_uses_friendly_name_formatter():
    block = js_function(
        "renderTreasuryWithdrawalRoutePreparation"
    )

    assert (
        "treasuryWithdrawalDisplayNetworkName("
        in block
    )

    assert "item.name," in block
    assert "chain," in block


def test_internal_destination_option_is_concise():
    block = js_function(
        "renderTreasuryWithdrawalDestinations"
    )

    match = re.search(
        r"const optionText = \[(.*?)\]"
        r"\.join\(' · '\);",
        block,
        re.S,
    )

    assert match is not None

    body = match.group(1)

    assert "item.currency" in body
    assert "label" in body

    assert "item.chain" not in body
    assert "item.owner_account_id" not in body


def test_operational_ids_remain_present():
    root = tree()

    for node_id in (
        "treasuryWithdrawalAsset",
        "treasuryWithdrawalNetwork",
        "treasuryWithdrawalRecipient",
        "treasuryWithdrawalRecipientMemo",
        "treasuryWithdrawalDestination",
        "treasuryWithdrawalDestinationSummary",
        "treasuryWithdrawalAmount",
        "treasuryWithdrawalFundingSummary",
        "treasuryWithdrawalPreflightButton",
        "createTreasuryWithdrawalRequest",
    ):
        assert (
            find_id(
                root,
                node_id,
            )
            is not None
        )


def test_visual_polish_css_marker_exists():
    assert (
        "3J39 Withdrawal visual polish v1"
        in CSS
    )
