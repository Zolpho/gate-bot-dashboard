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


def test_alerts_html_uses_incident_sections():
    for token in (
        "<h2>Active incidents</h2>",
        'id="alertIncidents"',
        'id="activeIncidentCount"',
        "<h3>History</h3>",
        'id="alertIncidentHistory"',
        'id="incidentHistoryCount"',
    ):
        assert token in HTML

    assert "<h2>Alert events</h2>" not in HTML
    assert 'id="alertEvents"' not in HTML
    assert 'id="unackedOnly"' not in HTML


def test_alerts_use_durable_incident_state():
    assert "alertIncidents: []" in APP
    assert "alertIncidentHistory: []" in APP

    start = APP.index(
        "function renderAlerts()"
    )

    end = APP.index(
        "\nfunction renderSystem()",
        start,
    )

    renderer = APP[start:end]

    assert "state.alertIncidents" in renderer
    assert ".map(alertIncidentHtml)" in renderer

    assert (
        "state.alertIncidentHistory"
        in renderer
    )

    assert (
        ".map(alertIncidentHistoryHtml)"
        in renderer
    )

    assert "state.alertEvents" not in renderer


def test_active_incident_renderer_has_lifecycle_values():
    start = APP.index(
        "function alertIncidentHtml(incident)"
    )

    end = APP.index(
        "\n\nfunction alertIncidentHistoryHtml",
        start,
    )

    renderer = APP[start:end]

    for token in (
        "incident.rule_name",
        "incident.trigger_value",
        "incident.current_value",
        "incident.worst_value",
        "incident.opened_at",
        "incident.last_observed_at",
        "Acknowledged",
        "Open",
    ):
        assert token in renderer


def test_history_renderer_uses_recovered_lifecycle():
    start = APP.index(
        "function alertIncidentHistoryHtml(incident)"
    )

    end = APP.index(
        "\nfunction renderAlerts()",
        start,
    )

    renderer = APP[start:end]

    for token in (
        "incident.opened_at",
        "incident.recovered_at",
        "incident.worst_value",
        "Recovered",
        "Not acknowledged",
    ):
        assert token in renderer


def test_incident_acknowledgement_hook():
    assert (
        'class="text-button ack-incident"'
        in APP
    )

    assert (
        'data-incident-id="${incident.id}"'
        in APP
    )

    assert (
        "async function acknowledgeIncident(id)"
        in APP
    )

    assert (
        "/api/alerts/incidents/"
        "${id}/acknowledge"
        in APP
    )

    assert "Incident acknowledged." in APP


def test_overview_alert_renderer_remains_separate():
    start = APP.index(
        "function renderOverviewAlerts()"
    )

    end = APP.index(
        "\nfunction eventHtml(event)",
        start,
    )

    overview = APP[start:end]

    assert (
        "state.alertEvents.slice(0,4)"
        in overview
    )

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

    assert (
        'class="text-button ack-event"'
        in event_renderer
    )


def test_load_core_keeps_events_for_overview_and_incidents_for_alerts():
    start = APP.index(
        "async function loadCore()"
    )

    end = APP.index(
        "\nasync function syncNow()",
        start,
    )

    loader = APP[start:end]

    assert (
        "api(scopedPath('/api/alerts/events'"
        in loader
    )

    assert (
        "api(scopedPath('/api/alerts/incidents'"
        in loader
    )

    assert "state: 'open'" in loader
    assert "state: 'history'" in loader

    assert (
        "state.alertEvents = eventData.items"
        in loader
    )

    assert (
        "state.alertIncidents = "
        "openIncidentData.items"
        in loader
    )

    assert (
        "state.alertIncidentHistory = "
        "historyIncidentData.items"
        in loader
    )

    assert "unacknowledged_only" not in loader


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


def test_alert_rule_metrics_remain_human_readable():
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


def test_existing_rule_mutation_hooks_preserved():
    assert 'class="rule-toggle"' in APP

    assert (
        'class="text-button delete-rule"'
        in APP
    )

    assert (
        'data-rule-id="${rule.id}"'
        in APP
    )


def test_incident_visual_states_exist():
    for token in (
        ".alerts-incident-status.open",
        ".alerts-incident-status.acknowledged",
        ".alerts-incident-status.recovered",
        ".alerts-incident-values",
        ".alerts-history-section",
        ".alerts-history-item",
    ):
        assert token in CSS


def test_alerts_assets_are_versioned():
    assert (
        "./alerts.css?"
        "v=20260823-alert-incidents-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260823-alert-incidents-v1"
        in HTML
    )

    assert (
        "/* 3J15 Alerts incident UI v1 */"
        in CSS
    )
