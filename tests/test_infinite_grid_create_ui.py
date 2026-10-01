from __future__ import annotations

from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]

SYSTEM = (
    ROOT
    / "app/api/system.py"
).read_text()

APP = (
    ROOT
    / "frontend/app.js"
).read_text()

PREVIEW = (
    ROOT
    / "frontend/infinite-grid-preview.js"
).read_text()

HTML = (
    ROOT
    / "frontend/index.html"
).read_text()


def function_block(
    source: str,
    marker: str,
    next_marker: str,
) -> str:
    start = source.index(
        marker
    )

    end = source.index(
        next_marker,
        start,
    )

    return source[
        start:end
    ]


def test_health_exposes_independent_infinity_arm() -> None:
    assert (
        '"allow_infinite_grid_create"'
        in SYSTEM
    )

    assert (
        "settings.allow_infinite_grid_create"
        in SYSTEM
    )


def test_shared_availability_requires_infinity_arm() -> None:
    armed = function_block(
        APP,
        "function infinityGridCreationArmed(",
        "\nfunction infinityGridSubmissionAvailableForAccount(",
    )

    availability = function_block(
        APP,
        "function infinityGridSubmissionAvailableForAccount(",
        "\nfunction botStopEnabled(",
    )

    assert (
        "state.health?.allow_infinite_grid_create"
        in armed
    )

    assert (
        "infinityGridCreationArmed()"
        in availability
    )

    assert (
        "botCreationSubmissionAvailableForAccount("
        in availability
    )


def test_infinity_confirmation_dialog_is_separate() -> None:
    for element_id in (
        "infiniteGridConfirmDialog",
        "infiniteGridConfirmSummary",
        "infiniteGridCreateNotice",
        "infiniteGridRequiredConfirmation",
        "infiniteGridConfirmText",
        "infiniteGridConfirmError",
        "cancelInfiniteGridCreate",
        "confirmInfiniteGridCreate",
    ):
        assert (
            f'id="{element_id}"'
            in HTML
        )


def test_infinity_review_action_is_disabled_by_default() -> None:
    assert (
        'id="openInfiniteGridConfirmation"'
        in HTML
    )

    segment = HTML[
        HTML.index(
            'id="openInfiniteGridConfirmation"'
        ) - 200:
        HTML.index(
            'id="openInfiniteGridConfirmation"'
        ) + 250
    ]

    assert "disabled" in segment


def test_submit_refreshes_both_safety_sources() -> None:
    submit = function_block(
        PREVIEW,
        "  async function submitInfiniteGridCreate(",
        "\n\n  async function prepareInfiniteGrid(",
    )

    assert (
        "await refreshBotControlRuntimeHealth();"
        in submit
    )

    assert (
        "'/api/auth/capabilities'"
        in submit
    )

    assert (
        "renderBotControlAccess();"
        in submit
    )

    for token in (
        "modeBefore",
        "modeAfter",
        "armBefore",
        "armAfter",
        "availableBefore",
        "availableAfter",
    ):
        assert token in submit


def test_submit_fails_closed_if_safety_state_changes() -> None:
    submit = function_block(
        PREVIEW,
        "  async function submitInfiniteGridCreate(",
        "\n\n  async function prepareInfiniteGrid(",
    )

    assert (
        "modeAfter !== modeBefore"
        in submit
    )

    assert (
        "armAfter !== armBefore"
        in submit
    )

    assert (
        "availableAfter !== availableBefore"
        in submit
    )

    assert (
        "|| !availableAfter"
        in submit
    )

    assert (
        "No Create request was "
        in submit
    )


def test_submit_uses_persistent_idempotency_request_id() -> None:
    submit = function_block(
        PREVIEW,
        "  async function submitInfiniteGridCreate(",
        "\n\n  async function prepareInfiniteGrid(",
    )

    assert (
        "if (!previewState.requestId)"
        in submit
    )

    assert (
        "generateBotControlRequestId("
        in submit
    )

    assert (
        "'infinite-grid'"
        in submit
    )

    assert (
        "request_id:"
        in submit
    )

    assert (
        "Keep the SAME request ID"
        in submit
    )


def test_create_post_exists_exactly_once_in_controller() -> None:
    endpoint = (
        "/api/bot-control/"
        "infinite-grid/create"
    )

    assert (
        PREVIEW.count(
            endpoint
        )
        == 1
    )

    assert endpoint not in APP

    assert (
        "/bot/infinite-grid/create"
        not in PREVIEW
    )


def test_prepare_path_remains_read_only() -> None:
    prepare = function_block(
        PREVIEW,
        "  async function prepareInfiniteGrid(",
        "\n\n  function install()",
    )

    assert (
        "/api/bot-control/"
        "infinite-grid/prepare"
        in prepare
    )

    assert (
        "result.write_performed"
        in prepare
    )

    assert (
        "/api/bot-control/"
        "infinite-grid/create"
        not in prepare
    )


def test_rollout_disabled_copy_is_initial_state() -> None:
    assert (
        "Infinity Create rollout disabled"
        in HTML
    )

    assert (
        ">REVIEW ONLY</span>"
        in HTML
    )


def test_modified_assets_are_cache_busted() -> None:
    assert (
        "infinitym44f="
        "20261001-create-ui-v1"
        in HTML
    )

    assert (
        "./infinite-grid-preview.js?"
        "v=20261001-infinity-create-ui-m44f-v1"
        in HTML
    )
