from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text()

CSS = (
    ROOT
    / "frontend"
    / "treasury.css"
).read_text()


class TreasuryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = []
        self.stack = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)

        element_id = values.get("id")

        if element_id:
            self.ids.append(element_id)

        if tag != "section":
            return

        row = {
            "id": values.get("id", ""),
            "classes": set(
                values.get(
                    "class",
                    "",
                ).split()
            ),
            "line": self.getpos()[0],
        }

        self.sections.append(row)
        self.stack.append(row)

    def handle_endtag(self, tag):
        if tag == "section":
            self.stack.pop()


def parsed():
    parser = TreasuryParser()
    parser.feed(HTML)
    return parser


def test_withdrawal_precedes_registered_user_transfer():
    parser = parsed()

    withdrawal = [
        row
        for row in parser.sections
        if (
            row["id"]
            == "treasuryWithdrawalAction"
        )
    ]

    transfer = [
        row
        for row in parser.sections
        if (
            "treasury-user-transfer-section"
            in row["classes"]
        )
    ]

    assert len(withdrawal) == 1
    assert len(transfer) == 1

    assert (
        withdrawal[0]["line"]
        < transfer[0]["line"]
    )


def test_withdrawal_has_three_stage_visual_flow():
    assert HTML.count(
        'class="treasury-withdrawal-flow"'
    ) == 1

    assert (
        ">Destination<"
        in HTML
    )

    assert (
        ">Amount &amp; safety<"
        in HTML
    )

    assert (
        ">Create request<"
        in HTML
    )

    assert (
        "Local audited request only"
        in HTML
    )


def test_operational_withdrawal_ids_are_preserved_once():
    parser = parsed()

    required = (
        "treasuryWithdrawalAction",
        "treasuryWithdrawalState",
        "treasuryWithdrawalDestinationCount",
        "treasuryWithdrawalRouteBuilder",
        "treasuryWithdrawalAsset",
        "treasuryWithdrawalNetwork",
        "treasuryWithdrawalRecipient",
        "treasuryWithdrawalRecipientMemo",
        "manageTreasuryWithdrawalRecipients",
        "prepareTreasuryWithdrawalDestination",
        "treasuryWithdrawalDestination",
        "treasuryWithdrawalDestinationSummary",
        "treasuryWithdrawalPreflightContext",
        "treasuryWithdrawalAmount",
        "treasuryWithdrawalPreflightButton",
        "createTreasuryWithdrawalRequest",
        "treasuryWithdrawalPreflight",
    )

    for element_id in required:
        assert parser.ids.count(
            element_id
        ) == 1


def test_primary_withdrawal_and_secondary_transfer_span_workspace():
    assert (
        "3J39 Withdrawal primary workspace v1"
        in CSS
    )

    assert (
        "> #treasuryWithdrawalAction {"
        in CSS
    )

    assert (
        "> .treasury-user-transfer-section {"
        in CSS
    )

    assert CSS.count(
        "grid-column: 1 / -1;"
    ) >= 2


def test_amount_safety_workspace_is_two_column_desktop():
    assert (
        ".treasury-withdrawal-form {"
        in CSS
    )

    assert (
        "minmax(0, 1.34fr)"
        in CSS
    )

    assert (
        ".treasury-withdrawal-execution-row {"
        in CSS
    )


def test_behavior_script_cache_key_is_unchanged():
    assert (
        "./app.js?"
        "v=20260829-withdraw-no-jit-ready-v1"
        in HTML
    )


def test_treasury_css_cache_key_is_bumped_for_redesign():
    assert (
        "./treasury.css?"
        "v=20260829-withdraw-primary-card-v1"
        in HTML
    )
