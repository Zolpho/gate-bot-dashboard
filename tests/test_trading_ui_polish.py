from pathlib import Path


def _html():
    return Path(
        "frontend/index.html"
    ).read_text(
        encoding="utf-8"
    )


def _js():
    return Path(
        "frontend/trading.js"
    ).read_text(
        encoding="utf-8"
    )


def _css():
    return Path(
        "frontend/trading.css"
    ).read_text(
        encoding="utf-8"
    )


def _limit_css():
    return Path(
        "frontend/trading-limit.css"
    ).read_text(
        encoding="utf-8"
    )


def test_trading_default_interval_is_one_hour():
    js = _js()
    html = _html()

    assert "interval: '1h'," in js
    assert "interval: '5m'," not in js

    assert (
        'class="trading-interval active" '
        'data-trading-interval="1h"'
        in html
    )

    assert (
        'class="trading-interval active" '
        'data-trading-interval="5m"'
        not in html
    )


def test_single_account_static_control_exists():
    html = _html()

    assert 'id="tradingAccount"' in html
    assert 'id="tradingAccountStatic"' in html
    assert 'class="trading-account-static hidden"' in html


def test_account_scope_renderer_is_catalog_driven():
    js = _js()

    assert (
        "function tradingRenderAccountControl(accounts)"
        in js
    )

    assert (
        "accounts.length === 1"
        in js
    )

    assert (
        "accountSelect?.classList.toggle("
        in js
    )

    assert (
        "tradingAccountControlLabel("
        in js
    )


def test_single_account_label_does_not_duplicate_id():
    js = _js()

    assert (
        "name.toLowerCase() === id.toLowerCase()"
        in js
    )

    assert "return id;" in js


def test_multi_account_selector_is_preserved():
    js = _js()

    start = js.index(
        "function tradingRenderAccountControl(accounts)"
    )

    end = js.index(
        "function tradingPopulateCatalog()",
        start,
    )

    helper = js[start:end]

    assert (
        "'hidden',\n    singleAccount"
        in helper
    )

    assert (
        "'hidden',\n    !singleAccount"
        in helper
    )


def test_trading_account_change_handler_remains():
    js = _js()

    assert (
        "$('#tradingAccount')?.addEventListener("
        in js
    )

    assert (
        "tradingState.accountId = accountId;"
        in js
    )


def test_trading_polish_markers_present_once():
    css = _css()
    limit_css = _limit_css()

    assert (
        css.count(
            "/* 3J13 Trading-specific polish v1 */"
        )
        == 1
    )

    assert (
        css.count(
            "/* End 3J13 Trading-specific polish v1 */"
        )
        == 1
    )

    assert (
        limit_css.count(
            "/* 3J13 Trading order-surface polish v1 */"
        )
        == 1
    )

    assert (
        limit_css.count(
            "/* End 3J13 Trading order-surface polish v1 */"
        )
        == 1
    )


def test_trading_static_account_is_visually_defined():
    css = _css()

    assert (
        "#tab-trading\n.trading-account-static"
        in css
    )


def test_trading_asset_versions_exact():
    html = _html()

    assert (
        "./trading.css?v=20260823-trading-refine-v3"
        in html
    )

    assert (
        "./trading-limit.css?v=20260823-sticky-book-v1"
        in html
    )

    assert (
        "./trading.js?v=20260823-trading-refine-v2"
        in html
    )

    assert (
        "./trading-limit.js?v=20260822-recovery-v1"
        in html
    )


def test_guarded_trading_surfaces_remain_present():
    html = _html()
    limit_css = _limit_css()

    # Execution/cancellation behavior is covered by the
    # dedicated Trading safety suites. This presentation
    # test only guarantees that the guarded UI surfaces
    # themselves were not removed by the polish pass.
    assert "trading-order-execution" in html
    assert "trading-order-cancellation" in html

    assert ".trading-order-execution" in limit_css
    assert ".trading-order-cancellation" in limit_css


def test_spot_pair_is_search_styled_not_select():
    html = _html()
    css = _css()

    assert (
        'class="trading-field trading-pair-field"'
        in html
    )

    assert (
        'class="trading-pair-search"'
        in html
    )

    assert 'id="tradingPair"' in html
    assert 'list="tradingPairOptions"' in html

    assert (
        ".trading-pair-search::before"
        in css
    )

    assert (
        ".trading-pair-search::after"
        in css
    )


def test_order_book_group_selector_is_compact():
    css = _css()

    assert (
        "#tab-trading\n.trading-depth-selector select"
        in css
    )

    assert "min-width: 72px;" in css
    assert "min-height: 31px;" in css


def test_trade_times_are_24_hour_utc():
    html = _html()
    js = _js()

    assert "<span>Time (UTC)</span>" in html

    block_start = js.index(
        "function tradingFormatTradeTime(value)"
    )

    block_end = js.index(
        "function tradingRenderTrades()",
        block_start,
    )

    block = js[
        block_start:block_end
    ]

    for token in (
        "getUTCHours()",
        "getUTCMinutes()",
        "getUTCSeconds()",
    ):
        assert token in block

    assert "toLocaleTimeString" not in block


