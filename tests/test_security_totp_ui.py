from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re


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


class DocumentInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()

        self.elements: dict[
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

        if tag == "link":
            self.links.append(
                values
            )

        if tag == "script":
            self.scripts.append(
                values
            )


def inventory() -> DocumentInventory:
    parser = DocumentInventory()

    parser.feed(
        HTML
    )

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
        APP[start.end():],
        re.MULTILINE,
    )

    end = (
        start.end()
        + following.start()
        if following
        else len(APP)
    )

    return APP[
        start.start():end
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


def test_security_navigation_is_authenticated_workspace() -> None:
    document = inventory()

    nav = document.elements[
        "securityNavItem"
    ]

    panel = document.elements[
        "tab-security"
    ]

    assert nav["tag"] == "button"

    assert (
        nav.get("data-tab")
        == "security"
    )

    assert (
        nav.get("aria-controls")
        == "tab-security"
    )

    assert (
        "hidden"
        in str(
            nav.get("class", "")
        ).split()
    )

    assert panel["tag"] == "section"

    render = function_block(
        "renderAdminState"
    )

    for token in (
        "const securityNavItem",
        "securityNavItem?.classList.toggle(",
        "securityNavItem?.setAttribute(",
        "securityNavItem.tabIndex",
        "state.activeTab === 'security'",
    ):
        assert token in render

    switch = function_block(
        "switchTab"
    )

    for token in (
        "security: ['Security'",
        "'security'",
        "target === 'security'",
        "loadSecurityOverview({",
    ):
        assert token in switch

    assert (
        switch.index(
            "target === 'security'"
        )
        < switch.index(
            "loadSecurityOverview({"
        )
    )


def test_security_aurora_stylesheet_is_registered() -> None:
    document = inventory()

    stylesheets = [
        item
        for item in document.links
        if (
            item.get(
                "href",
                "",
            ).split("?")[0]
            == "./aurora-security.css"
        )
    ]

    assert len(
        stylesheets
    ) == 1

    stylesheet = stylesheets[0]

    assert (
        stylesheet.get(
            "data-dashboard-ui-stylesheet"
        )
        == "aurora"
    )

    assert (
        "disabled"
        in stylesheet
    )

    assert (
        'html[data-dashboard-ui="aurora"]'
        in CSS
    )

    for selector in (
        "#tab-security",
        ".security-grid",
        ".security-card",
        ".security-totp-dialog",
        ".security-totp-stage",
        ".security-totp-recovery-codes",
    ):
        assert selector in CSS


def test_security_totp_dialog_dom_contract() -> None:
    document = inventory()

    dialog = document.elements[
        "securityTotpDialog"
    ]

    enroll = document.elements[
        "securityTotpEnrollForm"
    ]

    password = document.elements[
        "securityTotpCurrentPassword"
    ]

    verify = document.elements[
        "securityTotpConfirmForm"
    ]

    code = document.elements[
        "securityTotpVerificationCode"
    ]

    recovery = document.elements[
        "securityTotpRecoveryStage"
    ]

    recovery_codes = (
        document.elements[
            "securityTotpRecoveryCodes"
        ]
    )

    assert dialog["tag"] == "dialog"
    assert enroll["tag"] == "form"
    assert verify["tag"] == "form"

    assert (
        password.get("type")
        == "password"
    )

    assert (
        password.get("autocomplete")
        == "current-password"
    )

    assert (
        code.get("inputmode")
        == "numeric"
    )

    assert (
        code.get("autocomplete")
        == "one-time-code"
    )

    assert (
        code.get("pattern")
        == "[0-9]{6}"
    )

    assert (
        code.get("minlength")
        == "6"
    )

    assert (
        code.get("maxlength")
        == "6"
    )

    assert (
        "hidden"
        in str(
            recovery.get(
                "class",
                "",
            )
        ).split()
    )

    assert (
        recovery_codes["tag"]
        == "pre"
    )


def test_security_status_loader_is_read_only() -> None:
    loader = function_block(
        "loadSecurityOverview"
    )

    assert (
        "'/api/auth/mfa/totp'"
        in loader
    )

    assert (
        "state.securityTotp = result;"
        in loader
    )

    assert (
        "state.adminSessionEpoch"
        in loader
    )

    assert (
        "state.adminAuthorization"
        in loader
    )

    assert (
        "method: 'POST'"
        not in loader
    )

    assert (
        "/api/auth/mfa/totp/enroll"
        not in loader
    )

    assert (
        "/api/auth/mfa/totp/confirm"
        not in loader
    )


def test_totp_enrollment_requires_password_and_clears_dom() -> None:
    enroll = function_block(
        "beginSecurityTotpEnrollment"
    )

    assert (
        "'/api/auth/mfa/totp/enroll'"
        in enroll
    )

    assert (
        "method: 'POST'"
        in enroll
    )

    assert (
        "current_password:"
        in enroll
    )

    assert (
        "currentPassword"
        in enroll
    )

    assert (
        "state.adminSessionEpoch"
        in enroll
    )

    assert (
        "state.adminAuthorization"
        in enroll
    )

    password_clear = enroll.index(
        "passwordInput.value = '';"
    )

    endpoint = enroll.index(
        "/api/auth/mfa/totp/enroll"
    )

    secret_render = enroll.index(
        "secretElement.textContent = secret;"
    )

    qr_render = enroll.index(
        "qr.src = qrDataUri;"
    )

    assert (
        password_clear
        < endpoint
        < secret_render
    )

    assert endpoint < qr_render

    for token in (
        "result.status !== 'pending'",
        "result.factor?.totp_enabled",
        "data:image/png;base64,",
        "confirmButton.disabled = false;",
    ):
        assert token in enroll


def test_totp_confirmation_sanitizes_recovery_response() -> None:
    confirm = function_block(
        "submitSecurityTotpConfirmation"
    )

    assert (
        "'/api/auth/mfa/totp/confirm'"
        in confirm
    )

    assert (
        "method: 'POST'"
        in confirm
    )

    assert (
        "/^[0-9]{6}$/.test(code)"
        in confirm
    )

    code_clear = confirm.index(
        "codeInput.value = '';"
    )

    endpoint = confirm.index(
        "/api/auth/mfa/totp/confirm"
    )

    assert code_clear < endpoint

    for token in (
        "result.status !== 'enabled'",
        "result.factor?.totp_enabled",
        "result.recovery_codes",
        "result.recovery_code_count",
        "recoveryCodes.length < 1",
        "recoveryCount",
    ):
        assert token in confirm

    assert (
        "state.securityTotp = result"
        not in confirm
    )

    assert (
        "state.securityTotp = {"
        in confirm
    )

    assert (
        "factor: result.factor"
        in confirm
    )

    assert (
        "mfa_required:"
        in confirm
    )

    assert (
        "gate_write_performed:"
        in confirm
    )

    qr_clear = confirm.index(
        "qr.removeAttribute('src');"
    )

    secret_clear = confirm.index(
        "secretElement.textContent = '—';"
    )

    recovery_render = confirm.index(
        "recoveryElement.textContent = ("
    )

    recovery_show = confirm.index(
        "recoveryStage.classList.remove("
    )

    assert (
        qr_clear
        < recovery_render
        < recovery_show
    )

    assert (
        secret_clear
        < recovery_render
    )

    assert (
        r"recoveryCodes.join('\n')"
        in confirm
    )


def test_totp_plaintext_never_enters_global_state() -> None:
    state = state_block()

    for forbidden in (
        "securityTotpCurrentPassword",
        "securityTotpSecret",
        "securityTotpVerificationCode",
        "securityTotpRecoveryCodes",
        "recovery_codes",
        "recoveryCodes",
    ):
        assert forbidden not in state

    assert (
        "securityTotp: null"
        in state
    )

    assert (
        "securityTotpLoading: false"
        in state
    )


def test_totp_sensitive_data_cleanup_reaches_all_exit_paths() -> None:
    clear = function_block(
        "clearSecurityTotpSensitiveState"
    )

    for token in (
        "enrollForm?.reset();",
        "confirmForm?.reset();",
        "qr.removeAttribute('src');",
        "secret.textContent = '—';",
        "recoveryCodes.textContent = '';",
        "'#securityTotpVerifyStage'",
        "'#securityTotpRecoveryStage'",
    ):
        assert token in clear

    close = function_block(
        "closeSecurityTotpDialog"
    )

    assert (
        "clearSecurityTotpSensitiveState();"
        in close
    )

    finish = function_block(
        "finishSecurityTotpSetup"
    )

    assert (
        "closeSecurityTotpDialog({"
        in finish
    )

    assert (
        "force: true"
        in finish
    )

    security_clear = function_block(
        "clearSecurityState"
    )

    assert (
        "closeSecurityTotpDialog({"
        in security_clear
    )

    assert (
        "force: true"
        in security_clear
    )

    lock = function_block(
        "lockAdmin"
    )

    assert (
        "clearSecurityState();"
        in lock
    )


def test_totp_copy_actions_are_explicit() -> None:
    secret_copy = function_block(
        "copySecurityTotpSecret"
    )

    recovery_copy = function_block(
        "copySecurityTotpRecoveryCodes"
    )

    helper = function_block(
        "copySecuritySensitiveText"
    )

    assert (
        "copySecuritySensitiveText("
        in secret_copy
    )

    assert (
        "copySecuritySensitiveText("
        in recovery_copy
    )

    assert (
        "navigator.clipboard.writeText("
        in helper
    )

    assert (
        "document.execCommand("
        in helper
    )

    bind = function_block(
        "bindEvents"
    )

    for token in (
        "'#copySecurityTotpSecret'",
        "copySecurityTotpSecret,",
        "'#copySecurityTotpRecoveryCodes'",
        "copySecurityTotpRecoveryCodes,",
        "'#finishSecurityTotpSetup'",
        "finishSecurityTotpSetup,",
    ):
        assert token in bind


def test_totp_dialog_close_paths_are_wired() -> None:
    bind = function_block(
        "bindEvents"
    )

    for token in (
        "'#securityTotpSetupButton'",
        "openSecurityTotpDialog,",
        "'#securityTotpEnrollForm'",
        "beginSecurityTotpEnrollment,",
        "'#securityTotpConfirmForm'",
        "submitSecurityTotpConfirmation,",
        "'#closeSecurityTotpDialog'",
        "'#cancelSecurityTotpEnroll'",
        "'#cancelSecurityTotpConfirm'",
        "'cancel'",
        "closeSecurityTotpDialog();",
    ):
        assert token in bind


def test_security_change_password_reuses_existing_workflow() -> None:
    bind = function_block(
        "bindEvents"
    )

    assert (
        "'#securityChangePasswordButton'"
        in bind
    )

    assert (
        "openChangePasswordDialog,"
        in bind
    )


def test_totp_frontend_write_surface_is_exact_and_gate_free() -> None:
    assert (
        APP.count(
            "/api/auth/mfa/totp/enroll"
        )
        == 1
    )

    assert (
        APP.count(
            "/api/auth/mfa/totp/confirm"
        )
        == 1
    )

    security_blocks = "".join(
        (
            function_block(
                "loadSecurityOverview"
            ),
            function_block(
                "beginSecurityTotpEnrollment"
            ),
            function_block(
                "submitSecurityTotpConfirmation"
            ),
        )
    )

    for forbidden in (
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
    ):
        assert forbidden not in security_blocks


def test_totp_browser_flow_uses_no_persistent_storage() -> None:
    security_blocks = "".join(
        (
            function_block(
                "clearSecurityTotpSensitiveState"
            ),
            function_block(
                "openSecurityTotpDialog"
            ),
            function_block(
                "beginSecurityTotpEnrollment"
            ),
            function_block(
                "submitSecurityTotpConfirmation"
            ),
            function_block(
                "copySecuritySensitiveText"
            ),
        )
    )

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert forbidden not in security_blocks


def test_totp_async_responses_are_bound_to_dialog_generation() -> None:
    state = state_block()

    assert (
        "securityTotpDialogEpoch: 0"
        in state
    )

    current = function_block(
        "securityTotpDialogIsCurrent"
    )

    for token in (
        "dialog?.open",
        "state.securityTotpDialogEpoch",
        "=== dialogEpoch",
        "state.adminSessionEpoch",
        "=== sessionEpoch",
        "state.adminAuthorization",
        "=== authorization",
    ):
        assert token in current

    opener = function_block(
        "openSecurityTotpDialog"
    )

    closer = function_block(
        "closeSecurityTotpDialog"
    )

    assert (
        "state.securityTotpDialogEpoch += 1;"
        in opener
    )

    assert (
        "state.securityTotpDialogEpoch += 1;"
        in closer
    )

    for name in (
        "beginSecurityTotpEnrollment",
        "submitSecurityTotpConfirmation",
    ):
        operation = function_block(
            name
        )

        assert (
            "const dialogEpoch = ("
            in operation
        )

        assert (
            "state.securityTotpDialogEpoch"
            in operation
        )

        # Success, catch and finally must all be
        # tied to the same dialog generation.
        assert (
            operation.count(
                "securityTotpDialogIsCurrent({"
            )
            >= 3
        )

        endpoint = (
            "/api/auth/mfa/totp/enroll"
            if name
            == "beginSecurityTotpEnrollment"
            else "/api/auth/mfa/totp/confirm"
        )

        assert endpoint in operation

        post_request = operation[
            operation.index(endpoint):
        ]

        assert (
            "securityTotpDialogIsCurrent({"
            in post_request
        )


def test_recovery_codes_require_explicit_acknowledgement_to_close() -> None:
    guard = function_block(
        "securityTotpRecoveryCodesAwaitingAcknowledgement"
    )

    assert (
        "'#securityTotpRecoveryStage'"
        in guard
    )

    assert (
        "classList.contains("
        in guard
    )

    assert (
        "'hidden'"
        in guard
    )

    closer = function_block(
        "closeSecurityTotpDialog"
    )

    for token in (
        "options = {}",
        "const force = Boolean(",
        "!force",
        "securityTotpRecoveryCodesAwaitingAcknowledgement()",
        "I saved these codes",
        "return false;",
    ):
        assert token in closer

    guard_position = closer.index(
        "securityTotpRecoveryCodesAwaitingAcknowledgement()"
    )

    invalidation_position = closer.index(
        "state.securityTotpDialogEpoch += 1;"
    )

    cleanup_position = closer.index(
        "clearSecurityTotpSensitiveState();"
    )

    assert (
        guard_position
        < invalidation_position
        < cleanup_position
    )

    finish = function_block(
        "finishSecurityTotpSetup"
    )

    assert (
        "closeSecurityTotpDialog({"
        in finish
    )

    assert (
        "force: true"
        in finish
    )

    clear = function_block(
        "clearSecurityState"
    )

    assert (
        "closeSecurityTotpDialog({"
        in clear
    )

    assert (
        "force: true"
        in clear
    )

    bind = function_block(
        "bindEvents"
    )

    # Normal X / Escape / backdrop flows remain
    # unforced and therefore hit the recovery guard.
    assert (
        "'#closeSecurityTotpDialog'"
        in bind
    )

    assert (
        "'cancel'"
        in bind
    )

    assert (
        "event.target"
        in bind
    )


def test_security_assets_have_final_r4a2c3_cache_busts() -> None:
    document = inventory()

    app_sources = [
        str(
            item.get(
                "src",
                "",
            )
        )
        for item in document.scripts
        if str(
            item.get(
                "src",
                "",
            )
        ).startswith(
            "./app.js?"
        )
    ]

    security_styles = [
        str(
            item.get(
                "href",
                "",
            )
        )
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
        == "./aurora-security.css"
    ]

    assert app_sources == [
        (
            "./app.js?"
            "v=20260912-bot-control-live-ux-a7c240-v1"
            "&a7c486=20260913-account-permissions-v1"
            "&a7c488=20260922-login-startup-hotfix-v1"
            "&a7c488copy=20260922-authenticator-copy-v1"
        )
    ]

    assert security_styles == [
        (
            "./aurora-security.css?"
            "v=20260920-security-totp-r4a2c3-v1"
        )
    ]

    assert (
        "20260920-bearer-init-cleanup-r3b4e-v1"
        not in HTML
    )

    assert (
        "20260920-security-page-r4a2a-v1"
        not in HTML
    )

def test_removed_legacy_change_password_control_is_startup_safe() -> None:
    document = inventory()

    assert (
        "changePasswordButton"
        not in document.elements
    )

    assert (
        "securityChangePasswordButton"
        in document.elements
    )

    admin_state = function_block(
        "renderAdminState"
    )

    assert (
        "changePasswordButton?.classList.toggle("
        in admin_state
    )

    assert (
        "changePasswordButton?.classList.add("
        in admin_state
    )

    assert (
        "changePasswordButton.classList"
        not in admin_state
    )

    assert (
        "$('#changePasswordButton')?.addEventListener("
        in APP
    )

    assert (
        "$('#changePasswordButton').addEventListener("
        not in APP
    )


def test_required_direct_event_bindings_have_dom_targets() -> None:
    document = inventory()

    required_ids = set(
        re.findall(
            r"\$\('#([^']+)'\)"
            r"\.addEventListener\(",
            APP,
        )
    )

    missing = sorted(
        required_ids
        - set(
            document.elements
        )
    )

    assert missing == []

def test_authenticator_available_copy_describes_live_enrollment() -> None:
    security_render = function_block(
        "renderSecurityPage"
    )

    assert (
        "'Authenticator setup is available for '"
        in security_render
    )

    assert (
        "+ 'this account. Use Set up Authenticator '"
        in security_render
    )

    assert (
        "+ 'to add two-step verification.'"
        in security_render
    )

    assert (
        "Enrollment controls"
        not in security_render
    )

    assert (
        "will be wired in the next security step."
        not in security_render
    )
