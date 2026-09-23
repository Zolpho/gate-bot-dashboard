from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)

CSS = (
    ROOT
    / "frontend"
    / "classic-security.css"
).read_text(
    encoding="utf-8"
)

UI_MODE = (
    ROOT
    / "frontend"
    / "ui-mode.js"
).read_text(
    encoding="utf-8"
)


class Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()

        self.links: list[
            dict[str, str | None]
        ] = []

        self.elements: dict[
            str,
            dict[str, str | None],
        ] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[
            tuple[str, str | None]
        ],
    ) -> None:
        values = dict(attrs)

        if tag == "link":
            self.links.append(values)

        element_id = values.get("id")

        if element_id:
            self.elements[element_id] = {
                "tag": tag,
                **values,
            }


def inventory() -> Inventory:
    parser = Inventory()
    parser.feed(HTML)
    return parser


def test_classic_security_stylesheet_is_registered() -> None:
    document = inventory()

    styles = [
        item
        for item in document.links
        if str(
            item.get(
                "href",
                "",
            )
        ).split(
            "?",
            1,
        )[0]
        == "./classic-security.css"
    ]

    assert len(styles) == 1

    stylesheet = styles[0]

    assert (
        stylesheet.get(
            "data-dashboard-ui-stylesheet"
        )
        == "classic"
    )

    assert "disabled" in stylesheet

    assert (
        stylesheet.get("href")
        == (
            "./classic-security.css?"
            "v=20260923-classic-security-a7c491a1-v1"
        )
    )


def test_ui_mode_loader_can_activate_classic_styles() -> None:
    for token in (
        "'classic'",
        "'aurora'",
        "[data-dashboard-ui-stylesheet]",
        "owner !== mode",
    ):
        assert token in UI_MODE


def test_classic_security_css_is_mode_scoped() -> None:
    assert (
        'html[data-dashboard-ui="classic"]'
        in CSS
    )

    assert (
        'html[data-dashboard-ui="aurora"]'
        not in CSS
    )


def test_classic_security_covers_shared_page_structure() -> None:
    for selector in (
        "#tab-security",
        ".security-account-panel",
        ".security-account-facts",
        ".security-grid",
        ".security-card",
        ".security-card-heading",
        ".security-status-pill",
        ".security-card-sessions",
        ".security-card-ip",
    ):
        assert selector in CSS


def test_classic_security_covers_active_sessions() -> None:
    for selector in (
        ".security-session-list",
        ".security-session-row",
        ".security-session-row.current",
        ".security-session-heading",
        ".security-session-badge",
        ".security-session-facts",
        ".security-session-fact",
        ".security-session-user-agent",
        ".security-session-row-actions",
        ".security-session-revoke",
        ".security-session-danger",
    ):
        assert selector in CSS


def test_classic_security_covers_ip_restrictions() -> None:
    for selector in (
        ".security-ip-facts",
        ".security-ip-allowlist",
        ".security-ip-allowlist-row",
        ".security-ip-dialog",
        ".security-ip-dialog-content",
        ".security-ip-safety",
        ".security-ip-current",
        ".security-ip-enable",
        'input[type="checkbox"]',
        ".security-ip-editor-row",
        ".security-ip-recovery",
    ):
        assert selector in CSS


def test_classic_security_covers_totp_dialog() -> None:
    for selector in (
        ".security-totp-dialog",
        ".security-totp-stage",
        ".security-totp-safety",
        ".security-totp-setup-grid",
        ".security-totp-qr-surface",
        ".security-totp-secret",
        ".security-totp-confirm-form",
        ".security-totp-recovery-codes",
        ".security-totp-recovery-actions",
    ):
        assert selector in CSS


def test_classic_ip_checkbox_resets_global_input_geometry() -> None:
    checkbox_start = CSS.index(
        '.security-ip-enable\ninput[type="checkbox"]'
    )

    checkbox_end = CSS.index(
        '.security-ip-enable\ninput[type="checkbox"]:hover',
        checkbox_start,
    )

    checkbox = CSS[
        checkbox_start:
        checkbox_end
    ]

    for token in (
        "width: 18px;",
        "height: 18px;",
        "min-width: 18px;",
        "min-height: 18px;",
        "max-width: 18px;",
        "max-height: 18px;",
        "margin: 0;",
        "padding: 0;",
        "box-sizing: border-box;",
    ):
        assert token in checkbox


def test_classic_security_textareas_are_not_browser_default() -> None:
    for token in (
        ".security-ip-field textarea {",
        "min-height: 78px;",
        "resize: vertical;",
        "var(--bg);",
        "var(--text);",
        "font: inherit;",
        ".security-ip-field textarea::placeholder",
        ".security-ip-field textarea:focus",
    ):
        assert token in CSS


def test_classic_security_responsive_contract() -> None:
    for breakpoint in (
        "@media (max-width: 920px)",
        "@media (max-width: 760px)",
        "@media (max-width: 700px)",
        "@media (max-width: 560px)",
    ):
        assert breakpoint in CSS


def test_shared_security_dom_remains_present() -> None:
    document = inventory()

    for element_id in (
        "tab-security",
        "securitySessionsCard",
        "securitySessionsList",
        "securityIpCard",
        "securityIpAllowlist",
        "securityTotpDialog",
        "securityIpDialog",
    ):
        assert element_id in document.elements
