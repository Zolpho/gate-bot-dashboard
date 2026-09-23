from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT / "frontend/index.html"
).read_text()

APP = (
    ROOT / "frontend/app.js"
).read_text()

FEATURE = (
    ROOT
    / "frontend/aurora-account-permissions.js"
).read_text()

CSS = (
    ROOT
    / "frontend/aurora-account-permissions.css"
).read_text()


class DocumentInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()

        self.elements_by_id: dict[
            str,
            dict[str, str | None],
        ] = {}

        self.links: list[
            dict[str, str | None]
        ] = []

        self.scripts: list[
            dict[str, str | None]
        ] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[
            tuple[str, str | None]
        ],
    ) -> None:
        values = dict(attrs)

        element_id = values.get("id")

        if element_id:
            self.elements_by_id[
                element_id
            ] = {
                "tag": tag,
                **values,
            }

        if tag == "link":
            self.links.append(values)

        if tag == "script":
            self.scripts.append(values)


def inventory() -> DocumentInventory:
    parser = DocumentInventory()
    parser.feed(HTML)
    return parser


def test_permissions_workspace_is_canonical_but_hidden() -> None:
    document = inventory()

    button = document.elements_by_id[
        "accountPermissionsButton"
    ]

    assert button["tag"] == "button"

    assert (
        "hidden"
        in str(
            button.get("class", "")
        ).split()
    )

    assert (
        button.get("aria-hidden")
        == "true"
    )

    assert (
        button.get("aria-controls")
        == "accountPermissionsDialog"
    )

    dialog = document.elements_by_id[
        "accountPermissionsDialog"
    ]

    assert dialog["tag"] == "dialog"


def test_permissions_assets_are_aurora_owned() -> None:
    document = inventory()

    stylesheet = next(
        item
        for item in document.links
        if (
            item.get("href", "").split("?")[0]
            == "./aurora-account-permissions.css"
        )
    )

    assert (
        stylesheet.get(
            "data-dashboard-ui-stylesheet"
        )
        == "aurora"
    )

    assert "disabled" in stylesheet

    assert (
        'html[data-dashboard-ui="aurora"]'
        in CSS
    )


def test_permissions_feature_loads_after_app() -> None:
    document = inventory()

    sources = [
        item.get("src", "")
        for item in document.scripts
        if item.get("src")
    ]

    app_index = next(
        index
        for index, source
        in enumerate(sources)
        if source.startswith("./app.js?")
    )

    feature_index = next(
        index
        for index, source
        in enumerate(sources)
        if source.startswith(
            "./aurora-account-permissions.js?"
        )
    )

    assert feature_index > app_index

    assert (
        sources[app_index]
        == (
            "./app.js?"
            "v=20260912-bot-control-live-ux-a7c240-v1"
            "&a7c486=20260913-account-permissions-v1"
            "&a7c488=20260922-login-startup-hotfix-v1"
            "&a7c488copy=20260922-authenticator-copy-v1"
            "&a7c488escape=20260922-recovery-escape-guard-v1"
            "&a7c489c=20260922-active-sessions-readonly-v1"
            "&a7c489d=20260923-session-revocation-v1"
            "&a7c490c=20260923-ip-restrictions-ui-v1"
            "&a7c490d21=20260923-refresh-safe-session-v1"
        )
    )

    assert (
        sources[feature_index]
        == (
            "./aurora-account-permissions.js?"
            "v=20260913-account-permissions-a7c486-v1"
        )
    )


def test_app_contains_only_permissions_lifecycle_hooks() -> None:
    assert (
        APP.count(
            "window.renderAccountPermissionsAccess?.();"
        )
        == 1
    )

    assert (
        APP.count(
            "window.clearAccountPermissionsState?.();"
        )
        == 1
    )

    assert (
        "/api/auth/account-policies"
        not in APP
    )


def test_feature_is_rootadmin_and_aurora_only() -> None:
    assert (
        "dataset.dashboardUi"
        in FEATURE
    )

    assert (
        "!== 'aurora'"
        in FEATURE
    )

    assert (
        "state.adminUser.role === 'super_admin'"
        in FEATURE
    )

    assert (
        "/api/auth/account-policies"
        in FEATURE
    )


def test_feature_uses_actual_policy_account_fields() -> None:
    for field in (
        "account_name",
        "account_type",
        "account_enabled",
        "account_configured",
    ):
        assert field in FEATURE


def test_policy_changes_require_explicit_save_and_reason() -> None:
    save_start = FEATURE.index(
        "const saveAccountPolicy"
    )

    save_end = FEATURE.index(
        "const closeAccountPermissionsDialog",
        save_start,
    )

    save_block = FEATURE[
        save_start:save_end
    ]

    assert (
        "method: 'PATCH'"
        in save_block
    )

    assert (
        "reason.length < 10"
        in save_block
    )

    assert (
        "method: 'PATCH'"
        not in FEATURE[:save_start]
    )

    assert (
        "data-account-policy-save"
        in FEATURE
    )


def test_permissions_ui_contains_gate_write_invariants() -> None:
    assert (
        FEATURE.count(
            "gate_write_performed"
        )
        >= 3
    )


def test_permissions_feature_has_no_live_execution_endpoint() -> None:
    forbidden = (
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
    )

    for endpoint in forbidden:
        assert endpoint not in FEATURE


def test_permissions_copy_uses_wallet_account_language() -> None:
    combined = HTML + FEATURE

    assert (
        "Wallet account permissions"
        in combined
    )

    assert (
        "Wallet account"
        in combined
    )

    assert (
        "subaccount"
        not in FEATURE.lower()
    )


def test_permissions_css_does_not_target_frozen_wallet_ui() -> None:
    forbidden = (
        "#walletDepositsWorkspace",
        "#treasuryWithdrawal",
        ".aurora-withdrawal",
        ".aurora-deposit",
        ".wallet-view",
        ".wallet-tab",
    )

    for selector in forbidden:
        assert selector not in CSS
