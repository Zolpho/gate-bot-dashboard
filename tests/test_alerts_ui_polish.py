from pathlib import Path


HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)

APP = Path(
    "frontend/app.js"
).read_text(
    encoding="utf-8"
)

CSS = Path(
    "frontend/alerts.css"
).read_text(
    encoding="utf-8"
)


def test_alerts_panels_use_natural_height():
    assert (
        'class="dashboard-grid equal alerts-grid"'
        in HTML
    )

    assert ".alerts-grid" in CSS
    assert "align-items: start;" in CSS

    assert ".alerts-panel" in CSS
    assert "align-self: start;" in CSS


def test_alerts_have_dedicated_event_renderer():
    assert (
        "function alertEventHtml(event)"
        in APP
    )

    start = APP.index(
        "function renderAlerts()"
    )

    end = APP.index(
        "\nfunction renderSystem()",
        start,
    )

    renderer = APP[start:end]

    assert ".map(alertEventHtml)" in renderer


def test_overview_alert_renderer_remains_separate():
    start = APP.index(
        "function renderOverviewAlerts()"
    )

    end = APP.index(
        "\nfunction eventHtml(event)",
        start,
    )

    overview = APP[start:end]

    assert ".map(eventHtml)" in overview

    event_start = APP.index(
        "function eventHtml(event)"
    )

    event_end = APP.index(
        "\nfunction formatAlertUtcDate",
        event_start,
    )

    event_renderer = APP[
        event_start:event_end
    ]

    assert (
        "fmtDate(event.triggered_at)"
        in event_renderer
    )


def test_alerts_use_explicit_utc_timestamps():
    start = APP.index(
        "function formatAlertUtcDate(value)"
    )

    end = APP.index(
        "\n\nfunction alertMetricLabel(",
        start,
    )

    formatter = APP[start:end]

    for token in (
        "getUTCFullYear()",
        "getUTCMonth()",
        "getUTCDate()",
        "getUTCHours()",
        "getUTCMinutes()",
        " UTC",
    ):
        assert token in formatter

    assert "toLocaleString" not in formatter
    assert "toLocaleTimeString" not in formatter


def test_alert_rule_metrics_are_human_readable():
    for label in (
        "Drawdown %",
        "PnL USDT",
        "ROI %",
        "Floating PnL",
        "Current value",
        "Liquidation distance %",
        "Data age minutes",
    ):
        assert label in APP

    assert (
        "function alertOperatorLabel(operator)"
        in APP
    )

    assert "'≥'" in APP
    assert "'≤'" in APP


def test_existing_rule_mutation_hooks_are_preserved():
    assert 'class="rule-toggle"' in APP

    assert (
        'class="text-button delete-rule"'
        in APP
    )

    assert (
        'data-rule-id="${rule.id}"'
        in APP
    )


def test_existing_acknowledge_hook_is_preserved():
    assert (
        'class="text-button ack-event"'
        in APP
    )

    assert (
        'data-event-id="${event.id}"'
        in APP
    )

    assert "Acknowledge" in APP


def test_alert_event_states_are_consistent():
    assert "Acknowledged" in APP
    assert "Open" in APP

    assert (
        ".alerts-event-status.open"
        in CSS
    )

    assert (
        ".alerts-event-status.acknowledged"
        in CSS
    )


def test_unacknowledged_filter_semantics_remain():
    assert 'id="unackedOnly"' in HTML

    assert (
        "$('#unackedOnly').addEventListener("
        "'change', loadCore"
        in APP
    )

    assert (
        "unacknowledged_only: "
        "$('#unackedOnly').checked"
        in APP
    )


def test_alert_account_scoping_remains():
    assert (
        "api(scopedPath('/api/alerts/events'"
        in APP
    )

    assert (
        "api('/api/alerts/rules')"
        in APP
    )


def test_alerts_stylesheet_is_versioned():
    assert (
        "./alerts.css?"
        "v=20260823-alerts-polish-v1"
        in HTML
    )

    assert (
        "/* 3J14 Alerts-specific polish v1 */"
        in CSS
    )


def test_app_asset_is_versioned_for_alerts():
    assert (
        "./app.js?"
        "v=20260823-alerts-polish-v1"
        in HTML
    )
