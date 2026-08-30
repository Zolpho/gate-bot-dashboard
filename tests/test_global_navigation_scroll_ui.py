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


def test_scroll_reset_is_a_single_reusable_helper():
    block = function(
        "resetPageScroll"
    )

    assert (
        "window.scrollTo({"
        in block
    )

    assert "top: 0," in block
    assert "left: 0," in block

    assert (
        "behavior: 'auto',"
        in block
    )

    assert JS.count(
        "window.scrollTo("
    ) == 1


def test_browser_scroll_restoration_is_manual():
    block = function(
        "configurePageScrollRestoration"
    )

    assert (
        "'scrollRestoration' in window.history"
        in block
    )

    assert (
        "window.history.scrollRestoration = 'manual';"
        in block
    )


def test_pageshow_reasserts_top_after_browser_restore():
    block = function(
        "configurePageScrollRestoration"
    )

    assert (
        "window.addEventListener("
        in block
    )

    assert "'pageshow'" in block

    assert (
        "resetPageScroll,"
        in block
    )


def test_switch_tab_captures_previous_active_tab():
    block = function(
        "switchTab"
    )

    assert (
        "const previousTab = state.activeTab;"
        in block
    )

    assert (
        "const tabChanged = previousTab !== target;"
        in block
    )


def test_real_tab_change_uses_reusable_scroll_reset():
    block = function(
        "switchTab"
    )

    assert (
        "if (tabChanged) {"
        in block
    )

    assert (
        "resetPageScroll();"
        in block
    )

    changed = block.index(
        "if (tabChanged) {"
    )

    reset = block.index(
        "resetPageScroll();"
    )

    assert changed < reset


def test_switch_tab_no_longer_duplicates_scroll_primitive():
    block = function(
        "switchTab"
    )

    assert (
        "window.scrollTo("
        not in block
    )

    assert (
        "scrollIntoView"
        not in block
    )

    assert (
        ".scrollTop"
        not in block
    )


def test_tab_reset_occurs_after_new_tab_becomes_active():
    block = function(
        "switchTab"
    )

    previous = block.index(
        "const previousTab = state.activeTab;"
    )

    changed = block.index(
        "const tabChanged = previousTab !== target;"
    )

    active = block.index(
        "state.activeTab = target;"
    )

    reset = block.index(
        "resetPageScroll();"
    )

    assert (
        previous
        < changed
        < active
        < reset
    )


def test_tab_reset_precedes_page_specific_async_loading():
    block = function(
        "switchTab"
    )

    active = block.index(
        "state.activeTab = target;"
    )

    reset = block.index(
        "resetPageScroll();"
    )

    wallet_load = block.index(
        "target === 'wallet'",
        active,
    )

    assert reset < wallet_load


def test_navigation_clicks_continue_to_use_switch_tab():
    block = function(
        "bindEvents"
    )

    assert (
        "switchTab(button.dataset.tab)"
        in block
    )

    assert (
        "switchTab(button.dataset.jump)"
        in block
    )


def test_hash_navigation_continues_to_use_switch_tab():
    block = function(
        "bindEvents"
    )

    assert (
        "hashchange"
        in block
    )

    assert (
        "switchTab(window.location.hash.slice(1), "
        "{ updateHash: false })"
        in block
    )


def test_scroll_restoration_is_configured_before_app_startup():
    configure_call = JS.index(
        "configurePageScrollRestoration();"
    )

    bind_call = JS.index(
        "\nbindEvents();",
        configure_call,
    )

    initial_switch = JS.index(
        "switchTab(window.location.hash.slice(1) "
        "|| 'overview', { updateHash: false });",
        bind_call,
    )

    assert (
        configure_call
        < bind_call
        < initial_switch
    )


def test_initial_startup_explicitly_resets_to_top():
    initial_switch = JS.index(
        "switchTab(window.location.hash.slice(1) "
        "|| 'overview', { updateHash: false });"
    )

    initial_reset = JS.index(
        "\nresetPageScroll();",
        initial_switch,
    )

    load_core = JS.index(
        "\nloadCore();",
        initial_reset,
    )

    assert (
        initial_switch
        < initial_reset
        < load_core
    )


def test_restoration_hooks_are_centralized_once():
    assert JS.count(
        "function resetPageScroll()"
    ) == 1

    assert JS.count(
        "function configurePageScrollRestoration()"
    ) == 1

    assert JS.count(
        "window.history.scrollRestoration = 'manual';"
    ) == 1

    assert JS.count(
        "'pageshow'"
    ) == 1

    assert JS.count(
        "configurePageScrollRestoration();"
    ) == 1
