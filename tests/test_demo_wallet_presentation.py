from __future__ import annotations

import re
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

JS_PATH = (
    ROOT
    / "frontend"
    / "app.js"
)

HTML_PATH = (
    ROOT
    / "frontend"
    / "index.html"
)


def _source() -> str:
    return JS_PATH.read_text(
        encoding="utf-8"
    )


def _function(
    name: str,
) -> str:
    source = _source()

    pattern = re.compile(
        rf"(?m)^"
        rf"(?:async\s+)?"
        rf"function\s+"
        rf"{re.escape(name)}\s*"
    )

    matches = list(
        pattern.finditer(
            source
        )
    )

    assert len(matches) == 1

    match = matches[0]
    start = match.start()

    paren = source.find(
        "(",
        match.end(),
    )

    assert paren >= 0

    index = paren
    paren_depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False

    while index < len(source):
        char = source[index]
        nxt = (
            source[index + 1]
            if index + 1 < len(source)
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
                and nxt == "/"
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
            and nxt == "/"
        ):
            line_comment = True
            index += 2
            continue

        if (
            char == "/"
            and nxt == "*"
        ):
            block_comment = True
            index += 2
            continue

        if char in {
            "'",
            '"',
            "`",
        }:
            quote = char
            index += 1
            continue

        if char == "(":
            paren_depth += 1

        elif char == ")":
            paren_depth -= 1

            if paren_depth == 0:
                index += 1
                break

        index += 1

    while (
        index < len(source)
        and source[index].isspace()
    ):
        index += 1

    assert source[index] == "{"

    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False

    while index < len(source):
        char = source[index]
        nxt = (
            source[index + 1]
            if index + 1 < len(source)
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
                and nxt == "/"
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
            and nxt == "/"
        ):
            line_comment = True
            index += 2
            continue

        if (
            char == "/"
            and nxt == "*"
        ):
            block_comment = True
            index += 2
            continue

        if char in {
            "'",
            '"',
            "`",
        }:
            quote = char
            index += 1
            continue

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return source[
                    start:
                    index + 1
                ]

        index += 1

    raise AssertionError(
        f"unbalanced function: {name}"
    )


def test_demo_wallet_has_separate_read_scope_state():
    source = _source()

    assert (
        "demoWalletAccount: ''"
        in source
    )

    helper = _function(
        "ensureDemoWalletAccount"
    )

    assert (
        "state.demoWalletAccount"
        in helper
    )

    assert (
        "demoWalletAccountIds"
        in helper
    )


def test_demo_still_has_no_account_management_authority():
    body = _function(
        "canManageAccount"
    )

    assert (
        "execution_mode === 'demo'"
        in body
    )

    demo_guard = body.index(
        "execution_mode === 'demo'"
    )

    assert (
        body.index(
            "return false",
            demo_guard,
        )
        > demo_guard
    )


def test_demo_navigation_now_exposes_wallet_but_not_unreviewed_tabs():
    presentation = _function(
        "renderDemoPresentation"
    )

    assert "'overview'" in presentation
    assert "'bots'" in presentation
    assert "'wallet'" in presentation

    switch_tab = _function(
        "switchTab"
    )

    guard_start = switch_tab.index(
        "isDemoSession()"
    )

    guard_end = switch_tab.index(
        "].includes(",
        guard_start,
    )

    guard = switch_tab[
        guard_start:
        guard_end
    ]

    assert "'overview'" in guard
    assert "'bots'" in guard
    assert "'wallet'" in guard

    assert "'trading'" not in guard
    assert "'security'" not in guard
    assert "'alerts'" not in guard


