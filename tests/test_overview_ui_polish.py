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
        "formatAlertMessage(event.message)"
        in app
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
