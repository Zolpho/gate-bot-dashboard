from __future__ import annotations

import re
from html.parser import HTMLParser
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

CSS = (
    ROOT
    / "frontend"
    / "aurora-security.css"
).read_text(
    encoding="utf-8"
)


class Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()

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
        values = dict(
            attrs
        )

        element_id = values.get(
            "id"
        )

        if element_id:
            self.elements[
                element_id
            ] = {
                "tag": tag,
                **values,
            }


def inventory() -> Inventory:
    parser = Inventory()
    parser.feed(HTML)
    return parser


def function_block(
    name: str,
) -> str:
    start = re.search(
        rf"^(?:async\s+)?function\s+"
        rf"{re.escape(name)}\b",
        APP,
        re.MULTILINE,
    )

    if start is None:
        raise AssertionError(
            f"function not found: {name}"
        )

    following = re.search(
        r"^(?:async\s+)?function\s+",
        APP[
            start.end():
        ],
        re.MULTILINE,
    )

    end = (
        start.end()
        + following.start()
        if following
        else len(APP)
    )

    return APP[
        start.start():
        end
    ]


def state_block() -> str:
    start = APP.index(
        "const state = {"
    )

    end = APP.index(
        "\n};",
        start,
    )

    return APP[
        start:end
    ]


def test_ip_card_is_live_security_workspace() -> None:
    document = inventory()

    card = document.elements[
        "securityIpCard"
    ]

    assert card["tag"] == "article"

    assert (
        "security-card-planned"
        not in str(
            card.get(
                "class",
                "",
            )
        ).split()
    )

    for element_id in (
        "securityIpStatus",
        "securityIpObservedAddress",
        "securityIpObservedNetwork",
        "securityIpGlobalEnforcement",
        "securityIpAllowlist",
        "securityIpRefreshButton",
        "securityIpManageButton",
    ):
        assert (
            element_id
            in document.elements
        )

    assert (
        "Planned"
        not in HTML[
            HTML.index(
                'id="securityIpCard"'
            ):
            HTML.index(
                "</article>",
                HTML.index(
                    'id="securityIpCard"'
                ),
            )
        ]
    )


def test_ip_dialog_has_password_confirmed_editor() -> None:
    document = inventory()

    dialog = document.elements[
        "securityIpDialog"
    ]

    form = document.elements[
        "securityIpForm"
    ]

    password = document.elements[
        "securityIpCurrentPassword"
    ]

    enabled = document.elements[
        "securityIpEnabled"
    ]

    assert dialog["tag"] == "dialog"
    assert form["tag"] == "form"

    assert (
        password.get(
            "type"
        )
        == "password"
    )

    assert (
        password.get(
            "autocomplete"
        )
        == "current-password"
    )

    assert (
        enabled.get(
            "type"
        )
        == "checkbox"
    )

    for element_id in (
        "securityIpAddCurrent",
        "securityIpAddNetwork",
        "securityIpEditorRows",
        "securityIpReason",
        "saveSecurityIpPolicy",
    ):
        assert (
            element_id
            in document.elements
        )


def test_rootadmin_recovery_contract_is_present() -> None:
    document = inventory()

    recovery = document.elements[
        "securityIpAdminRecovery"
    ]

    form = document.elements[
        "securityIpRecoveryForm"
    ]

    password = document.elements[
        "securityIpRecoveryPassword"
    ]

    assert (
        "hidden"
        in str(
            recovery.get(
                "class",
                "",
            )
        ).split()
    )

    assert form["tag"] == "form"

    assert (
        password.get(
            "autocomplete"
        )
        == "current-password"
    )

    for element_id in (
        "securityIpRecoveryUsername",
        "securityIpRecoveryReason",
        "securityIpRecoverySubmit",
    ):
        assert (
            element_id
            in document.elements
        )


def test_ip_state_is_memory_only() -> None:
    state = state_block()

    for token in (
        "securityIp: null",
        "securityIpLoading: false",
        "securityIpMutating: false",
        "securityIpDialogEpoch: 0",
    ):
        assert token in state

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert forbidden not in state


def test_ip_loader_is_bearer_read_only_and_stale_safe() -> None:
    loader = function_block(
        "loadSecurityIpRestrictions"
    )

    for token in (
        "'/api/auth/ip-restrictions'",
        "state.adminSessionEpoch",
        "state.adminAuthorization",
        "normalizeSecurityIpResponse(",
        "result?.gate_write_performed",
    ):
        # gate_write_performed validation lives in
        # normalizeSecurityIpResponse(), which the loader calls.
        if token == "result?.gate_write_performed":
            assert token in function_block(
                "normalizeSecurityIpResponse"
            )
        else:
            assert token in loader

    for forbidden in (
        "method: 'POST'",
        "method: 'PUT'",
        "method: 'PATCH'",
        "method: 'DELETE'",
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
    ):
        assert forbidden not in loader


def test_ip_renderer_uses_safe_dynamic_dom() -> None:
    renderer = function_block(
        "renderSecurityIpRestrictions"
    )

    for token in (
        "list.replaceChildren();",
        "document.createElement(",
        "networkValue.textContent",
        "label.textContent",
        "observed_client_ip",
        "observed_client_network",
        "global_enforcement_enabled",
        "'Prepared'",
        "'Enforced'",
    ):
        assert token in renderer

    for forbidden in (
        "innerHTML",
        "insertAdjacentHTML",
        "outerHTML",
    ):
        assert forbidden not in renderer


