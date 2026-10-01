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
        "v=20261001-infinity-create-ui-m44f-v1"
        in HTML
    )

    assert (
        "infinitym44f="
        "20261001-create-ui-v1"
        in HTML
    )

    assert (
        "./bot-control.css?"
        "v=20260923-bot-control-market-m42-v2"
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
        'name="profit_per_grid_percent"',
        'name="trigger_price"',
        'name="stop_profit"',
        'name="stop_loss"',
    ):
        assert field in block


def test_workspace_exposes_gated_create_control() -> None:
    block = infinity_html_block()

    for token in (
        "Final confirmation",
        'id="openInfiniteGridConfirmation"',
        'id="infiniteGridCreateResult"',
        "REVIEW ONLY",
        "Infinity Create rollout disabled",
    ):
        assert token in block

    assert (
        "Review Infinity Grid"
        in block
    )

def test_infinity_create_endpoint_is_controller_only() -> None:
    assert (
        "/api/bot-control/"
        "infinite-grid/create"
        in PREVIEW
    )

    assert (
        "/api/bot-control/"
        "infinite-grid/create"
        not in APP
    )

    for source in (
        HTML,
        APP,
        PREVIEW,
    ):
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


def test_native_infinity_form_omits_grid_count_and_type() -> None:
    block = infinity_html_block()

    assert (
        'name="grid_num"'
        not in block
    )

    assert (
        'name="price_type"'
        not in block
    )

    start = PREVIEW.index(
        "function infinityGridDraftFromForm("
    )

    end = PREVIEW.index(
        "\n\n  function infinityGridPreparePayloadFromDraft(",
        start,
    )

    draft = PREVIEW[
        start:end
    ]

    assert (
        "grid_num"
        not in draft
    )

    assert (
        "price_type"
        not in draft
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
        "Gate profit ratio",
        "Estimated levels to floor",
        "Estimated Gate minimum",
        "Recommended minimum",
        "Native geometric",
        "Upper price",
        "No fixed upper bound",
        "Gate market status",
        "Review the values below before final confirmation.",
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


def test_shared_app_exposes_infinity_safety_helpers() -> None:
    assert (
        "window.renderInfiniteGridPreviewAccess?.();"
        in APP
    )

    assert (
        "window.resetInfiniteGridPreviewForm?.({"
        in APP
    )

    assert (
        "function infinityGridCreationArmed("
        in APP
    )

    assert (
        "function infinityGridSubmissionAvailableForAccount("
        in APP
    )

    assert (
        "state.health?.allow_infinite_grid_create"
        in APP
    )

    assert (
        "/api/bot-control/infinite-grid/create"
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


def test_controller_has_gated_confirmation_flow() -> None:
    for required in (
        "openInfiniteGridConfirmation",
        "updateInfinityGridConfirmButton",
        "submitInfiniteGridCreate",
        "previewState.requestId",
        "/api/bot-control/infinite-grid/create",
        "refreshBotControlRuntimeHealth()",
        "'/api/auth/capabilities'",
    ):
        assert required in PREVIEW

    assert (
        "/bot/infinite-grid/create"
        not in PREVIEW
    )

def test_profit_per_grid_uses_explicit_percent_semantics() -> None:
    block = infinity_html_block()

    assert (
        'name="profit_per_grid_percent"'
        in block
    )

    assert (
        'name="profit_per_grid"'
        not in block
    )

    assert (
        "<span>%</span>"
        in block
    )

    assert (
        "function percentToGateRatioText("
        in PREVIEW
    )

    assert (
        "function infinityGridPreparePayloadFromDraft("
        in PREVIEW
    )


def test_prepare_converts_percent_to_gate_ratio() -> None:
    start = PREVIEW.index(
        "function infinityGridPreparePayloadFromDraft("
    )

    end = PREVIEW.index(
        "\n\n  function reviewMetric(",
        start,
    )

    block = PREVIEW[
        start:end
    ]

    assert (
        "profit_per_grid_percent,"
        in block
    )

    assert (
        "profit_per_grid:"
        in block
    )

    assert (
        "percentToGateRatioText("
        in block
    )


def test_percent_parser_fails_closed_on_ambiguous_notation() -> None:
    start = PREVIEW.index(
        "function percentToGateRatioText("
    )

    end = PREVIEW.index(
        "\n\n  function optionalValue(",
        start,
    )

    block = PREVIEW[
        start:end
    ]

    assert (
        "throw new Error("
        in block
    )

    assert (
        "decimal percentage such as 0.5 or 1"
        in block
    )

    assert (
        "return raw;"
        not in block
    )


def test_review_discloses_human_percent_and_gate_ratio() -> None:
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

    assert (
        "'Profit per grid'"
        in block
    )

    assert (
        "draft.profit_per_grid_percent"
        in block
    )

    assert (
        "'Gate profit ratio'"
        in block
    )

    assert (
        "grid.profit_per_grid"
        in block
    )


def test_preview_discloses_infinity_validation_boundaries() -> None:
    block = infinity_html_block()

    assert (
        'aria-describedby="infiniteGridProfitHint"'
        in block
    )

    assert (
        'id="infiniteGridProfitHint"'
        in block
    )

    assert (
        "Minimum 0.2%; must remain below 100%."
        in block
    )

    assert (
        'min="0.2"'
        in block
    )

    assert (
        'aria-describedby="infiniteGridTriggerHint"'
        in block
    )

    assert (
        'id="infiniteGridTriggerHint"'
        in block
    )

    assert (
        "If set, must be below the "
        "current market price."
        in block
    )


def test_preview_keeps_one_percent_default() -> None:
    block = infinity_html_block()

    profit_position = block.index(
        'name="profit_per_grid_percent"'
    )

    profit_block = block[
        profit_position:
        block.index(
            "</label>",
            profit_position,
        )
    ]

    assert (
        'value="1"'
        in profit_block
    )

    assert (
        "<span>%</span>"
        in profit_block
    )


def test_review_renders_prepare_validation_messages() -> None:
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
        "prepared.can_create",
        "prepared.errors",
        "prepared.warnings",
        "errors.forEach",
        "warnings.forEach",
        "bot-control-message error",
        "bot-control-message warning",
        "escapeHtml(",
        "message",
    ):
        assert token in block

    assert (
        "Preflight failed. "
        "No Gate write was performed."
        in block
    )

def test_review_renders_infinity_estimator_metadata() -> None:
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
        "prepared.infinity_estimate",
        "'Estimated levels to floor'",
        "'Estimated Gate minimum'",
        "'Recommended minimum'",
        "'Native geometric · Gate-derived levels'",
    ):
        assert token in block


def test_m410a_cache_marker_is_present() -> None:
    assert (
        "m410a="
        "20261001-native-infinity-estimator-v1"
        in HTML
    )
