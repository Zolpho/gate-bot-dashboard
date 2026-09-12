from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

CSS = (
    ROOT
    / "frontend"
    / "aurora-wallet-motion.css"
).read_text(
    encoding="utf-8"
)

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)

CACHE = (
    "20260912-aurora-wallet-tablet-motion-a7c303-v2"
)


def test_motion_stylesheet_is_loaded_once():
    ref = (
        "./aurora-wallet-motion.css"
        f"?v={CACHE}"
    )

    assert HTML.count(ref) == 1


def test_motion_stylesheet_loads_after_withdrawal_css():
    withdrawal = HTML.index(
        "aurora-withdrawal.css"
    )

    motion = HTML.index(
        "aurora-wallet-motion.css"
    )

    assert withdrawal < motion


def test_tablet_contract_preserves_existing_geometry():
    assert (
        "@media (max-width: 1320px)"
        in CSS
    )

    # This file owns motion only.
    # It must not redefine the responsive stage grid.
    assert "grid-template-columns" not in CSS
    assert "grid-template-rows" not in CSS


def test_deposit_tablet_stage_motion_exists():
    assert (
        "#walletDepositsWorkspace\n"
        "  .deposit-step.deposit-step-disabled"
        in CSS
    )

    assert (
        "translateY(8px) !important"
        in CSS
    )

    assert (
        "#walletDepositsWorkspace\n"
        "  .deposit-step:not(.deposit-step-disabled)"
        in CSS
    )

    assert (
        "transform 220ms "
        "cubic-bezier(0.2, 0.8, 0.2, 1)"
        in CSS
    )


def test_deposit_network_height_transition_exists():
    assert (
        "#depositNetworkList"
        in CSS
    )

    assert (
        "max-height 190ms "
        "cubic-bezier(0.2, 0.8, 0.2, 1)"
        in CSS
    )


def test_withdrawal_tablet_phase_motion_exists():
    expected = {
        "route": {
            "destination": "-4px",
            "safety": "6px",
            "request": "10px",
        },
        "safety": {
            "destination": "0",
            "safety": "-4px",
            "request": "6px",
        },
        "request": {
            "request": "-4px",
        },
    }

    for phase, stages in expected.items():
        for stage, value in stages.items():
            pattern = re.compile(
                rf'#treasuryWithdrawalAction'
                rf'\[data-aurora-phase="{phase}"\]'
                rf'\s+'
                rf'\.aurora-withdrawal-stage-{stage}'
                rf'\s*\{{'
                rf'.*?'
                rf'transform\s*:'
                rf'.*?'
                rf'translateY\({re.escape(value)}\)'
                rf'\s*!important',
                re.S,
            )

            assert pattern.search(CSS), (
                phase,
                stage,
                value,
            )


def test_tablet_motion_does_not_reintroduce_3d():
    assert "perspective(" not in CSS
    assert "translateZ(" not in CSS
    assert "translate3d(" not in CSS
    assert "rotateX(" not in CSS
    assert "rotateY(" not in CSS


def test_reduced_motion_disables_new_motion():
    reduced = re.search(
        r"@media\s*"
        r"\(prefers-reduced-motion:\s*reduce\)"
        r"\s*\{"
        r"(?P<body>.*)"
        r"\}\s*$",
        CSS,
        re.S,
    )

    assert reduced is not None

    body = reduced.group(
        "body"
    )

    assert "transition:" in body
    assert "none !important" in body
    assert "transform:" in body


def test_motion_layer_has_no_css_imports():
    # File names may legitimately appear in documentation comments.
    # What matters semantically is that this layer does not import
    # another stylesheet and therefore cannot pull Classic CSS into
    # the Aurora motion contract.
    assert re.search(
        r"(?m)^\\s*@import\\b",
        CSS,
    ) is None


def test_motion_layer_is_scoped_to_wallet_surfaces():
    # Parse CSS blocks structurally instead of searching raw text.
    # Comments may contain file names or selector-like prose, and
    # @media blocks contain nested rules, so a flat regex is brittle.

    def strip_comments(text: str) -> str:
        return re.sub(
            r"/\*.*?\*/",
            "",
            text,
            flags=re.S,
        )


    def matching_brace(
        text: str,
        opening: int,
    ) -> int:
        depth = 0
        quote = None
        escaped = False

        for index in range(
            opening,
            len(text),
        ):
            char = text[index]

            if quote is not None:
                if escaped:
                    escaped = False
                    continue

                if char == "\\":
                    escaped = True
                    continue

                if char == quote:
                    quote = None

                continue

            if char in ("'", '"'):
                quote = char
                continue

            if char == "{":
                depth += 1

            elif char == "}":
                depth -= 1

                if depth == 0:
                    return index

        raise AssertionError(
            f"unclosed CSS block at offset {opening}"
        )


    def style_rule_headers(
        text: str,
    ) -> list[str]:
        headers = []
        cursor = 0

        while cursor < len(text):
            while (
                cursor < len(text)
                and text[cursor].isspace()
            ):
                cursor += 1

            if cursor >= len(text):
                break

            opening = text.find(
                "{",
                cursor,
            )

            if opening < 0:
                break

            header = " ".join(
                text[
                    cursor:opening
                ].split()
            )

            closing = matching_brace(
                text,
                opening,
            )

            body = text[
                opening + 1:
                closing
            ]

            if header.startswith(
                (
                    "@media",
                    "@supports",
                    "@container",
                    "@layer",
                )
            ):
                headers.extend(
                    style_rule_headers(
                        body
                    )
                )

            elif header.startswith("@"):
                # Other at-rules are not ordinary style selectors.
                pass

            elif header:
                headers.append(
                    header
                )

            cursor = closing + 1

        return headers


    headers = style_rule_headers(
        strip_comments(
            CSS
        )
    )

    selectors = []

    for header in headers:
        selectors.extend(
            " ".join(
                selector.split()
            )
            for selector
            in header.split(",")
            if selector.strip()
        )

    assert selectors

    for selector in selectors:
        assert (
            "#walletDepositsWorkspace"
            in selector
            or "#treasuryWithdrawalAction"
            in selector
        ), selector


def test_motion_stylesheet_is_aurora_scoped_and_disabled_by_default():
    from html.parser import HTMLParser

    target = (
        "./aurora-wallet-motion.css"
        f"?v={CACHE}"
    )

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(
            self,
            tag,
            attrs,
        ):
            if tag.lower() != "link":
                return

            self.links.append(
                dict(attrs)
            )

    parser = LinkParser()
    parser.feed(
        HTML
    )

    matches = [
        attrs
        for attrs in parser.links
        if attrs.get("href") == target
    ]

    assert len(matches) == 1

    attrs = matches[0]

    assert (
        attrs.get(
            "data-dashboard-ui-stylesheet"
        )
        == "aurora"
    )

    assert "disabled" in attrs

    rel = attrs.get(
        "rel",
        "",
    )

    assert "stylesheet" in rel.split()
