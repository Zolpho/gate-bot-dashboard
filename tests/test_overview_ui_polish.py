from pathlib import Path


def _app():
    return Path(
        "frontend/app.js"
    ).read_text(
        encoding="utf-8"
    )


def _css():
    return Path(
        "frontend/styles.css"
    ).read_text(
        encoding="utf-8"
    )


def _html():
    return Path(
        "frontend/index.html"
    ).read_text(
        encoding="utf-8"
    )


def test_current_value_metric_is_neutral():
    app = _app()

    assert (
        "setMetric("
        "'#currentValue', "
        "totals.current_value, "
        "fmtMoney, "
        "null"
        ");"
        in app
    )

    assert (
        "setMetric("
        "'#currentValue', "
        "totals.current_value, "
        "fmtMoney, "
        "totals.pnl"
        ");"
        not in app
    )


def test_performance_leaders_are_structured():
    app = _app()

    for token in (
        'class="leader-copy"',
        'class="leader-name"',
        'class="leader-meta"',
        'class="leader-result ${valueClass(rate)}"',
    ):
        assert token in app


def test_alert_display_formatter_exists():
    app = _app()

    assert (
        "function formatAlertMessage(message)"
        in app
    )

    assert (
        "function overviewIncidentHtml(incident)"
        in app
    )

    assert (
        "state.alertIncidents.slice(0, 4)"
        in app
    )

    assert (
        "No active incidents."
        in app
    )

    assert (
        "formatAlertMessage(event.message)"
        not in app
    )

    assert "minimumFractionDigits: 2" in app
    assert "'>=': '≥'" in app
    assert "'<=': '≤'" in app


def test_alert_formatter_does_not_mutate_state():
    app = _app()

    start = app.index(
        "function formatAlertMessage(message)"
    )

    end = app.index(
        "function renderOverviewAlerts()",
        start,
    )

    helper = app[start:end]

    assert "state." not in helper
    assert "fetch(" not in helper
    assert "apiFetch(" not in helper


def test_overview_grid_does_not_stretch_lower_cards():
    css = _css()

    assert (
        "#tab-overview .dashboard-grid.equal"
        in css
    )

    assert "align-items: start;" in css


def test_leader_visual_structure_present():
    css = _css()

    for token in (
        "#tab-overview .leader-copy",
        "#tab-overview .leader-name",
        "#tab-overview .leader-meta",
        "#tab-overview .leader-result",
    ):
        assert token in css


def test_current_value_css_is_neutral():
    css = _css()

    assert (
        "#tab-overview #currentValue"
        in css
    )

    assert (
        "color: var(--text) !important;"
        in css
    )


def test_overview_core_assets_remain_versioned():
    html = _html()

    assert "./styles.css?v=" in html
    assert "./app.js?v=" in html

    assert 'href="./styles.css"' not in html
    assert 'src="./app.js"' not in html


def test_overview_polish_markers_present_once():
    css = _css()

    assert (
        css.count(
            "/* 3J13 Overview-specific polish v1 */"
        )
        == 1
    )

    assert (
        css.count(
            "/* End 3J13 Overview-specific polish v1 */"
        )
        == 1
    )


def _aurora_overview_css():
    return Path(
        "frontend/aurora-overview.css"
    ).read_text(
        encoding="utf-8"
    )


def test_overview_chart_has_interface_local_series_colors():
    app = _app()
    css = _aurora_overview_css()

    assert (
        "--overview-current-value-color"
        in app
    )

    assert (
        "--overview-total-pnl-color"
        in app
    )

    assert (
        "color: currentValueColor"
        in app
    )

    assert (
        "color: totalPnlColor"
        in app
    )

    assert (
        "--overview-current-value-color:"
        in css
    )

    assert (
        "--overview-total-pnl-color:"
        in css
    )

    assert "#58f0bd" in css
    assert "#63a6ff" in css


def test_aurora_overview_legend_and_tooltip_match_series():
    css = _aurora_overview_css()

    assert (
        "#tab-overview .legend-value,"
        in css
    )

    assert (
        "#tab-overview .tooltip-dot.value"
        in css
    )

    assert (
        "#tab-overview .legend-pnl,"
        in css
    )

    assert (
        "#tab-overview .tooltip-dot.pnl"
        in css
    )


def test_overview_series_contrast_assets_are_cache_busted():
    html = _html()

    marker = (
        "m412a="
        "20261002-overview-series-contrast-v1"
    )

    # Aurora Overview CSS + shared app.js.
    assert html.count(marker) == 2


def test_aurora_premium_chart_tokens_present():
    css = _aurora_overview_css()

    for token in (
        "--overview-premium-chart: 1;",
        "--overview-current-value-fill:",
        "--overview-current-value-line-width:",
        "--overview-total-pnl-line-width:",
        "--overview-current-value-shadow:",
        "--overview-chart-grid-color:",
        "--overview-chart-axis-color:",
        "--overview-chart-zero-color:",
    ):
        assert token in css


def test_premium_chart_renderer_is_opt_in():
    app = _app()

    for token in (
        "const premiumChart = (",
        "transparentBackground: premiumChart",
        "rightZeroLine: premiumChart",
        "axisLabelAlpha: (",
        "item.lineWidth",
        "item.shadowBlur",
        "item.rounded",
        "options.xAxisLabel === false",
    ):
        assert token in app


def test_portfolio_hover_markers_exist():
    html = _html()
    app = _app()

    for token in (
        'id="portfolioChartValuePoint"',
        'id="portfolioChartPnlPoint"',
        'class="chart-hover-point value hidden"',
        'class="chart-hover-point pnl hidden"',
    ):
        assert token in html

    for token in (
        "const valuePoint = $('#portfolioChartValuePoint');",
        "const pnlPoint = $('#portfolioChartPnlPoint');",
        "positionHoverPoint(",
        "meta.yFor(",
    ):
        assert token in app


def test_aurora_premium_chart_css_is_scoped():
    css = _aurora_overview_css()

    assert (
        "M4.12G — PREMIUM OVERVIEW CHART"
        in css
    )

    assert (
        "/* End M4.12G Premium Overview chart */"
        in css
    )

    for token in (
        "#tab-overview .chart-wrap",
        "#tab-overview .chart-crosshair",
        "#tab-overview .chart-hover-point",
        "#tab-overview .chart-tooltip",
        "#tab-overview .chart-legend",
    ):
        assert token in css


def test_premium_overview_assets_are_cache_busted():
    html = _html()

    marker = (
        "m412g="
        "20261002-premium-overview-chart-v1"
    )

    assert html.count(
        marker
    ) == 2

    assert (
        "./aurora-overview.css?"
        in html
    )

    assert (
        "./app.js?"
        in html
    )


def test_aurora_premium_final_polish():
    css = _aurora_overview_css()
    html = _html()

    assert (
        "--overview-current-value-shadow:"
        in css
    )

    assert (
        "rgba(88, 240, 189, 0.09);"
        in css
    )

    assert (
        "--overview-chart-zero-color:"
        in css
    )

    assert (
        "rgba(99, 166, 255, 0.18);"
        in css
    )

    marker = (
        "m412i="
        "20261002-final-premium-polish-v1"
    )

    # CSS-only presentation adjustment.
    assert html.count(marker) == 1

    assert (
        "./aurora-overview.css?"
        in html
    )