def test_demo_selector_ignores_production_overview_accounts():
    body = _function(
        "populateAccountSelector"
    )

    demo_guard = body.index(
        "if (isDemoSession())"
    )

    live_scope = body.index(
        "state.selectedAccount",
        demo_guard,
    )

    demo_segment = body[
        demo_guard:
        live_scope
    ]

    demo_return = body.index(
        "return;",
        demo_guard,
    )

    assert (
        demo_guard
        < body.index(
            "demoWalletAccountIds",
            demo_guard,
        )
        < demo_return
        < live_scope
    )

    assert (
        "demoWalletAccountLabel"
        in demo_segment
    )

    assert (
        "No Demo Wallet accounts"
        in demo_segment
    )

    # Compare executable source shape after removing formatting
    # whitespace. This deliberately avoids matching the harmless
    # UI text "No Demo Wallet accounts".
    demo_compact = "".join(
        demo_segment.split()
    )

    live_compact = "".join(
        body[
            live_scope:
        ].split()
    )

    assert (
        "accounts.map("
        not in demo_compact
    )

    assert (
        "accounts.map("
        in live_compact
    )

def test_demo_selector_change_never_changes_global_selected_account():
    body = _function(
        "changeSelectedAccount"
    )

    demo_guard = body.index(
        "if (isDemoSession())"
    )

    invalid_guard = body.index(
        "!accountIds.includes(",
        demo_guard,
    )

    invalid_return = body.index(
        "return;",
        invalid_guard,
    )

    demo_assignment = body.index(
        "state.demoWalletAccount",
        demo_guard,
    )

    global_assignment = body.index(
        "state.selectedAccount",
        demo_assignment,
    )

    demo_segment = body[
        demo_guard:
        global_assignment
    ]

    assert (
        demo_guard
        < invalid_guard
        < invalid_return
        < demo_assignment
        < global_assignment
    )

    assert (
        "state.demoWalletAccount"
        in demo_segment
    )

    assert (
        "loadWalletViewData"
        in demo_segment
    )

    assert (
        "loadTreasuryOverview"
        not in demo_segment
    )

    assert (
        "state.selectedAccount"
        not in demo_segment
    )


def test_demo_deposit_catalog_uses_bearer_transport():
    body = _function(
        "loadDepositCatalog"
    )

    assert (
        "isDemoSession()"
        in body
    )

    assert (
        "adminApi("
        in body
    )

    assert (
        "api("
        in body
    )

    assert (
        "/api/deposit/currencies"
        in body
    )


def test_demo_wallet_views_are_limited_to_balance_and_deposits():
    helper = _function(
        "walletViewForSession"
    )

    assert "'balance'" in helper
    assert "'deposits'" in helper
    assert "return 'balance'" in helper

    render = _function(
        "renderWalletView"
    )

    loader = _function(
        "loadWalletViewData"
    )

    switcher = _function(
        "switchWalletView"
    )

    for body in (
        render,
        loader,
        switcher,
    ):
        assert (
            "walletViewForSession"
            in body
        )


def test_demo_balance_loader_returns_before_treasury():
    body = _function(
        "loadWalletViewData"
    )

    demo_guard = body.index(
        "if (\n    isDemoSession()"
    )

    live_treasury = body.index(
        "loadTreasuryOverview",
        demo_guard,
    )

    demo_segment = body[
        demo_guard:
        live_treasury
    ]

    assert (
        "loadPrivateBalance"
        in demo_segment
    )

    assert (
        "loadDepositHistory"
        in demo_segment
    )

    assert (
        "loadTreasuryOverview"
        not in demo_segment
    )


def test_demo_presentation_hides_unwired_wallet_surfaces():
    body = _function(
        "renderDemoPresentation"
    )

    for marker in (
        "#walletTransfersTab",
        "#walletWithdrawalsTab",
        "#syncDepositHistory",
        "#walletBalanceRecords",
        "#treasuryPanel",
    ):
        assert marker in body


def test_demo_wallet_cache_bust_marker_is_present():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "m424e2=20261015-demo-presentation-shell-v1"
        in html
    )

    assert (
        "m424f4=20261017-demo-wallet-read-ui-v1"
        in html
    )