def test_current_connection_helper_uses_backend_host_network() -> None:
    bind = function_block(
        "bindEvents"
    )

    for token in (
        "'#securityIpAddCurrent'",
        "observed_client_network",
        "'Current connection'",
        "addSecurityIpEditorRow(",
    ):
        assert token in bind

    assert (
        "X-Forwarded-For"
        not in bind
    )

    assert (
        "X-Real-IP"
        not in bind
    )


def test_self_policy_save_is_password_confirmed_configuration_only() -> None:
    save = function_block(
        "submitSecurityIpRestrictions"
    )

    for token in (
        "'/api/auth/ip-restrictions'",
        "method: 'PUT'",
        "current_password:",
        "allowlist,",
        "normalizeSecurityIpResponse(",
        "normalized.enforcement_active",
        "!== false",
        "Global enforcement is still off.",
    ):
        assert token in save

    for forbidden in (
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
    ):
        assert forbidden not in save


def test_rootadmin_recovery_is_disable_only_and_audited_api_flow() -> None:
    recovery = function_block(
        "submitSecurityIpAdminRecovery"
    )

    for token in (
        "state.adminUser.role",
        "!== 'super_admin'",
        "window.confirm(",
        "'/api/auth/ip-restrictions/users/'",
        "+ '/disable'",
        "method: 'POST'",
        "current_password:",
        "reason,",
        "normalizeSecurityIpResponse(",
        "normalized.policy.enabled",
        "normalized.enforcement_active",
    ):
        assert token in recovery

    for forbidden in (
        "method: 'PUT'",
        "method: 'PATCH'",
        "method: 'DELETE'",
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
    ):
        assert forbidden not in recovery


def test_security_overview_loads_ip_after_existing_security_reads() -> None:
    overview = function_block(
        "loadSecurityOverview"
    )

    assert (
        "await loadSecuritySessions({"
        in overview
    )

    assert (
        "await loadSecurityIpRestrictions({"
        in overview
    )

    assert (
        overview.index(
            "await loadSecuritySessions({"
        )
        < overview.index(
            "await loadSecurityIpRestrictions({"
        )
    )


def test_security_clear_resets_ip_state_and_dialog() -> None:
    clear = function_block(
        "clearSecurityState"
    )

    for token in (
        "state.securityIp = null;",
        "state.securityIpLoading = false;",
        "state.securityIpMutating = false;",
        "setSecurityIpError('');",
        "closeSecurityIpDialog({",
        "force: true",
    ):
        assert token in clear


def test_ip_controls_are_bound() -> None:
    bind = function_block(
        "bindEvents"
    )

    for token in (
        "'#securityIpRefreshButton'",
        "refreshSecurityIpRestrictions,",
        "'#securityIpManageButton'",
        "openSecurityIpDialog,",
        "'#securityIpForm'",
        "submitSecurityIpRestrictions,",
        "'#securityIpRecoveryForm'",
        "submitSecurityIpAdminRecovery,",
        "'#closeSecurityIpDialog'",
        "'#cancelSecurityIpDialog'",
    ):
        assert token in bind


def test_ip_ui_copy_is_explicitly_non_enforcing() -> None:
    combined = (
        HTML
        + APP
    )

    for token in (
        "Configuration is not enforcement.",
        "Global IP enforcement is currently off.",
        "does not block access yet.",
        "network identity observed by the backend",
    ):
        assert token in combined


def test_ip_aurora_layout_is_registered_and_responsive() -> None:
    for selector in (
        ".security-card-ip",
        ".security-ip-facts",
        ".security-ip-allowlist",
        ".security-ip-dialog",
        ".security-ip-editor-row",
        ".security-ip-recovery",
    ):
        assert selector in CSS

    assert (
        "@media (max-width: 700px)"
        in CSS
    )

    assert (
        "@media (max-width: 560px)"
        in CSS
    )


def test_ip_ui_uses_only_local_auth_endpoints() -> None:
    blocks = "".join(
        (
            function_block(
                "loadSecurityIpRestrictions"
            ),
            function_block(
                "submitSecurityIpRestrictions"
            ),
            function_block(
                "submitSecurityIpAdminRecovery"
            ),
        )
    )

    assert (
        "/api/auth/ip-restrictions"
        in blocks
    )

    for forbidden in (
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
        "token_hash",
        "credential_fingerprint",
        "totp_secret",
        "recovery_codes",
    ):
        assert forbidden not in blocks

def test_ip_enable_checkbox_has_cross_browser_aurora_geometry() -> None:
    compact = re.sub(
        r"\s+",
        " ",
        CSS,
    )

    selector = (
        'html[data-dashboard-ui="aurora"] '
        '.security-ip-enable '
        'input[type="checkbox"]'
    )

    assert (
        selector
        in compact
    )

    for token in (
        "-webkit-appearance: none;",
        "appearance: none;",
        "flex: 0 0 18px;",
        "width: 18px;",
        "height: 18px;",
        "min-width: 18px;",
        "min-height: 18px;",
        "max-width: 18px;",
        "max-height: 18px;",
        "padding: 0;",
        "box-sizing: border-box;",
        "border-radius: 4px;",
    ):
        assert token in compact

    assert (
        (
            '.security-ip-enable '
            'input[type="checkbox"]:checked'
        )
        in compact
    )

    assert (
        'background-image: url("data:image/svg+xml,'
        in compact
    )

    assert (
        (
            '.security-ip-enable '
            'input[type="checkbox"]:focus-visible'
        )
        in compact
    )
