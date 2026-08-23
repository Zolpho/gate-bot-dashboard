from pathlib import Path


def _styles():
    return Path(
        "frontend/styles.css"
    ).read_text(
        encoding="utf-8"
    )


def _html():
    return Path(
        "frontend/index.html"
    ).read_text(
        encoding="utf-8"
    )


def test_global_polish_layer_present():
    css = _styles()

    assert (
        "3J13 global design-system polish v1"
        in css
    )

    for token in (
        "--surface-raised:",
        "--border-soft:",
        "--border-strong:",
        "--focus-ring:",
        "--shadow-sm:",
        "--shadow-lg:",
    ):
        assert token in css


def test_shell_and_navigation_polished():
    css = _styles()

    for token in (
        ".sidebar {",
        ".brand-mark {",
        ".nav-item {",
        ".nav-item:hover {",
        ".nav-item.active {",
        ".topbar {",
    ):
        assert token in css


def test_shared_components_polished():
    css = _styles()

    for token in (
        ".panel,",
        ".metric-card {",
        ".button {",
        ".button.secondary {",
        "select,",
        ".toolbar-panel {",
        ".table-panel {",
        ".empty-state {",
        "dialog {",
        ".toast {",
    ):
        assert token in css


def test_common_badges_and_tables_polished():
    css = _styles()

    for token in (
        ".mode-badge,",
        ".status-badge.running,",
        ".account-badge {",
        "font-variant-numeric:",
        "tbody tr:hover {",
        ".strategy-cell strong {",
    ):
        assert token in css


def test_archive_polish_present():
    css = _styles()

    for token in (
        ".archived-bots-panel {",
        ".archived-bots-summary {",
        ".archived-bots-summary:hover {",
        ".bot-row-actions {",
    ):
        assert token in css


def test_accessibility_polish_present():
    css = _styles()

    assert (
        "@media (prefers-reduced-motion: reduce)"
        in css
    )

    assert "::selection {" in css
    assert "button:focus-visible" in css


def test_responsive_polish_present():
    css = _styles()

    assert (
        "@media (max-width: 820px)"
        in css
    )

    assert (
        "@media (max-width: 560px)"
        in css
    )


def test_styles_cache_buster_updated():
    html = _html()

    assert (
        "./styles.css?v=20260823-global-polish-v1"
        in html
    )

    assert (
        "./styles.css?v=20260822-bot-archive-v1"
        not in html
    )


def test_app_js_cache_buster_unchanged():
    html = _html()

    assert (
        "./app.js?v=20260822-bot-archive-v2"
        in html
    )
