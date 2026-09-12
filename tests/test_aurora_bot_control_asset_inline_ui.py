from pathlib import Path
import re


CSS = Path(
    "frontend/aurora-bot-control.css"
).read_text(
    encoding="utf-8"
)

SYMBOLS_JS = Path(
    "frontend/aurora-symbols.js"
).read_text(
    encoding="utf-8"
)

APP_JS = Path(
    "frontend/app.js"
).read_text(
    encoding="utf-8"
)

HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)


CONTEXTS = (
    (
        "#tab-bot-control",
        "0.98rem",
    ),
    (
        "#spotGridConfirmDialog",
        "1rem",
    ),
    (
        "#stopBotConfirmDialog",
        "1rem",
    ),
)


def shared_rule_body_after(
    selector: str,
) -> str:
    position = CSS.find(
        selector
    )

    assert position >= 0, selector

    opening = CSS.find(
        "{",
        position,
    )

    assert opening >= 0, selector

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


def test_asset_inline_class_is_applied_to_value_host():
    assert (
        "'aurora-bot-control-asset-inline'"
        in SYMBOLS_JS
    )

    assert (
        "element.classList.add(\n"
        "        extraClass"
        in SYMBOLS_JS
    )

    assert (
        "#stopBotReturnEstimate "
        ".bot-stop-return-asset"
        in SYMBOLS_JS
    )


def test_stop_return_value_host_is_strong_element():
    assert (
        '<div class="bot-stop-return-asset">'
        in APP_JS
    )

    assert (
        "<strong>${escapeHtml(baseReturn)}</strong>"
        in APP_JS
    )

    assert (
        "<strong>${escapeHtml(quoteReturn)}</strong>"
        in APP_JS
    )


def test_asset_inline_hosts_never_receive_icon_dimensions():
    for context, _dimension in CONTEXTS:
        host = (
            f"{context} "
            ".aurora-bot-control-asset-inline"
        )

        pattern = re.compile(
            re.escape(host)
            + r"\s*\{"
            + r"[^{}]*"
            + r"(?:width|height)\s*:",
            re.S,
        )

        assert not pattern.search(
            CSS
        ), host


def test_asset_inline_child_symbols_keep_dimensions():
    for context, dimension in CONTEXTS:
        child = (
            f"{context} "
            ".aurora-bot-control-asset-inline "
            "> .aurora-symbol"
        )

        body = shared_rule_body_after(
            child
        )

        assert (
            f"width: {dimension};"
            in body
        )

        assert (
            f"height: {dimension};"
            in body
        )


def test_stop_return_host_remains_flexible_amount_row():
    pattern = re.compile(
        r"(?m)^[ \t]*"
        r"\#stopBotConfirmDialog "
        r"\.bot-stop-return-asset strong"
        r"[ \t]*\{"
    )

    matches = list(
        pattern.finditer(
            CSS
        )
    )

    assert len(matches) == 1

    opening = CSS.find(
        "{",
        matches[0].start(),
    )

    closing = CSS.find(
        "}",
        opening,
    )

    body = CSS[
        opening + 1:closing
    ]

    assert "display: flex;" in body
    assert "align-items: center;" in body
    assert "width: 1rem;" not in body
    assert "height: 1rem;" not in body


def test_new_aurora_cache_key_is_served_once():
    version = (
        "20260912-aurora-bot-control-market-symbols-a7c273-v1"
    )

    assert (
        HTML.count(
            "./aurora-bot-control.css?"
            f"v={version}"
        )
        == 1
    )
