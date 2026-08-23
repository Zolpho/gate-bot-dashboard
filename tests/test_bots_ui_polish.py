from pathlib import Path


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


def _app():
    return Path(
        "frontend/app.js"
    ).read_text(
        encoding="utf-8"
    )


def test_bots_polish_markers_present_once():
    css = _css()

    assert (
        css.count(
            "/* 3J13 Bots-specific polish v1 */"
        )
        == 1
    )

    assert (
        css.count(
            "/* End 3J13 Bots-specific polish v1 */"
        )
        == 1
    )


def test_bots_toolbar_is_page_scoped():
    css = _css()

    for token in (
        "#tab-bots .toolbar-panel",
        "#tab-bots .filters",
        "#tab-bots #botSearch",
        "#tab-bots #exportCsv",
    ):
        assert token in css


def test_active_bot_numeric_columns_are_aligned():
    css = _css()

    assert (
        "#tab-bots .table-panel"
        in css
    )

    assert (
        "font-variant-numeric:"
        in css
    )

    assert (
        "text-align: right;"
        in css
    )


def test_bot_actions_are_visually_secondary():
    css = _css()

    for token in (
        "#tab-bots .bot-row-actions",
        "#tab-bots .bot-row-actions\n.row-button",
        "#tab-bots .bot-archive-action",
        "#tab-bots .bot-restore-action",
    ):
        assert token in css


def test_archived_bots_have_secondary_hierarchy():
    css = _css()

    for token in (
        "#tab-bots .archived-bots-panel",
        "#tab-bots .archived-bots-summary",
        "#tab-bots #archivedBotsCount",
        "#tab-bots .archived-bots-content",
    ):
        assert token in css


def test_archived_numeric_columns_are_aligned():
    css = _css()

    assert (
        "#tab-bots .archived-bots-content"
        in css
    )

    assert (
        "min-width: 1060px;"
        in css
    )


def test_bots_responsive_rules_present():
    css = _css()

    assert (
        "@media (max-width: 1100px)"
        in css
    )

    assert (
        "@media (max-width: 560px)"
        in css
    )


def test_bots_core_assets_remain_versioned():
    html = _html()

    assert "./styles.css?v=" in html
    assert "./app.js?v=" in html

    assert 'href="./styles.css"' not in html
    assert 'src="./app.js"' not in html


def test_strategy_names_are_not_rewritten():
    app = _app()

    assert (
        "${escapeHtml("
        in app
    )

    assert "bot.strategy_name" in app

    # UI polish must not introduce a strategy-name
    # normalizer that silently changes Gate/local data.
    assert "normalizeStrategyName" not in app
    assert "formatStrategyName" not in app
