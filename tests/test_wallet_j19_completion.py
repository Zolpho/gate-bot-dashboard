from pathlib import Path
import re


HTML = Path(
    "frontend/index.html"
).read_text()

APP = Path(
    "frontend/app.js"
).read_text()

WALLET_CSS = Path(
    "frontend/wallet-tab.css"
).read_text()

TREASURY_CSS = Path(
    "frontend/treasury.css"
).read_text()


def function_source(name):
    marker = f"function {name}("

    start = APP.index(marker)

    open_brace = APP.index(
        "{",
        start + len(marker),
    )

    depth = 0
    index = open_brace

    quote = None
    escaped = False
    line_comment = False
    block_comment = False

    while index < len(APP):
        char = APP[index]

        next_char = (
            APP[index + 1]
            if index + 1 < len(APP)
            else ""
        )

        if line_comment:
            if char == "\n":
                line_comment = False

            index += 1
            continue

        if block_comment:
            if (
                char == "*"
                and next_char == "/"
            ):
                block_comment = False
                index += 2
                continue

            index += 1
            continue

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None

            index += 1
            continue

        if (
            char == "/"
            and next_char == "/"
        ):
            line_comment = True
            index += 2
            continue

        if (
            char == "/"
            and next_char == "*"
        ):
            block_comment = True
            index += 2
            continue

        if char in (
            "'",
            '"',
            "`",
        ):
            quote = char
            index += 1
            continue

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return APP[
                    start:index + 1
                ]

        index += 1

    raise AssertionError(
        f"Unterminated JavaScript function: {name}"
    )


def test_j19s_wallet_subnav_is_not_sticky():
    marker = (
        "/* Wallet subnav collision fix J19S */"
    )

    block = WALLET_CSS[
        WALLET_CSS.index(marker):
    ]

    assert "position: static;" in block
    assert "top: auto;" in block
    assert "z-index: auto;" in block


def test_j19s_gate_bot_value_label_is_explicit():
    assert "Gate bot account value" in HTML

    assert "Gate quant account" not in HTML
    assert "Funds in Gate bots" not in HTML


def test_j19s_tracked_bot_note_is_explicit():
    balance = function_source(
        "renderPrivateBalance"
    )

    assert "Tracked bots:" in balance
    assert "bot.current_value" in balance
    assert "bot.initial_capital" in balance


def test_j19s_destination_summary_is_delivery_only():
    block = function_source(
        "renderTreasuryWithdrawalDestinationSummary"
    )

    assert "<span>Address</span>" in block
    assert "<span>Memo / tag</span>" in block

    for repeated in (
        "<span>Account</span>",
        "<span>Asset</span>",
        "<span>Network</span>",
    ):
        assert repeated not in block


def test_j19s_funding_summary_has_only_constraints():
    block = function_source(
        "renderTreasuryWithdrawalFundingSummary"
    )

    for required in (
        "<span>Available to withdraw</span>",
        "<span>Withdrawal fee</span>",
        "<span>Minimum withdrawal</span>",
    ):
        assert required in block

    assert "<span>Network</span>" not in block


def test_j19s_preflight_has_only_outcome_values():
    block = function_source(
        "renderTreasuryWithdrawalPreflight"
    )

    for required in (
        "<span>Withdrawal amount</span>",
        "<span>Estimated fee</span>",
        "<span>Recipient receives (est.)</span>",
    ):
        assert required in block

    for repeated in (
        "<span>Available to withdraw</span>",
        "<span>Network</span>",
        "<span>Destination</span>",
        'class="is-secondary"',
    ):
        assert repeated not in block


def test_j19s_preflight_safety_contract_remains():
    block = function_source(
        "renderTreasuryWithdrawalPreflight"
    )

    assert "preflight.preflight_valid" in block
    assert (
        "treasuryWithdrawalPreflightMatchesForm()"
        in block
    )
    assert "createButton.disabled = !valid" in block
    assert "Preflight passed" in block
    assert "Preflight blocked" in block


def test_j19s_decorative_withdrawal_flow_is_hidden():
    marker = (
        "/* Wallet Withdrawal flattening J19S */"
    )

    block = TREASURY_CSS[
        TREASURY_CSS.index(marker):
    ]

    assert ".treasury-withdrawal-flow {" in block
    assert "display: none;" in block


def test_j20_cache_keys_follow_changed_wallet_assets():
    current_key = "20260830-wallet-ux-j20-v1"
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
