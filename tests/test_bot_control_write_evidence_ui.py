from pathlib import Path
import re


APP = Path(
    "frontend/app.js"
).read_text(
    encoding="utf-8"
)

INDEX = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)

AURORA_CSS = Path(
    "frontend/aurora-bot-control.css"
).read_text(
    encoding="utf-8"
)


FUNCTION_RE = re.compile(
    r"(?m)^[ \t]*(?:async[ \t]+)?function[ \t]+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)[ \t]*\("
)


def function_body(
    name: str,
) -> str:
    matches = list(
        FUNCTION_RE.finditer(
            APP
        )
    )

    selected = [
        (index, match)
        for index, match in enumerate(
            matches
        )
        if match.group(1) == name
    ]

    assert len(selected) == 1

    index, match = selected[0]

    end = (
        matches[index + 1].start()
        if index + 1 < len(matches)
        else len(APP)
    )

    return APP[
        match.start():end
    ]


def test_write_evidence_requires_positive_durable_proof():
    body = function_body(
        "botControlGateWriteEvidence"
    )

    assert (
        "explicitWrite === true"
        in body
    )

    assert (
        "status === 'simulated'"
        in body
    )

    assert (
        "knownLockConflict"
        in body
    )

    assert (
        "status === 'rejected'"
        in body
    )

    assert (
        "gate_status_code"
        in body
    )

    assert (
        "status === 'uncertain'"
        in body
    )

    assert (
        "Do not infer "
        in body
    )

    assert (
        "NOT PERFORMED"
        in body
    )

    # Missing/falsy durable write evidence must never
    # globally collapse to NOT PERFORMED.
    assert (
        "Boolean(response.write_performed)"
        not in body
    )


def test_request_detail_has_distinct_write_evidence_panel():
    body = function_body(
        "renderBotControlRequestDetail"
    )

    assert (
        body.count(
            "botControlGateWriteEvidence"
        )
        == 1
    )

    assert (
        "bot-control-write-evidence"
        in body
    )

    assert (
        body.count(
            "Gate write evidence"
        )
        == 1
    )


def test_explicit_gate_rejection_is_attempted_not_not_performed():
    body = function_body(
        "botControlGateWriteEvidence"
    )

    rejected = body.index(
        "status === 'rejected'"
    )

    attempted = body.index(
        "ATTEMPTED · REJECTED"
    )

    assert attempted > rejected

    rejected_slice = body[
        rejected:
        attempted + 160
    ]

    assert (
        "gate_status_code"
        in rejected_slice
    )

    assert (
        "NOT PERFORMED"
        not in rejected_slice
    )


def test_live_create_language_names_real_gate_write():
    state = function_body(
        "renderBotControlCreateState"
    )

    confirmation = function_body(
        "openSpotGridConfirmation"
    )

    button = function_body(
        "updateSpotGridConfirmButton"
    )

    assert (
        "badge.textContent = 'LIVE WRITE'"
        in state
    )

    assert (
        "Real Gate create enabled"
        in state
    )

    assert (
        "LIVE GATE WRITE ENABLED"
        in confirmation
    )

    assert (
        "can place live orders"
        in confirmation
    )

    assert (
        "Create live Spot Grid"
        in button
    )


def test_live_stop_language_names_real_gate_write():
    controls = function_body(
        "updateBotAdminControls"
    )

    confirmation = function_body(
        "renderBotStopConfirmation"
    )

    button = function_body(
        "updateBotStopConfirmButton"
    )

    assert (
        "sends a real Stop request to Gate"
        in controls
    )

    assert (
        "LIVE GATE WRITE ENABLED"
        in confirmation
    )

    assert (
        "Stop live bot"
        in button
    )


def test_pair_marks_are_adjacent_not_overlapped():
    assert (
        ".aurora-bot-control-market-symbols"
        in AURORA_CSS
    )

    assert (
        "gap: 4px;"
        in AURORA_CSS
    )

    assert (
        "transform: none;"
        in AURORA_CSS
    )

    assert (
        "margin-left: 0;"
        in AURORA_CSS
    )


def test_changed_assets_use_new_cache_key():
    unchanged_version = (
        "20260912-bot-control-live-ux-a7c240-v1"
    )
    aurora_scroll_version = (
        "20260912-aurora-bot-control-asset-inline-a7c264-v1"
    )

    for asset in (
        "bot-control.css",
        "app.js",
    ):
        assert (
            INDEX.count(
                f"./{asset}?v={unchanged_version}"
            )
            == 1
        )

    assert (
        INDEX.count(
            "./aurora-bot-control.css?"
            f"v={aurora_scroll_version}"
        )
        == 1
    )
