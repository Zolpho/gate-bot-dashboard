from pathlib import Path


APP = Path(
    "frontend/app.js"
).read_text()

HTML = Path(
    "frontend/index.html"
).read_text()

CSS = Path(
    "frontend/bot-control.css"
).read_text()

AURORA = Path(
    "frontend/aurora-bot-control.css"
).read_text()


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


def test_bot_control_fields_use_natural_height():
    assert (
        ".bot-control-form > label"
        in CSS
    )

    assert (
        "#tab-bot-control .bot-control-form > label"
        in AURORA
    )

    assert (
        "align-self: start;"
        in CSS
    )

    assert (
        "align-content: start;"
        in CSS
    )

    assert (
        "align-self: start;"
        in AURORA
    )

    assert (
        "align-content: start;"
        in AURORA
    )


def test_suffix_controls_are_integrated_not_segmented():
    assert (
        ".input-with-suffix:focus-within"
        in CSS
    )

    assert (
        "#tab-bot-control .input-with-suffix:focus-within"
        in AURORA
    )

    aurora_suffix = AURORA[
        AURORA.index(
            "#tab-bot-control .input-with-suffix span"
        ):
        AURORA.index(
            "#tab-bot-control .aurora-bot-control-market-input-symbols"
        )
    ]

    assert "border: 0;" in aurora_suffix
    assert "background: transparent;" in aurora_suffix

    assert (
        "min-width: 3.5rem;"
        not in aurora_suffix
    )


def test_confirmed_gate_write_copy_is_user_friendly():
    block = _function(
        "botControlGateWriteEvidence",
        "renderBotControlRequestDetail",
    )

    assert (
        "Gate accepted this live request successfully."
        in block
    )

    assert (
        "write_performed=true"
        not in block
    )

    #
    # Durable positive proof is still required.
    #
    assert (
        "explicitWrite === true"
        in block
    )


def test_request_detail_wires_lock_history_and_manual_lock_state():
    block = _function(
        "renderBotControlRequestDetail",
        "renderBotControlLockResolutions",
    )

    assert (
        "renderBotControlLockResolutions("
        in block
    )

    assert (
        "detail.lock_resolutions"
        in block
    )

    assert (
        "renderManualLockRelease("
        in block
    )


def test_empty_lock_history_is_hidden():
    block = _function(
        "renderBotControlLockResolutions",
        "updateManualLockReleaseButton",
    )

    assert (
        "#botControlLockResolutionSection"
        in block
    )

    assert (
        "section.classList.add("
        in block
    )

    assert (
        "section.classList.remove("
        in block
    )

    assert (
        "No lock-resolution decisions recorded."
        not in block
    )

    assert (
        'id="botControlLockResolutionSection"'
        in HTML
    )

    assert (
        "<h3>Lock history</h3>"
        in HTML
    )


def test_request_raw_data_is_grouped_as_technical_details():
    assert (
        'class="bot-control-technical-section"'
        in HTML
    )

    assert (
        "<h3>Technical details</h3>"
        in HTML
    )

    assert (
        "<summary>Request data</summary>"
        in HTML
    )

    assert (
        "<summary>Gate response data</summary>"
        in HTML
    )

    assert (
        "<summary>Original request</summary>"
        not in HTML
    )

    assert (
        "<summary>Original response</summary>"
        not in HTML
    )


def test_m46a_cache_busts_cover_changed_assets():
    marker = (
        "m46a="
        "20261001-bot-control-ui-polish-v1"
    )

    assert HTML.count(
        marker
    ) == 3

    assert (
        "./bot-control.css?"
        in HTML
    )

    assert (
        "./aurora-bot-control.css?"
        in HTML
    )

    assert (
        "./app.js?"
        in HTML
    )


def test_spot_and_infinity_strategy_titles_are_symmetric():
    assert (
        "<h2>Spot Grid</h2>"
        in HTML
    )

    assert (
        "<h2>Infinity Grid</h2>"
        in HTML
    )

    assert (
        "<h2>Create Spot Grid</h2>"
        not in HTML
    )

    #
    # Final mutation buttons should still describe
    # the action the operator is about to perform.
    #
    assert (
        ">Create Spot Grid<"
        in HTML.replace(
            "\n",
            "",
        ).replace(
            "  ",
            "",
        )
    ) or (
        "Create Spot Grid"
        in HTML
    )

    assert (
        "Create Infinity Grid"
        in HTML
    )
