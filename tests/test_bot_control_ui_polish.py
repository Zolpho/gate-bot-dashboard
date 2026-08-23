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
    "frontend/bot-control.css"
).read_text(
    encoding="utf-8"
)


def test_global_account_scope_is_hidden_on_bot_control():
    assert "target !== 'trading'" in APP
    assert "target !== 'bot-control'" in APP


def test_single_bot_control_account_has_static_surface():
    assert 'id="spotGridAccount"' in HTML
    assert 'name="account_id"' in HTML
    assert 'id="spotGridAccountStatic"' in HTML

    assert "accounts.length === 1" in APP
    assert "singleAccount" in APP


def test_bot_control_live_state_is_compact():
    assert "badge.textContent = 'LIVE'" in APP
    assert "detail.textContent = 'Creation armed'" in APP

    assert "LIVE creation enabled" not in APP

    assert (
        'id="botControlCreateStateDetail"'
        in HTML
    )


def test_activity_defaults_to_ten_rows():
    assert "limit: 10" in APP

    assert (
        'id="botControlActivityPageSize"'
        in HTML
    )

    assert (
        '<option value="10" selected>10</option>'
        in HTML
    )

    assert '<option value="25">25</option>' in HTML
    assert '<option value="50">50</option>' in HTML


def test_activity_uses_server_backed_pagination():
    assert (
        "`?limit=${encodeURIComponent(requestedLimit)}`"
        in APP
    )

    assert (
        "`&offset=${encodeURIComponent(requestedOffset)}`"
        in APP
    )

    assert "result.total" in APP
    assert "result.has_previous" in APP
    assert "result.has_next" in APP


def test_activity_has_page_navigation():
    for element_id in (
        "botControlActivityPrevious",
        "botControlActivityNext",
        "botControlActivityPage",
    ):
        assert f'id="{element_id}"' in HTML

    assert "$('#botControlActivityPrevious')" in APP
    assert "$('#botControlActivityNext')" in APP


def test_activity_time_is_24_hour_utc():
    table_start = HTML.index(
        '<table class="bot-control-activity-table">'
    )

    table_end = HTML.index(
        '</table>',
        table_start,
    )

    table = HTML[
        table_start:table_end
    ]

    assert "<th>Time (UTC)</th>" in table

    assert (
        "function formatBotControlUtcDate"
        in APP
    )

    for token in (
        "getUTCFullYear()",
        "getUTCMonth()",
        "getUTCDate()",
        "getUTCHours()",
        "getUTCMinutes()",
        "getUTCSeconds()",
    ):
        assert token in APP


def test_zero_attention_state_is_compact():
    assert (
        "bot-control-attention-clear"
        in APP
    )

    assert "All clear" in APP

    assert (
        ".bot-control-attention-panel.is-clear"
        in CSS
    )


def test_preflight_panel_is_compact():
    assert (
        "#tab-bot-control"
        in CSS
    )

    assert (
        ".bot-control-review-panel"
        in CSS
    )

    assert "align-self: start;" in CSS

    for token in (
        ".bot-control-review-status",
        ".bot-control-review-grid",
        ".bot-control-review-item",
        ".bot-control-validation",
        ".bot-control-payload",
    ):
        assert token in CSS


def test_bot_control_asset_versions_are_bumped():
    assert (
        "./bot-control.css?"
        "v=20260823-bot-control-polish-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260823-bot-control-polish-v1"
        in HTML
    )


def test_activity_exports_remain_independent():
    assert 'id="exportBotControlJson"' in HTML
    assert 'id="exportBotControlCsv"' in HTML

    assert (
        "downloadBotControlAuditExport"
        in APP
    )


def test_activity_pagination_loader_is_get_only():
    start = APP.index(
        "async function loadBotControlActivity("
    )

    end = APP.index(
        "\n\nfunction reconciliationLabel(",
        start,
    )

    loader = APP[
        start:end
    ]

    assert "/api/bot-control/requests" in loader

    for forbidden in (
        "method:",
        "POST",
        "DELETE",
        "PATCH",
    ):
        assert forbidden not in loader
