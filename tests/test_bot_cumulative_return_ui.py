from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]

APP = (
    ROOT
    / "frontend"
    / "app.js"
).read_text(
    encoding="utf-8"
)

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
    / "aurora-bot-details.css"
).read_text(
    encoding="utf-8"
)


def _function(
    name: str,
    next_name: str,
) -> str:
    start = APP.index(
        f"function {name}("
    )

    boundaries = (
        f"\n\nfunction {next_name}(",
        f"\n\nasync function {next_name}(",
    )

    matches = [
        APP.find(
            boundary,
            start,
        )
        for boundary in boundaries
    ]

    matches = [
        match
        for match in matches
        if match >= 0
    ]

    if not matches:
        raise AssertionError(
            f"Unable to find function boundary "
            f"after {name}: {next_name}"
        )

    end = min(
        matches
    )

    return APP[
        start:end
    ]


def test_bot_detail_has_gate_style_cumulative_return_graph():
    for token in (
        'id="cumulativeReturnPanel"',
        "Cumulative Return",
        'id="cumulativeReturnSummary"',
        'id="cumulativeReturnEmpty"',
        'id="cumulativeReturnChartWrap"',
        'id="botCumulativeReturnChart"',
    ):
        assert token in HTML

    assert (
        "Cumulative realized grid earnings"
        not in HTML
    )


def test_cumulative_return_supports_spot_and_infinity():
    block = _function(
        "cumulativeReturnHistory",
        "drawCumulativeReturnChart",
    )

    assert (
        "strategyType !== 'spot_grid'"
        in block
    )

    assert (
        "strategyType !== 'infinite_grid'"
        in block
    )


def test_cumulative_return_uses_total_profit_only():
    block = _function(
        "cumulativeReturnHistory",
        "drawCumulativeReturnChart",
    )

    assert (
        "snapshot.total_profit"
        in block
    )

    assert "snapshot.grid_profit" not in block
    assert "snapshot.realized_pnl" not in block
    assert "snapshot.floating_pnl" not in block


def test_dialog_detail_request_skips_unused_full_history_analytics():
    assert (
        "/api/bots/${botId}?include_analytics=false"
        in APP
    )


def test_dialog_open_uses_only_fast_detail_before_async_chart():
    start = APP.index(
        "async function openBot("
    )

    end = APP.index(
        "\n\nfunction renderBotDialog(",
        start,
    )

    block = APP[
        start:end
    ]

    assert (
        "/api/bots/${botId}?include_analytics=false"
        in block
    )

    assert (
        "/history?hours="
        not in block
    )

    assert (
        "/pnl-history"
        not in block
    )

    assert (
        "void loadCumulativeReturnHistory("
        in block
    )

    assert (
        "Promise.all(["
        not in block
    )


def test_lightweight_pnl_history_is_bounded_for_all_grid_bots():
    for token in (
        "CUMULATIVE_RETURN_HOURS",
        "24 * 365",
        "CUMULATIVE_RETURN_MAX_POINTS",
        "1600",
        "/pnl-history",
        "max_points=${CUMULATIVE_RETURN_MAX_POINTS}",
    ):
        assert token in APP


def test_cumulative_history_has_short_per_bot_cache():
    for token in (
        "CUMULATIVE_RETURN_CACHE_MS",
        "60 * 1000",
        "botCumulativeHistoryCache",
        "botCumulativeHistoryRequests",
        "cumulativeReturnCacheEntry",
        "fetchCumulativeReturnHistory",
    ):
        assert token in APP


def test_cumulative_chart_has_loading_state():
    block = _function(
        "drawCumulativeReturnChart",
        "stopCurrentBot",
    )

    for token in (
        "state.currentBotCumulativeLoading",
        "Loading cumulative return…",
        "Loading up to 1 year of ",
        "state.currentBotCumulativeError",
    ):
        assert token in block

    assert (
        ".cumulative-return-empty.loading::before"
        in CSS
    )

    assert (
        "aurora-cumulative-return-spin"
        in CSS
    )


def test_cumulative_graph_reports_downsampling_counts():
    block = _function(
        "drawCumulativeReturnChart",
        "stopCurrentBot",
    )

    for token in (
        "state.currentBotCumulativeMeta",
        "meta.sourcePoints",
        "meta.plottedPoints",
        "snapshots · ${",
        "plotted",
    ):
        assert token in block


def test_series_renderer_supports_zero_split_colors():
    block = _function(
        "drawSeriesChart",
        "bindPortfolioChartTooltip",
    )

    for token in (
        "item.zeroSplit",
        "item.positiveFill",
        "item.negativeFill",
        "item.positiveColor",
        "item.negativeColor",
    ):
        assert token in block


def test_cumulative_return_graph_matches_gate_semantics():
    block = _function(
        "drawCumulativeReturnChart",
        "stopCurrentBot",
    )

    for token in (
        "cumulative_return",
        "--positive",
        "--negative",
        "zeroSplit:",
        "positiveFill:",
        "negativeFill:",
        "leftIncludeZero: true",
        "showRightAxis: false",
        "Latest Total PnL",
    ):
        assert token in block


def test_old_grid_earnings_feature_is_removed():
    combined = APP + HTML

    for token in (
        "gridEarningsHistory",
        "drawGridEarningsChart",
        "gridEarningsPanel",
        "botGridEarningsChart",
        "cumulative_grid_earnings",
    ):
        assert token not in combined




def test_cumulative_return_is_only_bot_detail_performance_chart():
    combined = APP + HTML

    for token in (
        "Equity and drawdown",
        'id="drawdownSummary"',
        'id="botHistoryRange"',
        'id="botChart"',
        "currentBotHistory",
        "function drawBotChart(",
    ):
        assert token not in combined

    assert (
        "drawCumulativeReturnChart();"
        in APP
    )


def test_bot_detail_no_longer_exposes_range_dependent_drawdown():
    start = APP.index(
        "function renderBotDialog("
    )

    end = APP.index(
        "\n\nfunction updateBotAdminControls(",
        start,
    )

    block = APP[
        start:end
    ]

    assert (
        "Max drawdown"
        not in block
    )

    assert (
        "history.analytics"
        not in block
    )


def test_m411d_cache_busts_cover_current_assets():
    r3_marker = (
        "m411d3="
        "20261002-cumulative-return-fast-v1"
    )

    r4_marker = (
        "m411d4="
        "20261002-cumulative-return-only-v1"
    )

    assert HTML.count(
        r3_marker
    ) == 2

    assert HTML.count(
        r4_marker
    ) == 1
