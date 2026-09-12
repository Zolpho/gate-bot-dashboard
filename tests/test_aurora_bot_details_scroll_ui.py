from pathlib import Path


CSS = Path(
    "frontend/aurora-bot-details.css"
).read_text(
    encoding="utf-8"
)

HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)


def css_rule(
    selector: str,
) -> str:
    start = CSS.find(
        selector
    )

    assert start >= 0, (
        f"selector not found: {selector}"
    )

    opening = CSS.find(
        "{",
        start,
    )

    assert opening >= 0

    depth = 0

    for index in range(
        opening,
        len(CSS),
    ):
        char = CSS[index]

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1

            if depth == 0:
                return CSS[
                    opening + 1:index
                ]

    raise AssertionError(
        f"unclosed rule: {selector}"
    )


def test_bot_details_dialog_shell_owns_clipping():
    body = css_rule(
        "#botDialog"
    )

    assert (
        "overflow: hidden;"
        in body
    )


def test_bot_details_content_owns_vertical_scrolling():
    body = css_rule(
        "#botDialog .dialog-content"
    )

    assert (
        "overflow: auto;"
        in body
    )

    assert (
        "max-height:"
        in body
    )


def test_bot_details_header_is_not_sticky():
    body = css_rule(
        "#botDialog .dialog-header"
    )

    assert (
        "position: relative;"
        in body
    )

    assert (
        "position: sticky;"
        not in body
    )

    assert (
        "top: 0;"
        not in body
    )

    # Relative positioning intentionally preserves
    # the containing block for the header ::before.
    assert (
        "z-index: 5;"
        in body
    )


def test_bot_details_cache_key_marks_scroll_fix():
    assert (
        "./aurora-bot-details.css?"
        "v=20260912-aurora-bot-details-scroll-a7c248-v1"
        in HTML
    )
