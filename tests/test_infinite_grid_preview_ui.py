from __future__ import annotations

from pathlib import Path

ROOT = Path(
    __file__
).resolve().parents[1]

HTML = (
    ROOT
    / "frontend/index.html"
).read_text(
    encoding="utf-8"
)

APP = (
    ROOT
    / "frontend/app.js"
).read_text(
    encoding="utf-8"
)

PREVIEW = (
    ROOT
    / "frontend/infinite-grid-preview.js"
).read_text(
    encoding="utf-8"
)

CSS = (
    ROOT
    / "frontend/bot-control.css"
).read_text(
    encoding="utf-8"
)


def infinity_html_block() -> str:
    identifier = (
        'id="infiniteGridPreviewWorkspace"'
    )

    identifier_position = HTML.index(
        identifier
    )

    start = HTML.rfind(
        "<div",
        0,
        identifier_position,
    )

    if start < 0:
        raise AssertionError(
            "Infinity workspace container not found"
        )

    end = HTML.index(
        (
            '<article class="panel '
            'bot-control-attention-panel">'
        ),
        identifier_position,
    )

    return HTML[
        start:end
    ]


def function_block(
    source: str,
    name: str,
    next_name: str,
) -> str:
    start = source.index(
        f"function {name}("
    )

    end = source.index(
        f"\n\n  function {next_name}(",
        start,
    )

    return source[
        start:end
    ]


def test_preview_assets_are_registered() -> None:
    assert (
        "./infinite-grid-preview.js?"
        "v=20260923-infinity-preview-m4-v1"
        in HTML
    )

    assert (
        "infinitym4="
        "20260923-preview-only-v1"
        in HTML
    )

    assert (
        "./bot-control.css?"
        "v=20260923-infinity-preview-m4-v1"
        in HTML
    )


def test_preview_workspace_contains_required_fields() -> None:
    block = infinity_html_block()

    for element_id in (
        "infiniteGridPreviewWorkspace",
        "infiniteGridAccount",
        "infiniteGridForm",
        "infiniteGridFormError",
        "resetInfiniteGridButton",
        "prepareInfiniteGridButton",
        "infiniteGridReviewEmpty",
        "infiniteGridReview",
        "infiniteGridReviewStatus",
        "infiniteGridReviewMetrics",
        "infiniteGridValidationMessages",
        "infiniteGridPayloadPreview",
    ):
        assert (
            f'id="{element_id}"'
            in block
        )

    for field in (
        'name="account_id"',
        'name="market"',
        'name="money"',
        'name="price_floor"',
        'name="profit_per_grid"',
        'name="grid_num"',
        'name="price_type"',
        'name="trigger_price"',
        'name="stop_profit"',
        'name="stop_loss"',
    ):
        assert field in block


def test_preview_workspace_exposes_no_create_control() -> None:
    block = infinity_html_block()

    for forbidden in (
        "Final confirmation",
        "Create Infinity Grid",
        "Confirm Infinity",
        "infinite-grid/create",
        "createInfiniteGrid",
    ):
        assert forbidden not in block

    assert (
        "Review Infinity Grid"
        in block
    )

    assert (
        "PREVIEW ONLY"
        in block
    )

    assert (
        "No create path"
        in block
    )


def test_frontend_has_no_infinity_create_endpoint() -> None:
    for source in (
        HTML,
        APP,
        PREVIEW,
    ):
        assert (
            "/api/bot-control/"
            "infinite-grid/create"
            not in source
        )

        assert (
            "/bot/infinite-grid/create"
            not in source
        )


def test_prepare_calls_only_prepare_endpoint() -> None:
    start = PREVIEW.index(
        "async function prepareInfiniteGrid("
    )

    end = PREVIEW.index(
        "\n\n  function install()",
        start,
    )

    block = PREVIEW[
        start:end
    ]

    assert (
        "/api/bot-control/"
        "infinite-grid/prepare"
        in block
    )

    assert (
        "method: 'POST'"
        in block
    )

    assert (
        "result.write_performed"
        in block
    )

    assert (
        "!== false"
        in block
    )

    for forbidden in (
        "createInfiniteGrid",
        "infinite-grid/create",
        "confirm",
        "request_id",
    ):
        assert forbidden not in block


def test_optional_gate_defaults_remain_optional() -> None:
    start = PREVIEW.index(
        "function infinityGridDraftFromForm("
    )

    end = PREVIEW.index(
        "\n\n  function reviewMetric(",
        start,
    )

    block = PREVIEW[
        start:end
    ]

    assert (
        "grid_num: ("
        in block
    )

    assert (
        "price_type: ("
        in block
    )

    assert (
        "gridNum === null"
        in block
    )

    assert (
        "priceType === null"
        in block
    )


def test_review_explains_infinity_semantics() -> None:
    start = PREVIEW.index(
        "function renderInfinityGridReview("
    )

    end = PREVIEW.index(
        "\n\n  async function prepareInfiniteGrid(",
        start,
    )

    block = PREVIEW[
        start:end
    ]

    for token in (
        "Price floor",
        "Profit per grid",
        "Number of grids",
        "Gate default",
        "Upper price",
        "No fixed upper bound",
        "Gate market status",
        "Infinity Grid remains preview-only.",
    ):
        assert token in block


def test_account_scope_is_synchronized() -> None:
    assert (
        "function syncBotControlAccount("
        in PREVIEW
    )

    for selector in (
        "#spotGridAccount",
        "#infiniteGridAccount",
    ):
        assert selector in PREVIEW

    assert (
        "invalidateSpotGridReview();"
        in PREVIEW
    )

    assert (
        "invalidateInfinityReview();"
        in PREVIEW
    )

    assert (
        "renderSidebarSyncScope();"
        in PREVIEW
    )


def test_shared_app_has_only_lifecycle_hooks() -> None:
    assert (
        "window.renderInfiniteGridPreviewAccess?.();"
        in APP
    )

    assert (
        "window.resetInfiniteGridPreviewForm?.({"
        in APP
    )

    assert (
        "/api/bot-control/infinite-grid/prepare"
        not in APP
    )

    assert (
        "infiniteGridPayloadPreview"
        not in APP
    )


def test_preview_uses_existing_bot_control_layout() -> None:
    block = infinity_html_block()

    for token in (
        "bot-control-layout",
        "bot-control-form-panel",
        "bot-control-review-panel",
        "bot-control-form",
        "bot-control-review-grid",
        "bot-control-validation",
        "bot-control-payload",
    ):
        assert token in block

    assert (
        ".bot-control-infinity-layout"
        in CSS
    )


def test_preview_controller_has_no_write_confirmation_flow() -> None:
    for forbidden in (
        "submitInfiniteGridCreate",
        "openInfiniteGridConfirmation",
        "confirmInfiniteGrid",
        "botControlRequestId",
        "reserve",
        "operation_lock",
    ):
        assert forbidden not in PREVIEW
