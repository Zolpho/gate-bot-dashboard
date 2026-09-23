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


def test_active_sessions_card_is_live_read_only_workspace() -> None:
    document = inventory()

    card = document.elements[
        "securitySessionsCard"
    ]

    status = document.elements[
        "securitySessionsStatus"
    ]

    listing = document.elements[
        "securitySessionsList"
    ]

    error = document.elements[
        "securitySessionsError"
    ]

    refresh = document.elements[
        "securitySessionsRefreshButton"
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

    assert status["tag"] == "span"
    assert listing["tag"] == "div"

    assert (
        listing.get(
            "aria-live"
        )
        == "polite"
    )

    assert (
        error.get(
            "role"
        )
        == "alert"
    )

    assert refresh["tag"] == "button"

    assert (
        "Refresh sessions"
        in HTML
    )

    revoke_others = document.elements[
        "securitySessionsRevokeOthersButton"
    ]

    assert (
        revoke_others["tag"]
        == "button"
    )

    assert (
        "Revoke all other sessions"
        in HTML
    )

    assert (
        "Session revocation controls "
        "will be added separately."
        not in HTML
    )


def test_active_sessions_state_is_memory_only() -> None:
    state = state_block()

    for token in (
        "securitySessions: []",
        "securitySessionsLoading: false",
        "securitySessionsMutating: false",
    ):
        assert token in state

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert forbidden not in state


def test_session_loader_is_bearer_read_only_and_stale_safe() -> None:
    loader = function_block(
        "loadSecuritySessions"
    )

    assert (
        "'/api/auth/sessions'"
        in loader
    )

    assert (
        "result.gate_write_performed"
        in loader
    )

    assert (
        "!== false"
        in loader
    )

    for token in (
        "state.adminSessionEpoch",
        "state.adminAuthorization",
        "staleAdminSessionError(error)",
        "state.securitySessions = (",
        "currentCount !== 1",
    ):
        assert token in loader

    for forbidden in (
        "method: 'POST'",
        "method: 'PUT'",
        "method: 'PATCH'",
        "method: 'DELETE'",
        "revoke-others",
        "/revoke",
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
    ):
        assert forbidden not in loader


def test_session_response_is_reduced_to_safe_public_fields() -> None:
    loader = function_block(
        "loadSecuritySessions"
    )

    for token in (
        "id,",
        "auth_method:",
        "mfa_completed:",
        "created_at:",
        "expires_at:",
        "client_ip:",
        "user_agent:",
        "last_seen_at:",
        "current:",
    ):
        assert token in loader

    for forbidden in (
        "token_hash",
        "credential_fingerprint",
        "access_token",
        "recovery_codes",
        "totp_secret",
    ):
        assert forbidden not in loader


def test_session_renderer_uses_text_nodes_for_untrusted_metadata() -> None:
    renderer = function_block(
        "renderSecuritySessions"
    )

    for token in (
        "document.createElement(",
        "list.replaceChildren();",
        "session.client_ip",
        "session.user_agent",
        "session.created_at",
        "session.last_seen_at",
        "session.expires_at",
        "value.textContent = valueText;",
        "userAgentValue.title = (",
        "row.dataset.sessionId",
        "'current'",
    ):
        assert token in renderer

    assert (
        "innerHTML"
        not in renderer
    )

    assert (
        "insertAdjacentHTML"
        not in renderer
    )

    assert (
        "outerHTML"
        not in renderer
    )


def test_older_sessions_have_explicit_missing_metadata_copy() -> None:
    renderer = function_block(
        "renderSecuritySessions"
    )

    assert (
        renderer.count(
            "'Not recorded (older session)'"
        )
        == 2
    )

    assert (
        "'Not recorded'"
        in function_block(
            "securitySessionDate"
        )
    )


def test_session_auth_method_and_mfa_are_visible() -> None:
    method = function_block(
        "securitySessionMethodLabel"
    )

    for token in (
        "password_totp:",
        "'Password + Authenticator'",
        "password_recovery:",
        "'Password + recovery code'",
        "passkey:",
    ):
        assert token in method

    renderer = function_block(
        "renderSecuritySessions"
    )

    for token in (
        "session.mfa_completed",
        "methodLabel",
        "MFA verified",
    ):
        assert token in renderer


def test_security_overview_loads_sessions_after_totp_status() -> None:
    overview = function_block(
        "loadSecurityOverview"
    )

    assert (
        "await loadSecuritySessions({"
        in overview
    )

    assert (
        "quiet,"
        in overview
    )

    assert (
        overview.index(
            "'/api/auth/mfa/totp'"
        )
        < overview.index(
            "await loadSecuritySessions({"
        )
    )


def test_security_clear_removes_session_state() -> None:
    clear = function_block(
        "clearSecurityState"
    )

    for token in (
        "state.securitySessions = [];",
        "state.securitySessionsLoading = false;",
        "setSecuritySessionsError('');",
    ):
        assert token in clear


def test_manual_refresh_is_read_only_and_bound() -> None:
    refresh = function_block(
        "refreshSecuritySessions"
    )

    assert (
        "loadSecuritySessions({"
        in refresh
    )

    assert (
        "quiet: false"
        in refresh
    )

    bind = function_block(
        "bindEvents"
    )

    for token in (
        "'#securitySessionsRefreshButton'",
        "refreshSecuritySessions,",
    ):
        assert token in bind


def test_individual_session_revocation_is_audited_api_flow() -> None:
    revoke = function_block(
        "revokeSecuritySession"
    )

    for token in (
        "window.confirm(",
        "'/api/auth/sessions/'",
        "+ `${session.id}/revoke`",
        "method: 'POST'",
        "result?.status !== 'revoked'",
        "result?.gate_write_performed",
        "revoked?.current",
        "revoked?.revoked_at",
        "state.securitySessionsMutating = true;",
    ):
        assert token in revoke

    for forbidden in (
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
    ):
        assert forbidden not in revoke


def test_current_session_revocation_forces_local_logout() -> None:
    revoke = function_block(
        "revokeSecuritySession"
    )

    current_branch = revoke[
        revoke.index(
            "if (current) {"
        ):
    ]

    for token in (
        "lockAdmin(false);",
        "switchTab(",
        "'overview'",
        "openAdminDialog();",
        "Sign in again.",
    ):
        assert token in current_branch

    assert (
        current_branch.index(
            "lockAdmin(false);"
        )
        < current_branch.index(
            "openAdminDialog();"
        )
    )


def test_other_session_revocation_preserves_current_browser() -> None:
    revoke = function_block(
        "revokeSecuritySession"
    )

    assert (
        "state.securitySessions.filter("
        in revoke
    )

    assert (
        "item.id !== session.id"
        in revoke
    )

    assert (
        "'Session revoked.'"
        in revoke
    )


def test_revoke_all_others_preserves_current_session() -> None:
    revoke = function_block(
        "revokeOtherSecuritySessions"
    )

    for token in (
        "window.confirm(",
        "'/api/auth/sessions/revoke-others'",
        "method: 'POST'",
        "result?.status !== 'revoked'",
        "result?.gate_write_performed",
        "current_session_id",
        "revoked_session_ids",
        "revoked_count",
        "state.securitySessions = [",
        "current,",
    ):
        assert token in revoke

    assert (
        "revokedIds.includes("
        in revoke
    )

    assert (
        "current.id"
        in revoke
    )


def test_session_mutations_are_stale_safe_and_serialized() -> None:
    for name in (
        "revokeSecuritySession",
        "revokeOtherSecuritySessions",
    ):
        operation = function_block(
            name
        )

        for token in (
            "state.securitySessionsMutating",
            "state.adminSessionEpoch",
            "state.adminAuthorization",
            "staleAdminSessionError(error)",
        ):
            assert token in operation

    renderer = function_block(
        "renderSecuritySessions"
    )

    for token in (
        "state.securitySessionsMutating",
        "revokeButton.disabled",
        "revokeOthers.disabled",
        "refresh.disabled",
    ):
        assert token in renderer


def test_session_action_buttons_use_safe_dynamic_dom() -> None:
    renderer = function_block(
        "renderSecuritySessions"
    )

    for token in (
        "document.createElement('button')",
        "revokeButton.type = 'button';",
        "'Sign out this session'",
        "'Revoke session'",
        "revokeButton.addEventListener(",
        "void revokeSecuritySession(",
    ):
        assert token in renderer

    for forbidden in (
        "innerHTML",
        "insertAdjacentHTML",
        "outerHTML",
    ):
        assert forbidden not in renderer


def test_bulk_revoke_button_is_bound() -> None:
    bind = function_block(
        "bindEvents"
    )

    for token in (
        "'#securitySessionsRevokeOthersButton'",
        "revokeOtherSecuritySessions,",
    ):
        assert token in bind


def test_security_clear_resets_mutation_state() -> None:
    clear = function_block(
        "clearSecurityState"
    )

    assert (
        "state.securitySessionsMutating = false;"
        in clear
    )


def test_session_revocation_frontend_uses_only_session_api() -> None:
    mutation_blocks = "".join(
        (
            function_block(
                "revokeSecuritySession"
            ),
            function_block(
                "revokeOtherSecuritySessions"
            ),
        )
    )

    assert (
        "/api/auth/sessions/"
        in mutation_blocks
    )

    assert (
        "/api/auth/sessions/revoke-others"
        in mutation_blocks
    )

    for forbidden in (
        "/api/treasury/",
        "/api/trading/",
        "/api/bot-control/",
        "/api/bots/",
        "/api/sync",
        "token_hash",
        "credential_fingerprint",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert forbidden not in mutation_blocks


def test_active_sessions_aurora_layout_is_registered() -> None:
    for selector in (
        ".security-card-sessions",
        ".security-session-list",
        ".security-session-row",
        ".security-session-heading",
        ".security-session-facts",
        ".security-session-user-agent",
        ".security-session-empty",
    ):
        assert selector in CSS

    assert (
        "grid-column: 1 / -1;"
        in CSS
    )

    assert (
        "@media (max-width: 920px)"
        in CSS
    )

    assert (
        "@media (max-width: 560px)"
        in CSS
    )
