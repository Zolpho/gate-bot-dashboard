from __future__ import annotations

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


class Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()

        self.elements: dict[
            str,
            dict[str, str | None],
        ] = {}

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

        if tag == "script":
            self.scripts.append(
                values
            )


def inventory() -> Inventory:
    parser = Inventory()
    parser.feed(
        HTML
    )
    return parser


def block(
    start: str,
    end: str,
) -> str:
    begin = APP.index(
        start
    )

    finish = APP.index(
        end,
        begin,
    )

    return APP[
        begin:finish
    ]


def test_frontend_no_longer_constructs_basic_authorization() -> None:
    assert (
        "function basicAuthorization("
        not in APP
    )

    assert (
        "function bearerAuthorization("
        in APP
    )

    bearer = block(
        "function bearerAuthorization(",
        "\n\nfunction setAdminError(",
    )

    assert (
        "return `Bearer ${normalized}`;"
        in bearer
    )


def test_password_login_uses_password_login_api() -> None:
    login = block(
        "async function unlockAdmin(",
        "\n\nasync function completeAdminMfa(",
    )

    assert (
        "'/api/auth/login'"
        in login
    )

    assert (
        "method: 'POST'"
        in login
    )

    assert (
        "username,"
        in login
    )

    assert (
        "password,"
        in login
    )

    assert (
        "result.status === 'mfa_required'"
        in login
    )

    assert (
        "openAdminMfaDialog(result);"
        in login
    )

    assert (
        "bearerAuthorization("
        in login
    )

    assert (
        "/api/auth/me"
        not in login
    )


def test_mfa_completion_uses_challenge_api() -> None:
    mfa = block(
        "async function completeAdminMfa(",
        "\n\nasync function changeOwnPassword(",
    )

    for token in (
        "'/api/auth/login/mfa'",
        "challenge_token: challenge",
        "method,",
        "code,",
        "bearerAuthorization(",
        "state.adminAuthorization = authorization;",
        "state.adminUser = result.user;",
    ):
        assert token in mfa


def test_auth_secrets_remain_in_memory_in_auth_flow() -> None:
    sensitive = "".join(
        (
            block(
                "function lockAdmin(",
                "\n\nasync function logoutAdmin(",
            ),
            block(
                "async function logoutAdmin(",
                "\n\nasync function unlockAdmin(",
            ),
            block(
                "async function unlockAdmin(",
                "\n\nasync function completeAdminMfa(",
            ),
            block(
                "async function completeAdminMfa(",
                "\n\nasync function changeOwnPassword(",
            ),
        )
    )

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert forbidden not in sensitive

    assert (
        "adminMfaChallenge: ''"
        in APP
    )

    assert (
        "adminMfaMethods: []"
        in APP
    )


def test_mfa_dialog_has_required_controls() -> None:
    document = inventory()

    dialog = document.elements[
        "adminMfaDialog"
    ]

    form = document.elements[
        "adminMfaForm"
    ]

    method = document.elements[
        "adminMfaMethod"
    ]

    submit = document.elements[
        "adminMfaSubmitButton"
    ]

    error = document.elements[
        "adminMfaError"
    ]

    assert (
        dialog["tag"]
        == "dialog"
    )

    assert (
        form["tag"]
        == "form"
    )

    assert (
        method["tag"]
        == "select"
    )

    assert (
        submit["tag"]
        == "button"
    )

    assert (
        error.get(
            "role"
        )
        == "alert"
    )

    assert (
        'autocomplete="one-time-code"'
        in HTML
    )


def test_mfa_supports_authenticator_and_recovery() -> None:
    helper = block(
        "function openAdminMfaDialog(",
        "\n\nfunction cancelAdminMfa(",
    )

    assert (
        "value === 'totp'"
        in helper
    )

    assert (
        "value === 'recovery'"
        in helper
    )

    assert (
        "'Authenticator code'"
        in helper
    )

    assert (
        "'Recovery code'"
        in helper
    )


def test_lock_account_revokes_bearer_before_local_clear() -> None:
    logout = block(
        "async function logoutAdmin(",
        "\n\nasync function unlockAdmin(",
    )

    assert (
        "'/api/auth/logout'"
        in logout
    )

    assert (
        "method: 'POST'"
        in logout
    )

    assert (
        "Authorization: authorization"
        in logout
    )

    assert (
        "lockAdmin(false);"
        in logout
    )

    assert (
        logout.index(
            "'/api/auth/logout'"
        )
        < logout.index(
            "lockAdmin(false);"
        )
    )


def test_lock_clears_pending_mfa_and_private_state() -> None:
    lock = block(
        "function lockAdmin(",
        "\n\nasync function logoutAdmin(",
    )

    for token in (
        "state.adminSessionEpoch += 1;",
        "state.adminAuthorization = '';",
        "state.adminUser = null;",
        "clearPendingAdminMfa();",
        "clearPrivateBalance();",
        "clearBotControlSession();",
        "clearTreasurySession();",
    ):
        assert token in lock


def test_password_change_ends_browser_session() -> None:
    change = block(
        "async function changeOwnPassword(",
        "\n\nfunction showToast(",
    )

    assert (
        "basicAuthorization("
        not in change
    )

    assert (
        "lockAdmin(false);"
        in change
    )

    assert (
        "Password changed successfully. Sign in again."
        in change
    )


def test_admin_api_still_uses_single_authorization_seam() -> None:
    admin_api = block(
        "function adminApi(",
        "\n\nfunction staleAdminSessionError(",
    )

    assert (
        "const authorization = state.adminAuthorization;"
        in admin_api
    )

    assert (
        "Authorization: authorization"
        in admin_api
    )

    assert (
        "state.adminAuthorization !== authorization"
        in admin_api
    )


def test_app_script_cache_bust_is_additive() -> None:
    document = inventory()

    sources = [
        item.get(
            "src",
            "",
        )
        for item in document.scripts
        if item.get(
            "src"
        )
    ]

    app_sources = [
        source
        for source in sources
        if source.startswith(
            "./app.js?"
        )
    ]

    assert app_sources == [
        (
            "./app.js?"
            "v=20260912-bot-control-live-ux-a7c240-v1"
            "&a7c486=20260913-account-permissions-v1"
            "&a7c488=20260919-bearer-auth-r2f2a-v1"
        )
    ]


def test_login_copy_describes_authenticated_memory_session() -> None:
    assert (
        "Your authenticated session stays in memory "
        "until this page is refreshed or locked."
        in HTML
    )
