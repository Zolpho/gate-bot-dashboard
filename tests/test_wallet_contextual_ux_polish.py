from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT / "frontend" / "index.html"
).read_text()

APP = (
    ROOT / "frontend" / "app.js"
).read_text()

WALLET_CSS = (
    ROOT / "frontend" / "wallet-tab.css"
).read_text()

DEPOSIT_CSS = (
    ROOT / "frontend" / "deposit.css"
).read_text()

TREASURY_CSS = (
    ROOT / "frontend" / "treasury.css"
).read_text()


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(name):
    matches = list(
        FUNCTION_PATTERN.finditer(APP)
    )

    found = []

    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(APP)
        )

        found.append(
            APP[
                match.start():
                end
            ]
        )

    assert len(found) == 1

    return found[0]


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        self.rows.append(
            (
                tag,
                attrs.get("id"),
                tuple(
                    attrs.get(
                        "class",
                        "",
                    ).split()
                ),
            )
        )


PARSER = Parser()
PARSER.feed(HTML)


def row(element_id):
    matches = [
        item
        for item in PARSER.rows
        if item[1] == element_id
    ]

    assert len(matches) == 1

    return matches[0]


def test_wallet_has_explicit_account_context():
    assert row(
        "walletAccountContext"
    )[0] == "div"

    block = function(
        "renderWalletAccountContext"
    )

    assert (
        "privateBalanceTargetAccount()"
        in block
    )

    assert (
        "Wallet account ·"
        in block
    )


def test_deposit_workflow_is_inline_not_dialog():
    tag, _, classes = row(
        "depositDialog"
    )

    assert tag == "section"

    assert (
        "wallet-deposit-workflow"
        in classes
    )

    assert "hidden" in classes


def test_deposit_preserves_existing_operational_controls():
    for element_id in (
        "depositCurrencySearch",
        "depositFavorites",
        "depositCurrencyList",
        "depositNetworkList",
        "depositDetails",
        "depositQr",
        "depositAddress",
        "depositMemo",
    ):
        row(element_id)


def test_deposit_uses_three_stage_visual_flow():
    assert (
        'class="deposit-flow"'
        in HTML
    )

    for label in (
        "Asset",
        "Network",
        "Address",
    ):
        assert label in HTML


def test_deposit_catalog_is_search_first():
    block = function(
        "renderDepositCurrencies"
    )

    assert (
        "filtered.slice(0, 100)"
        in block
    )

    assert (
        "Use a quick asset above or search"
        in block
    )

    assert (
        "slice(0, 300)"
        not in block
    )


def test_inline_deposit_no_longer_uses_dialog_top_layer():
    open_block = function(
        "openDepositDialog"
    )

    close_block = function(
        "closeDepositDialog"
    )

    assert ".showModal()" not in open_block
    assert ".close()" not in close_block

    assert (
        "classList.remove("
        in open_block
    )

    assert (
        "classList.add("
        in close_block
    )


def test_deposit_gate_reads_remain_get_only():
    currency = function(
        "selectDepositCurrency"
    )

    network = function(
        "selectDepositNetwork"
    )

    assert (
        "/api/me/deposit/"
        in currency
    )

    assert "/networks" in currency

    assert (
        "/api/me/deposit/"
        in network
    )

    assert "method: 'POST'" not in currency
    assert "method: 'POST'" not in network


def test_withdrawal_form_starts_hidden():
    tag, _, classes = row(
        "treasuryWithdrawalForm"
    )

    assert tag == "form"
    assert "hidden" in classes


def test_withdrawal_form_visibility_follows_exact_route_match():
    block = function(
        "renderTreasuryWithdrawalDestinations"
    )

    assert (
        "resolution.status === 'matched'"
        in block
    )

    assert (
        "form?.classList.toggle("
        in block
    )

    assert "!ready" in block


def test_unmatched_destination_has_no_large_placeholder():
    block = function(
        "renderTreasuryWithdrawalDestinationSummary"
    )

    assert (
        "Complete the route above to match"
        not in block
    )

    assert (
        "element.innerHTML = '';"
        in block
    )

    assert (
        "element.classList.add('hidden');"
        in block
    )

    assert (
        "element.classList.remove('hidden');"
        in block
    )


