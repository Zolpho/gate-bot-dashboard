from pathlib import Path
import re


AURORA_CSS = Path(
    "frontend/aurora-bot-control.css"
).read_text(
    encoding="utf-8"
)

CLASSIC_CSS = Path(
    "frontend/bot-control.css"
).read_text(
    encoding="utf-8"
)

HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)


DIALOGS = (
    "#spotGridConfirmDialog",
    "#stopBotConfirmDialog",
    "#botControlRequestDialog",
)


def rule_bodies(
    css: str,
    selector: str,
) -> list[str]:
    """
    Return bodies for complete CSS rules whose selector
    exactly matches `selector`.

    A selector can legitimately appear more than once,
    for example as a base rule plus a later viewport rule.
    """
    pattern = re.compile(
        r"(?m)^[ \t]*"
        + re.escape(selector)
        + r"[ \t]*\{"
    )

    bodies = []

    for match in pattern.finditer(css):
        opening = css.find(
            "{",
            match.start(),
        )

        depth = 0
        closing = None

        for index in range(
            opening,
            len(css),
        ):
            char = css[index]

            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1

                if depth == 0:
                    closing = index
                    break

        if closing is None:
            raise AssertionError(
                f"unclosed rule: {selector}"
            )

        bodies.append(
            css[
                opening + 1:closing
            ]
        )

    assert bodies, (
        f"selector not found: {selector}"
    )

    return bodies


def exact_rule(
    css: str,
    selector: str,
) -> str:
    bodies = rule_bodies(
        css,
        selector,
    )

    assert len(bodies) == 1, (
        selector,
        len(bodies),
    )

    return bodies[0]


def test_expected_source_rule_counts_are_stable():
    expected = (
        (
            AURORA_CSS,
            "#spotGridConfirmDialog",
            1,
        ),
        (
            AURORA_CSS,
            "#spotGridConfirmDialog > .dialog-header",
            1,
        ),
        (
            AURORA_CSS,
            "#stopBotConfirmDialog",
            1,
        ),
        (
            AURORA_CSS,
            "#stopBotConfirmDialog > .dialog-header",
            1,
        ),
        (
            AURORA_CSS,
            "#botControlRequestDialog",
            1,
        ),
        (
            AURORA_CSS,
            "#botControlRequestDialog > .dialog-header",
            1,
        ),
        (
            CLASSIC_CSS,
            ".bot-control-confirm-content",
            2,
        ),
        (
            CLASSIC_CSS,
            ".bot-control-request-content",
            3,
        ),
        (
            CLASSIC_CSS,
            ".bot-control-confirm-dialog[open]",
            2,
        ),
        (
            CLASSIC_CSS,
            ".bot-control-request-dialog[open]",
            2,
        ),
    )

    for css, selector, count in expected:
        assert (
            len(
                rule_bodies(
                    css,
                    selector,
                )
            )
            == count
        )


def test_aurora_dialog_shells_do_not_own_scrolling():
    for dialog in DIALOGS:
        body = exact_rule(
            AURORA_CSS,
            dialog,
        )

        assert (
            "overflow: hidden;"
            in body
        )

        assert (
            "overflow: auto;"
            not in body
        )


def test_aurora_dialog_headers_are_not_sticky():
    for dialog in DIALOGS:
        body = exact_rule(
            AURORA_CSS,
            f"{dialog} > .dialog-header",
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

        assert (
            "z-index: 4;"
            in body
        )


def test_classic_confirm_content_remains_scroll_owner():
    bodies = rule_bodies(
        CLASSIC_CSS,
        ".bot-control-confirm-content",
    )

    assert any(
        (
            "flex: 1 1 auto;"
            in body
            and "min-height: 0;"
            in body
            and "overflow-y: auto;"
            in body
        )
        for body in bodies
    )


def test_classic_request_content_remains_scroll_owner():
    bodies = rule_bodies(
        CLASSIC_CSS,
        ".bot-control-request-content",
    )

    assert any(
        (
            "flex: 1 1 auto;"
            in body
            and "min-height: 0;"
            in body
            and "overflow-y: auto;"
            in body
        )
        for body in bodies
    )


def test_classic_dialog_shells_remain_clipped_flex_columns():
    confirm_bodies = rule_bodies(
        CLASSIC_CSS,
        ".bot-control-confirm-dialog[open]",
    )

    request_bodies = rule_bodies(
        CLASSIC_CSS,
        ".bot-control-request-dialog[open]",
    )

    required = (
        "display: flex;",
        "flex-direction: column;",
        "overflow: hidden;",
    )

    assert any(
        all(
            token in body
            for token in required
        )
        for body in confirm_bodies
    )

    assert any(
        all(
            token in body
            for token in required
        )
        for body in request_bodies
    )


def test_only_aurora_bot_control_cache_key_changed():
    old_version = (
        "20260912-bot-control-live-ux-a7c240-v1"
    )

    new_version = (
        "20260912-aurora-bot-control-live-warning-a7c282-v1"
    )

    assert (
        HTML.count(
            f"./bot-control.css?v={old_version}"
        )
        == 1
    )

    assert (
        HTML.count(
            f"./app.js?v={old_version}"
        )
        == 1
    )

    assert (
        HTML.count(
            "./aurora-bot-control.css?"
            f"v={new_version}"
        )
        == 1
    )

    assert (
        "./aurora-bot-control.css?"
        f"v={old_version}"
        not in HTML
    )
