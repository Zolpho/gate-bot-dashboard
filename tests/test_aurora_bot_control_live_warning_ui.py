from pathlib import Path
import re


CSS = Path(
    "frontend/aurora-bot-control.css"
).read_text(
    encoding="utf-8"
)

HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)

APP_JS = Path(
    "frontend/app.js"
).read_text(
    encoding="utf-8"
)


def rule_body(
    selector: str,
) -> str:
    pattern = re.compile(
        r"(?m)^[ \t]*"
        + re.escape(selector)
        + r"[ \t]*\{"
    )

    match = pattern.search(
        CSS
    )

    assert match is not None, selector

    opening = CSS.find(
        "{",
        match.start(),
    )

    depth = 0

    for index in range(
        opening,
        len(CSS),
    ):
        if CSS[index] == "{":
            depth += 1
        elif CSS[index] == "}":
            depth -= 1

            if depth == 0:
                return CSS[
                    opening + 1:index
                ]

    raise AssertionError(
        f"unclosed CSS rule: {selector}"
    )


def test_create_confirmation_dialog_is_wide_enough_for_desktop_warning():
    body = rule_body(
        "#spotGridConfirmDialog"
    )

    normalized = " ".join(
        body.split()
    )

    assert (
        "width: min( 52rem, calc(100vw - 2rem) );"
        in normalized
    )


def test_live_warning_is_single_line_only_on_desktop():
    media = re.search(
        r"@media\s*\(min-width:\s*860px\)\s*\{"
        r"(?P<body>.*?)"
        r"\n\}",
        CSS,
        re.S,
    )

    assert media is not None

    body = media.group(
        "body"
    )

    assert (
        "#spotGridConfirmDialog"
        in body
    )

    assert (
        "#botCreateDisabledNotice.enabled"
        in body
    )

    assert (
        "white-space: nowrap;"
        in body
    )


def test_base_safety_notice_does_not_force_nowrap():
    body = rule_body(
        "#spotGridConfirmDialog .bot-control-safety-notice"
    )

    assert (
        "white-space:"
        not in body
    )


def test_existing_mobile_create_confirmation_breakpoint_remains():
    assert (
        "@media (max-width: 760px)"
        in CSS
    )

    assert (
        "#spotGridConfirmDialog .bot-control-confirm-summary"
        in CSS
    )


def test_live_warning_text_is_unchanged():
    expected = (
        "LIVE GATE WRITE ENABLED. Submitting this "
        "confirmation sends a real Spot Grid creation request "
        "to Gate and can place live orders."
    )

    assert expected in (
        APP_JS.replace(
            "'\n      + '",
            "",
        )
    ) or (
        "'LIVE GATE WRITE ENABLED. Submitting this '"
        in APP_JS
        and (
            "'confirmation sends a real Spot Grid creation "
            "request to Gate and can place live orders.'"
            in APP_JS
        )
    )


def test_new_aurora_cache_key_is_served_once():
    version = (
        "20260912-aurora-bot-control-live-warning-a7c282-v1"
    )

    assert (
        HTML.count(
            "./aurora-bot-control.css?"
            f"v={version}"
        )
        == 1
    )