def test_create_request_reuses_existing_disabled_safety_state():
    block = function(
        "renderTreasuryWithdrawalPreflight"
    )

    assert (
        "createButton.disabled = true;"
        in block
    )

    assert (
        "#createTreasuryWithdrawalRequest:disabled"
        in TREASURY_CSS
    )


def test_withdrawal_safety_endpoints_are_unchanged():
    route = function(
        "treasuryWithdrawalRouteReadyForPreflight"
    )

    preflight = function(
        "runTreasuryWithdrawalPreflight"
    )

    request = function(
        "createTreasuryWithdrawalRequest"
    )

    assert (
        "resolution.status === 'matched'"
        in route
    )

    assert (
        "/api/treasury/withdrawals/preflight/"
        in preflight
    )

    assert (
        "/api/treasury/withdrawals/requests/simulate"
        in request
    )

    assert (
        "gate_write_performed"
        in request
    )


def test_transfer_badge_describes_request_flow():
    block = function(
        "renderTreasuryUserTransferParticipants"
    )

    assert (
        "REQUEST FLOW ENABLED"
        in block
    )

    assert (
        "REQUEST FLOW DISABLED"
        in block
    )

    assert (
        "USER TRANSFERS ENABLED"
        not in block
    )

    assert (
        "USER TRANSFERS DISABLED"
        not in block
    )


def test_footer_is_short_and_explicit():
    assert (
        "Live Gate withdrawal execution is currently disarmed."
        in HTML
    )

    assert (
        "Preflight is read-only and request creation "
        "is audited locally."
        in HTML
    )


def test_wallet_nav_is_more_compact():
    assert (
        "/* Wallet contextual UX polish J18 */"
        in WALLET_CSS
    )

    assert "top: 8px;" in WALLET_CSS
    assert "min-height: 36px;" in WALLET_CSS


def test_inline_deposit_css_exists():
    assert (
        "/* Wallet inline Deposit workflow J18 */"
        in DEPOSIT_CSS
    )

    assert (
        ".wallet-deposit-workflow"
        in DEPOSIT_CSS
    )

    assert (
        ".deposit-flow"
        in DEPOSIT_CSS
    )


def test_withdrawal_compaction_css_exists():
    assert (
        "/* Wallet Treasury compaction J18 */"
        in TREASURY_CSS
    )

    assert (
        ".treasury-withdrawal-form.hidden"
        in TREASURY_CSS
    )

    assert (
        ".treasury-withdrawal-destination-summary.hidden"
        in TREASURY_CSS
    )

    assert (
        "#createTreasuryWithdrawalRequest:disabled"
        in TREASURY_CSS
    )


def test_global_scroll_primitive_remains_centralized():
    assert APP.count(
        "window.scrollTo("
    ) == 1


def test_critical_ids_remain_unique():
    for element_id in (
        "depositButton",
        "depositDialog",
        "depositCurrencySearch",
        "depositNetworkList",
        "depositAddress",
        "depositHistorySection",
        "treasuryWithdrawalForm",
        "treasuryWithdrawalDestination",
        "treasuryWithdrawalAmount",
        "treasuryWithdrawalPreflightButton",
        "createTreasuryWithdrawalRequest",
        "treasuryWithdrawalPreflight",
        "treasuryUserTransferForm",
    ):
        assert HTML.count(
            f'id="{element_id}"'
        ) == 1

def test_j21_cache_keys_follow_changed_wallet_assets():
    current_key = "20260830-wallet-ux-j21-v2"
    unchanged_key = "20260830-wallet-ux-j19-v2"

    for asset in (
        "app.js",
        "deposit.css",
        "treasury.css",
    ):
        assert (
            f"./{asset}?v={current_key}"
            in HTML
        )

    assert (
        f"./wallet-tab.css?v={unchanged_key}"
        in HTML
    )
