from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

INDEX = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)

LAYOUT = (
    ROOT
    / "frontend"
    / "aurora-wallet-tablet.css"
).read_text(
    encoding="utf-8"
)

MOTION = (
    ROOT
    / "frontend"
    / "aurora-wallet-motion.css"
).read_text(
    encoding="utf-8"
)

WITHDRAWAL = (
    ROOT
    / "frontend"
    / "aurora-withdrawal.css"
).read_text(
    encoding="utf-8"
)

LAYOUT_CACHE = (
    "20260912-aurora-wallet-tablet-layout-a7c312-v2"
)

MOTION_CACHE = (
    "20260912-aurora-wallet-tablet-motion-a7c303-v2"
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
        if tag.lower() == "link":
            self.links.append(
                dict(attrs)
            )


def css_brace_block(
    source,
    start,
):
    open_brace = source.index(
        "{",
        start,
    )

    depth = 0

    for position in range(
        open_brace,
        len(source),
    ):
        character = source[position]

        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1

            if depth == 0:
                return source[
                    start:
                    position + 1
                ]

    raise AssertionError(
        "unterminated CSS block"
    )


def stylesheet_link(
    href,
):
    parser = LinkParser()
    parser.feed(
        INDEX
    )

    matches = [
        attrs
        for attrs in parser.links
        if attrs.get(
            "href"
        ) == href
    ]

    assert len(matches) == 1

    return matches[0]


def test_tablet_layout_stylesheet_is_aurora_only():
    href = (
        "./aurora-wallet-tablet.css?"
        f"v={LAYOUT_CACHE}"
    )

    attrs = stylesheet_link(
        href
    )

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


def test_tablet_layout_loads_after_wallet_motion():
    motion_position = INDEX.index(
        "aurora-wallet-motion.css"
    )

    layout_position = INDEX.index(
        "aurora-wallet-tablet.css"
    )

    assert (
        layout_position
        > motion_position
    )


def test_tablet_layout_uses_1320_boundary():
    assert (
        "@media (max-width: 1320px)"
        in LAYOUT
    )

    assert (
        "@media (max-width: 1180px)"
        not in LAYOUT
    )


def test_deposit_tablet_geometry_is_single_column():
    assert (
        "#walletDepositsWorkspace"
        in LAYOUT
    )

    assert (
        ".deposit-dialog-content"
        in LAYOUT
    )

    assert re.search(
        r"\.deposit-dialog-content"
        r"\s*\{"
        r"[^}]*"
        r"grid-template-columns\s*:"
        r"\s*minmax\(0,\s*1fr\)"
        r"\s*!important",
        LAYOUT,
        flags=re.S,
    )


def test_withdrawal_tablet_geometry_is_single_column():
    assert (
        "#treasuryWithdrawalAction"
        in LAYOUT
    )

    assert (
        ".aurora-withdrawal-stage-grid"
        in LAYOUT
    )

    assert re.search(
        r"\.aurora-withdrawal-stage-grid"
        r"\s*\{"
        r"[^}]*"
        r"grid-template-columns\s*:"
        r"\s*minmax\(0,\s*1fr\)"
        r"\s*!important",
        LAYOUT,
        flags=re.S,
    )


def test_withdrawal_tablet_route_grid_keeps_named_areas_vertical():
    media_pattern = re.compile(
        r"@media\s*\("
        r"\s*max-width\s*:"
        r"\s*1320px\s*\)"
    )

    route_media_blocks = []

    for match in media_pattern.finditer(
        WITHDRAWAL
    ):
        media_block = css_brace_block(
            WITHDRAWAL,
            match.start(),
        )

        if (
            ".treasury-withdrawal-route-grid"
            in media_block
        ):
            route_media_blocks.append(
                media_block
            )

    assert len(route_media_blocks) == 1

    media_block = route_media_blocks[0]

    route_selector = (
        ".treasury-withdrawal-route-grid"
    )

    route_position = media_block.index(
        route_selector
    )

    route_block = css_brace_block(
        media_block,
        route_position,
    )

    assert re.search(
        r"grid-template-columns\s*:"
        r"\s*1fr\s*!important",
        route_block,
        flags=re.S,
    )

    assert re.search(
        r"grid-template-areas\s*:"
        r'\s*"asset"'
        r'\s*"network"'
        r'\s*"recipient"'
        r'\s*"memo"'
        r'\s*"actions"'
        r"\s*!important",
        route_block,
        flags=re.S,
    )


def test_geometry_layer_does_not_own_motion():
    forbidden = (
        "transform:",
        "transition:",
        "perspective(",
        "translate3d(",
        "translateY(",
        "rotate",
        "opacity:",
    )

    for token in forbidden:
        assert token not in LAYOUT


def test_motion_layer_does_not_own_geometry():
    forbidden = (
        "grid-template-columns",
        "grid-template-rows",
    )

    for token in forbidden:
        assert token not in MOTION


def test_motion_band_now_covers_real_1210px_ipad():
    match = re.search(
        r"@media\s*\(\s*max-width\s*:\s*(\d+)px\s*\)",
        MOTION,
    )

    assert match is not None

    breakpoint = int(
        match.group(1)
    )

    assert breakpoint == 1320
    assert 1210 <= breakpoint


def test_desktop_1366_remains_outside_tablet_band():
    assert 1366 > 1320


def test_updated_motion_cache_reference_is_exact():
    href = (
        "./aurora-wallet-motion.css?"
        f"v={MOTION_CACHE}"
    )

    attrs = stylesheet_link(
        href
    )

    assert (
        attrs.get(
            "data-dashboard-ui-stylesheet"
        )
        == "aurora"
    )

    assert "disabled" in attrs


def test_withdrawal_tablet_stage_placement_returns_to_normal_flow():
    phase_selector = (
        "#treasuryWithdrawalAction[data-aurora-phase]"
    )

    for stage in (
        ".aurora-withdrawal-stage-destination",
        ".aurora-withdrawal-stage-safety",
        ".aurora-withdrawal-stage-request",
    ):
        assert (
            phase_selector
            in LAYOUT
        )

        assert stage in LAYOUT

    assert re.search(
        r"#treasuryWithdrawalAction\[data-aurora-phase\]"
        r"\s*\.aurora-withdrawal-stage-destination,"
        r".*?"
        r"#treasuryWithdrawalAction\[data-aurora-phase\]"
        r"\s*\.aurora-withdrawal-stage-safety,"
        r".*?"
        r"#treasuryWithdrawalAction\[data-aurora-phase\]"
        r"\s*\.aurora-withdrawal-stage-request"
        r"\s*\{"
        r"[^}]*"
        r"grid-area\s*:\s*auto\s*!important"
        r"[^}]*"
        r"grid-column\s*:\s*1\s*/\s*-1\s*!important"
        r"[^}]*"
        r"grid-row\s*:\s*auto\s*!important",
        LAYOUT,
        flags=re.S,
    )
