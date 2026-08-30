from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

JS = (
    ROOT / "frontend" / "app.js"
).read_text()


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(name):
    matches = list(
        FUNCTION_PATTERN.finditer(JS)
    )

    found = []

    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(JS)
        )

        found.append(
            JS[match.start():end]
        )

    assert len(found) == 1

    return found[0]


def test_switch_tab_captures_previous_active_tab():
    block = function("switchTab")

    assert (
        "const previousTab = state.activeTab;"
        in block
    )

    assert (
        "const tabChanged = previousTab !== target;"
        in block
    )


def test_scroll_reset_only_runs_for_real_tab_change():
    block = function("switchTab")

    assert "if (tabChanged) {" in block

    changed = block.index(
        "if (tabChanged) {"
    )

    scroll = block.index(
        "window.scrollTo({"
    )

    assert changed < scroll


def test_scroll_reset_targets_browser_page_top():
    block = function("switchTab")

    assert "window.scrollTo({" in block
    assert "top: 0," in block
    assert "left: 0," in block
    assert "behavior: 'auto'," in block


def test_scroll_reset_happens_after_new_tab_becomes_active():
    block = function("switchTab")

    previous = block.index(
        "const previousTab = state.activeTab;"
    )

    changed = block.index(
        "const tabChanged = previousTab !== target;"
    )

    active = block.index(
        "state.activeTab = target;"
    )

    scroll = block.index(
        "window.scrollTo({"
    )

    assert (
        previous
        < changed
        < active
        < scroll
    )


def test_scroll_reset_precedes_page_specific_async_loading():
    block = function("switchTab")

    active = block.index(
        "state.activeTab = target;"
    )

    scroll = block.index(
        "window.scrollTo({"
    )

    wallet_load = block.index(
        "target === 'wallet'",
        active,
    )

    assert scroll < wallet_load


def test_scroll_behavior_is_centralized_once():
    block = function("switchTab")

    assert block.count(
        "window.scrollTo("
    ) == 1

    assert JS.count(
        "window.scrollTo("
    ) == 1


def test_navigation_clicks_continue_to_use_switch_tab():
    block = function("bindEvents")

    assert (
        "switchTab(button.dataset.tab)"
        in block
    )

    assert (
        "switchTab(button.dataset.jump)"
        in block
    )


def test_hash_navigation_continues_to_use_switch_tab():
    block = function("bindEvents")

    assert "hashchange" in block

    assert (
        "switchTab(window.location.hash.slice(1), "
        "{ updateHash: false })"
        in block
    )


def test_no_per_panel_scroll_target_was_introduced():
    block = function("switchTab")

    assert "scrollIntoView" not in block
    assert ".scrollTop" not in block
