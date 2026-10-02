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


def _function(
    name: str,
    next_name: str,
) -> str:
    start = APP.index(
        f"function {name}("
    )

    end = APP.index(
        f"\n\nfunction {next_name}(",
        start,
    )

    return APP[
        start:end
    ]


def test_bot_detail_has_dedicated_grid_earnings_graph():
    for token in (
        'id="gridEarningsPanel"',
        "Cumulative realized grid earnings",
        'id="gridEarningsSummary"',
        'id="gridEarningsEmpty"',
        'id="gridEarningsChartWrap"',
        'id="botGridEarningsChart"',
    ):
        assert token in HTML


def test_grid_earnings_series_is_limited_to_grid_strategies():
    block = _function(
        "gridEarningsHistory",
        "drawGridEarningsChart",
    )

    assert (
        "strategyType !== 'spot_grid'"
        in block
    )

    assert (
        "strategyType !== 'infinite_grid'"
        in block
    )


def test_grid_earnings_uses_only_gate_grid_profit():
    block = _function(
        "gridEarningsHistory",
        "drawGridEarningsChart",
    )

    assert (
        "snapshot.grid_profit"
        in block
    )

    assert "snapshot.total_profit" not in block
    assert "snapshot.realized_pnl" not in block
    assert "snapshot.floating_pnl" not in block


def test_infinity_empty_state_does_not_fake_grid_earnings():
    block = _function(
        "drawGridEarningsChart",
        "drawBotChart",
    )

    assert (
        "Gate currently provides no grid_profit "
        in block
    )

    assert (
        "Total profit is not substituted"
        in block
    )


def test_grid_series_is_collapsed_to_step_changes():
    block = _function(
        "gridEarningsHistory",
        "drawGridEarningsChart",
    )

    assert (
        "if (value === previousValue)"
        in block
    )

    assert (
        "cumulative_grid_earnings:"
        in block
    )

    assert (
        "previousValue"
        in block
    )


def test_grid_graph_uses_single_quote_axis():
    block = _function(
        "drawGridEarningsChart",
        "drawBotChart",
    )

    assert (
        "showRightAxis: false"
        in block
    )

    assert (
        "Grid earnings (${"
        in block
    )


def test_existing_bot_chart_also_draws_grid_earnings():
    start = APP.index(
        "function drawBotChart("
    )

    end = APP.index(
        "\n\nasync function stopCurrentBot(",
        start,
    )

    block = APP[
        start:end
    ]

    assert (
        "drawGridEarningsChart();"
        in block
    )


def test_m411b_cache_bust_is_scoped_to_modified_assets():
    marker = (
        "m411b="
        "20261002-grid-earnings-v1"
    )

    assert HTML.count(
        marker
    ) == 2
