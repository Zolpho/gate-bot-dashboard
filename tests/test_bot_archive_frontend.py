from pathlib import Path


def _app():
    return Path(
        "frontend/app.js"
    ).read_text(
        encoding="utf-8"
    )


def test_main_and_archive_lists_are_separate():
    app = _app()

    assert (
        "filteredArchivedBots: []"
        in app
    )

    assert (
        "function botIsArchived(bot)"
        in app
    )

    assert (
        "state.filteredBots = matches.filter("
        in app
    )

    assert (
        "state.filteredArchivedBots ="
        in app
    )

    assert (
        "renderArchivedBots();"
        in app
    )


def test_only_stopped_owned_bots_get_archive_action():
    app = _app()

    start = app.index(
        "function renderBots()"
    )

    end = app.index(
        "function renderArchivedBots()",
        start,
    )

    block = app[start:end]

    assert (
        "=== 'stopped'"
        in block
    )

    assert (
        "canManageAccount("
        in block
    )

    assert (
        "data-archive-bot-id"
        in block
    )


def test_archived_restore_is_owner_authorized():
    app = _app()

    start = app.index(
        "function renderArchivedBots()"
    )

    end = app.index(
        "async function archiveBot(",
        start,
    )

    block = app[start:end]

    assert (
        "canManageAccount("
        in block
    )

    assert (
        "data-restore-bot-id"
        in block
    )


def test_archive_and_restore_use_local_api_only():
    app = _app()

    assert (
        "`/api/bots/${bot.id}/archive`"
        in app
    )

    assert (
        "`/api/bots/${bot.id}/restore`"
        in app
    )

    assert (
        "gate_write_performed"
        in app
    )

    assert (
        "No Gate request was sent."
        in app
    )


def test_archive_requires_confirmation():
    app = _app()

    start = app.index(
        "async function archiveBot("
    )

    end = app.index(
        "async function restoreBot(",
        start,
    )

    block = app[start:end]

    assert "confirm(" in block

    assert (
        "Nothing will "
        in block
    )

    assert (
        "+ 'be sent to Gate.'"
        in block
    )


def test_alert_targets_exclude_archived_bots():
    app = _app()

    assert (
        "!botIsArchived(bot)"
        in app
    )


def test_archived_html_section_exists():
    html = Path(
        "frontend/index.html"
    ).read_text(
        encoding="utf-8"
    )

    for token in (
        'id="archivedBotsSection"',
        'id="archivedBotsCount"',
        'id="archivedBotsTableBody"',
        'id="archivedBotsEmpty"',
    ):
        assert token in html

    assert "Archived bots" in html

    assert (
        "Archiving"
        in html
    )

    assert (
        "does not change anything on Gate."
        in html
    )


def test_archive_css_exists():
    css = Path(
        "frontend/styles.css"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        ".archived-bots-panel"
        in css
    )

    assert (
        ".archived-bots-summary"
        in css
    )

    assert (
        ".bot-row-actions"
        in css
    )


def test_archive_assets_remain_versioned():
    html = Path(
        "frontend/index.html"
    ).read_text(
        encoding="utf-8"
    )

    # Archive does not own future global CSS/JS release
    # versions. Preserve the durable browser-cache safety
    # contract instead: both core assets remain versioned.
    assert "./styles.css?v=" in html
    assert "./app.js?v=" in html

    assert 'href="./styles.css"' not in html
    assert 'src="./app.js"' not in html


def test_archive_ui_updates_before_background_refresh():
    app = _app()

    start = app.index(
        "async function archiveBot("
    )

    end = app.index(
        "async function restoreBot(",
        start,
    )

    block = app[start:end]

    assert (
        "state.bots = state.bots.map("
        in block
    )

    assert (
        "...result.bot"
        in block
    )

    assert (
        "applyBotFilters();"
        in block
    )

    assert (
        "void loadCore();"
        in block
    )

    toast = block.index(
        "Bot archived locally."
    )

    refresh = block.index(
        "void loadCore();"
    )

    assert toast < refresh


def test_restore_ui_updates_before_background_refresh():
    app = _app()

    start = app.index(
        "async function restoreBot("
    )

    block = app[start:]

    assert (
        "state.bots = state.bots.map("
        in block
    )

    assert (
        "archived: false"
        in block
    )

    assert (
        "archived_at: null"
        in block
    )

    assert (
        "applyBotFilters();"
        in block
    )

    assert (
        "void loadCore();"
        in block
    )

    toast = block.index(
        "Bot restored to the main list."
    )

    refresh = block.index(
        "void loadCore();"
    )

    assert toast < refresh
