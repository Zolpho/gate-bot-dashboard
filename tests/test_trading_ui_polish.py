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
        "./trading.css?v=20260823-trading-polish-v1"
        in html
    )

    assert (
        "./trading-limit.css?v=20260823-trading-polish-v1"
        in html
    )

    assert (
        "./trading.js?v=20260823-trading-polish-v1"
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
