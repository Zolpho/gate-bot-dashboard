from pathlib import Path


def _app() -> str:
    return Path(
        "frontend/app.js"
    ).read_text()


def _html() -> str:
    return Path(
        "frontend/index.html"
    ).read_text()


def _bot_dialog_block() -> str:
    source = _app()

    start = source.index(
        "function renderBotDialog("
    )

    end = source.index(
        "\n\nfunction updateBotAdminControls(",
        start,
    )

    return source[
        start:end
    ]


def test_infinity_create_configuration_is_separate_from_gate_grid_count():
    block = _bot_dialog_block()

    assert (
        "'Grid count'"
        in block
    )

    assert (
        "fmtNumber(bot.grid_count, 0)"
        in block
    )

    assert (
        "bot.create_configuration?.source"
        in block
    )

    assert (
        "=== 'bot_control_create_audit'"
        in block
    )

    assert (
        "'Configured grids'"
        in block
    )

    assert (
        "createConfiguration.grid_count"
        in block
    )

    #
    # UI must not overwrite or fall back into the
    # Gate-observed grid_count field.
    #
    assert (
        "bot.grid_count ="
        not in block
    )

    assert (
        "bot.grid_count ??"
        not in block
    )


def test_infinity_configured_profit_and_grid_type_are_labeled():
    block = _bot_dialog_block()

    for token in (
        "'Configured profit per grid'",
        "createConfiguration.profit_per_grid",
        "'Configured grid type'",
        "createConfiguration?.price_type === 0",
        "createConfiguration?.price_type === 1",
        "'Arithmetic'",
        "'Geometric'",
        "'Configuration source'",
        "'Bot Control create audit'",
    ):
        assert token in block


def test_monitoring_provenance_app_cache_bust_is_present():
    html = _html()

    assert (
        "&amp;infinitym44f="
        "20261001-create-ui-v1"
        "&amp;infinitym45c="
        "20261001-config-provenance-v1"
        in html
    )
