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

HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)


def rule_body_after(
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


def test_market_decorator_uses_nested_span_group_and_slots():
    assert (
        "group.className =\n"
        "      'aurora-bot-control-market-symbols'"
        in SYMBOLS_JS
    )

    assert (
        "slot.className =\n"
        "          'aurora-bot-control-market-symbol-slot'"
        in SYMBOLS_JS
    )

    assert (
        "host.insertBefore(\n"
        "      group,\n"
        "      host.firstChild,"
        in SYMBOLS_JS
    )


def test_review_label_rule_is_direct_child_only():
    assert (
        "#tab-bot-control "
        ".bot-control-review-item > span {"
        in CSS
    )

    assert (
        "#tab-bot-control "
        ".bot-control-review-item span {"
        not in CSS
    )


def test_create_confirmation_label_rule_is_direct_child_only():
    assert (
        "#spotGridConfirmDialog "
        ".bot-control-confirm-row > span {"
        in CSS
    )

    assert (
        "#spotGridConfirmDialog "
        ".bot-control-confirm-row span {"
        not in CSS
    )


def test_stop_confirmation_label_rule_is_direct_child_only():
    assert (
        "#stopBotConfirmDialog "
        ".bot-stop-strategy-meta > div > span,"
        in CSS
    )

    assert (
        "#stopBotConfirmDialog "
        ".bot-stop-strategy-meta span,"
        not in CSS
    )


def test_market_symbol_groups_remain_horizontal_inline_flex():
    selectors = (
        "#tab-bot-control "
        ".aurora-bot-control-market-symbols",
        "#spotGridConfirmDialog "
        ".aurora-bot-control-market-symbols",
        "#stopBotConfirmDialog "
        ".aurora-bot-control-market-symbols",
    )

    for selector in selectors:
        body = rule_body_after(
            selector
        )

        assert (
            "display: inline-flex;"
            in body
        )

        assert (
            "flex-direction: column;"
            not in body
        )


def test_market_symbol_slots_remain_inline_flex():
    selectors = (
        "#tab-bot-control "
        ".aurora-bot-control-market-symbol-slot",
        "#spotGridConfirmDialog "
        ".aurora-bot-control-market-symbol-slot",
        "#stopBotConfirmDialog "
        ".aurora-bot-control-market-symbol-slot",
    )

    for selector in selectors:
        body = rule_body_after(
            selector
        )

        assert (
            "display: inline-flex;"
            in body
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