def test_order_history_times_are_explicit_utc():
    html = _html()
    js = _js()

    assert "<th>Time (UTC)</th>" in html

    start = js.index(
        "function tradingOrderTime("
    )

    end = js.index(
        "function tradingResetPersistentOrders()",
        start,
    )

    block = js[start:end]

    for token in (
        "getUTCFullYear()",
        "getUTCMonth()",
        "getUTCDate()",
        "getUTCHours()",
        "getUTCMinutes()",
        "getUTCSeconds()",
        " UTC",
    ):
        assert token in block

    assert "toLocaleString(" not in block


def test_trading_refinement_markers_present_once():
    css = _css()

    assert (
        css.count(
            "/* 3J13 Trading final refinement v2 */"
        )
        == 1
    )

    assert (
        css.count(
            "/* End 3J13 Trading final refinement v2 */"
        )
        == 1
    )


def test_trading_pair_and_account_have_balanced_widths():
    css = _css()

    assert (
        "grid-template-columns:\n"
        "    220px\n"
        "    230px\n"
        "    auto\n"
        "    auto;"
        in css
    )

    pair_start = css.index(
        "#tab-trading\n"
        ".trading-pair-search input {"
    )

    pair_end = css.index(
        "}",
        pair_start,
    )

    pair_rule = css[
        pair_start:pair_end
    ]

    assert "font-size: .78rem;" in pair_rule
    assert "font-weight: 560;" in pair_rule


def test_global_account_selector_is_hidden_on_trading_only():
    html = _html()

    app = Path(
        "frontend/app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="globalAccountSelector"'
        in html
    )

    assert (
        "target !== 'trading'"
        in app
    )

    assert (
        "globalAccountSelector?.classList.toggle("
        in app
    )

    assert (
        "globalAccountSelector?.setAttribute("
        in app
    )


def test_hiding_global_selector_does_not_clear_scope_state():
    app = Path(
        "frontend/app.js"
    ).read_text(
        encoding="utf-8"
    )

    start = app.index(
        "const globalAccountSelector = $("
    )

    end = app.index(
        "$$('.nav-item').forEach",
        start,
    )

    block = app[start:end]

    assert "state.selectedAccount =" not in block
    assert "accountSelector').value" not in block


def test_trading_scope_width_refinement_markers_once():
    css = _css()

    assert (
        css.count(
            "/* 3J13 Trading scope/width refinement v3 */"
        )
        == 1
    )

    assert (
        css.count(
            "/* End 3J13 Trading scope/width refinement v3 */"
        )
        == 1
    )


def test_order_book_is_sticky_on_desktop():
    limit_css = _limit_css()

    assert (
        "/* 3J13 Trading sticky market-side panel v1 */"
        in limit_css
    )

    desktop_start = limit_css.index(
        "@media (min-width: 901px)"
    )

    desktop_end = limit_css.index(
        "@media (max-width: 900px)",
        desktop_start,
    )

    desktop = limit_css[
        desktop_start:desktop_end
    ]

    for token in (
        ".trading-book-panel",
        "position: sticky;",
        "top: 16px;",
        "align-self: start;",
        "height: fit-content;",
        "max-height:",
        "calc(100vh - 32px);",
        "overflow-y: auto;",
    ):
        assert token in desktop


def test_sticky_book_returns_to_normal_flow_on_small_screens():
    limit_css = _limit_css()

    mobile_start = limit_css.index(
        "@media (max-width: 900px)",
        limit_css.index(
            "/* 3J13 Trading sticky market-side panel v1 */"
        ),
    )

    mobile_end = limit_css.index(
        "/* End 3J13 Trading sticky market-side panel v1 */",
        mobile_start,
    )

    mobile = limit_css[
        mobile_start:mobile_end
    ]

    for token in (
        ".trading-book-panel",
        "position: static;",
        "align-self: stretch;",
        "max-height: none;",
        "overflow:",
        "visible;",
    ):
        assert token in mobile


def test_sticky_book_uses_css_only():
    app = Path(
        "frontend/app.js"
    ).read_text(
        encoding="utf-8"
    )

    trading = _js()

    assert "IntersectionObserver" not in trading
    assert "scrollY" not in trading
    assert "scrollTo(" not in trading

    # No Trading-specific scroll implementation
    # was introduced into the global app either.
    assert "stickyTradingBook" not in app


def test_sticky_book_markers_present_once():
    limit_css = _limit_css()

    assert (
        limit_css.count(
            "/* 3J13 Trading sticky market-side panel v1 */"
        )
        == 1
    )

    assert (
        limit_css.count(
            "/* End 3J13 Trading sticky market-side panel v1 */"
        )
        == 1
    )
