from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

APP = (
    ROOT
    / "frontend"
    / "app.js"
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

STYLES = (
    ROOT
    / "frontend"
    / "styles.css"
).read_text(
    encoding="utf-8"
)

AURORA_BOTS = (
    ROOT
    / "frontend"
    / "aurora-bots.css"
).read_text(
    encoding="utf-8"
)


def test_out_of_range_precedes_trigger_waiting() -> None:
    range_check = APP.index(
        "rangeState === 'out_of_range'"
    )
    waiting_check = APP.index(
        "const waitingForTrigger"
    )

    assert range_check < waiting_check
    assert "key: 'out-of-range'" in APP
    assert "label: 'Out of range'" in APP


def test_overview_has_separate_out_of_range_bucket() -> None:
    assert "outOfRange: 0" in APP
    assert (
        "displayStatus === 'out-of-range'"
        in APP
    )
    assert (
        "displayCounts.outOfRange"
        in APP
    )
    assert "'--range'" in APP
    assert "'Out of range'" in APP


def test_out_of_range_remains_active_for_leaders() -> None:
    assert (
        "botDisplayStatus(bot).key === 'out-of-range'"
        in APP
    )
    assert "No active bots yet." in APP


def test_bot_filter_preserves_raw_status_with_derived_options() -> None:
    assert (
        "status === 'out-of-range'"
        in APP
    )

    assert (
        "botDisplayStatus(bot).key === 'out-of-range'"
        in APP
    )

    assert (
        "status === 'waiting-trigger'"
        in APP
    )

    assert (
        "botDisplayStatus(bot).key === 'waiting-trigger'"
        in APP
    )

    # Existing status filters remain canonical/raw.
    # Therefore a Gate-running bot can still appear under
    # Running while also being explicitly filterable as
    # Out of range or To be triggered.
    assert (
        "&& bot.status === status"
        in APP
    )

    assert (
        'value="out-of-range">Out of range'
        in HTML
    )

    assert (
        'value="waiting-trigger">To be triggered'
        in HTML
    )


def test_classic_has_out_of_range_badge_and_ring_segment() -> None:
    assert (
        ".status-badge.out-of-range"
        in STYLES
    )
    assert "--range: 0deg" in STYLES
    assert (
        "#ff9f6e var(--run) var(--range)"
        in STYLES
    )


def test_aurora_has_out_of_range_badge() -> None:
    assert (
        "#tab-bots .status-badge.out-of-range"
        in AURORA_BOTS
    )


def test_raw_gate_status_labels_remain_present() -> None:
    assert (
        "source_status"
        in APP
    )
    assert (
        "['Gate status', bot.source_status]"
        in APP
    )

def test_out_of_range_assets_have_current_cache_version() -> None:
    range_version = "20260912-out-of-range-a7c227-v1"
    app_version = "20260912-bot-control-live-ux-a7c240-v1"

    assert (
        f"./app.js?v={app_version}"
        in HTML
    )

    for asset in (
        "styles.css",
        "aurora-bots.css",
    ):
        assert (
            f"./{asset}?v={range_version}"
            in HTML
        )

