from __future__ import annotations

import ast
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth_mfa import (
    complete_totp_enrollment_with_recovery,
)
from app.auth_state import (
    generate_auth_encryption_key,
)
from app.auth_totp import (
    begin_totp_enrollment,
)
from app.config import (
    Settings,
    get_settings,
)
from app.db import (
    init_db,
    session_scope,
)
from app.main import app
from app.models import (
    DashboardAuthChallenge,
    DashboardAuthEvent,
    DashboardAuthFactor,
    DashboardAuthIpAllowlistEntry,
    DashboardAuthIpPolicy,
    DashboardAuthRateLimitEvent,
    DashboardAuthRecoveryCode,
    DashboardAuthSession,
)
from app.security import hash_password

USERNAME = "ip-integration-user"
PASSWORD = "password-test-123"

ALLOWED_IP = "192.0.2.10"
DENIED_IP = "198.51.100.10"


def _settings(
    tmp_path,
    *,
    enforcement: bool,
) -> Settings:
    users_path = (
        tmp_path
        / "dashboard_users.json"
    )

    users_path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username":
                            USERNAME,
                        "password_hash":
                            hash_password(
                                PASSWORD,
                                iterations=100_000,
                            ),
                        "account_ids": [
                            USERNAME,
                        ],
                        "role":
                            "account_operator",
                        "enabled":
                            True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    key_path = (
        tmp_path
        / "dashboard_auth.key"
    )

    key_path.write_text(
        generate_auth_encryption_key()
        + "\n",
        encoding="ascii",
    )

    key_path.chmod(
        0o600
    )

    return Settings(
        dashboard_users_file=(
            users_path
        ),
        dashboard_auth_encryption_key_file=(
            key_path
        ),
        dashboard_auth_rate_limit_enabled=False,
        dashboard_mfa_required=False,
        dashboard_ip_restrictions_enforcement_enabled=(
            enforcement
        ),
    )


def _clear() -> None:
    with session_scope() as db:
        db.execute(
            delete(
                DashboardAuthIpAllowlistEntry
            ).where(
                DashboardAuthIpAllowlistEntry
                .username
                == USERNAME
            )
        )

        db.execute(
            delete(
                DashboardAuthIpPolicy
            ).where(
                DashboardAuthIpPolicy
                .username
                == USERNAME
            )
        )

        for model in (
            DashboardAuthRecoveryCode,
            DashboardAuthSession,
            DashboardAuthChallenge,
            DashboardAuthFactor,
        ):
            db.execute(
                delete(
                    model
                ).where(
                    model.username
                    == USERNAME
                )
            )

        db.execute(
            delete(
                DashboardAuthEvent
            ).where(
                DashboardAuthEvent
                .target_username
                == USERNAME
            )
        )

        db.execute(
            delete(
                DashboardAuthRateLimitEvent
            )
        )


def _seed_policy(
    *,
    enabled: bool = True,
    network: str = (
        ALLOWED_IP
        + "/32"
    ),
) -> None:
    with session_scope() as db:
        db.add(
            DashboardAuthIpPolicy(
                username=USERNAME,
                enabled=enabled,
                updated_by=USERNAME,
            )
        )

        db.flush()

        db.add(
            DashboardAuthIpAllowlistEntry(
                username=USERNAME,
                network=network,
                label="Allowed network",
            )
        )


def _bearer(
    token: str,
) -> dict[str, str]:
    return {
        "Authorization":
            f"Bearer {token}",
    }


def _basic() -> dict[str, str]:
    encoded = base64.b64encode(
        (
            f"{USERNAME}:{PASSWORD}"
        ).encode()
    ).decode(
        "ascii"
    )

    return {
        "Authorization":
            f"Basic {encoded}",
    }


def _session_rows() -> list[
    DashboardAuthSession
]:
    with session_scope() as db:
        return list(
            db.scalars(
                select(
                    DashboardAuthSession
                ).where(
                    DashboardAuthSession
                    .username
                    == USERNAME
                )
            )
        )


def _challenge_rows() -> list[
    DashboardAuthChallenge
]:
    with session_scope() as db:
        return list(
            db.scalars(
                select(
                    DashboardAuthChallenge
                ).where(
                    DashboardAuthChallenge
                    .username
                    == USERNAME
                )
            )
        )


def test_global_arm_off_preserves_existing_login_behavior(
    tmp_path,
) -> None:
    init_db()
    _clear()

    settings = _settings(
        tmp_path,
        enforcement=False,
    )

    _seed_policy()

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app,
            client=(
                DENIED_IP,
                50000,
            ),
        ) as client:
            response = client.post(
                "/api/auth/login",
                json={
                    "username":
                        USERNAME,
                    "password":
                        PASSWORD,
                },
            )

        assert (
            response.status_code
            == 200
        )

        assert (
            response.json()[
                "status"
            ]
            == "authenticated"
        )

        assert len(
            _session_rows()
        ) == 1

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )

        _clear()


def test_password_login_denies_mismatch_before_session_or_challenge(
    tmp_path,
) -> None:
    init_db()
    _clear()

    settings = _settings(
        tmp_path,
        enforcement=True,
    )

    _seed_policy()

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app,
            client=(
                DENIED_IP,
                50000,
            ),
        ) as client:
            response = client.post(
                "/api/auth/login",
                headers={
                    "X-Forwarded-For":
                        ALLOWED_IP,
                    "X-Real-IP":
                        ALLOWED_IP,
                },
                json={
                    "username":
                        USERNAME,
                    "password":
                        PASSWORD,
                },
            )

        assert (
            response.status_code
            == 403
        )

        assert (
            response.json()[
                "detail"
            ]
            == "IP access denied"
        )

        assert _session_rows() == []
        assert _challenge_rows() == []

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )

        _clear()


def test_password_login_allows_matching_network(
    tmp_path,
) -> None:
    init_db()
    _clear()

    settings = _settings(
        tmp_path,
        enforcement=True,
    )

    _seed_policy()

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app,
            client=(
                ALLOWED_IP,
                50000,
            ),
        ) as client:
            response = client.post(
                "/api/auth/login",
                json={
                    "username":
                        USERNAME,
                    "password":
                        PASSWORD,
                },
            )

        assert (
            response.status_code
            == 200
        )

        body = response.json()

        assert (
            body[
                "status"
            ]
            == "authenticated"
        )

        assert body[
            "access_token"
        ]

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )

        _clear()


def test_bearer_miss_is_non_destructive_and_recovers_on_allowed_network(
    tmp_path,
) -> None:
    init_db()
    _clear()

    settings = _settings(
        tmp_path,
        enforcement=True,
    )

    _seed_policy()

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app,
            client=(
                ALLOWED_IP,
                50000,
            ),
        ) as allowed_client:
            login = allowed_client.post(
                "/api/auth/login",
                json={
                    "username":
                        USERNAME,
                    "password":
                        PASSWORD,
                },
            )

            assert (
                login.status_code
                == 200
            )

            token = str(
                login.json()[
                    "access_token"
                ]
            )

            policy = allowed_client.get(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
            )

            assert (
                policy.status_code
                == 200
            )

            assert (
                policy.json()[
                    "global_enforcement_enabled"
                ]
                is True
            )

            assert (
                policy.json()[
                    "enforcement_active"
                ]
                is True
            )

        with TestClient(
            app,
            client=(
                DENIED_IP,
                50000,
            ),
        ) as denied_client:
            denied = denied_client.get(
                "/api/auth/me",
                headers={
                    **_bearer(
                        token
                    ),
                    "X-Forwarded-For":
                        ALLOWED_IP,
                    "X-Real-IP":
                        ALLOWED_IP,
                },
            )

            assert (
                denied.status_code
                == 403
            )

            assert (
                denied.json()[
                    "detail"
                ]
                == "IP access denied"
            )

        rows = _session_rows()

        assert len(
            rows
        ) == 1

        assert (
            rows[0].revoked_at
            is None
        )

        with TestClient(
            app,
            client=(
                ALLOWED_IP,
                50001,
            ),
        ) as allowed_again:
            recovered = allowed_again.get(
                "/api/auth/me",
                headers=_bearer(
                    token
                ),
            )

            assert (
                recovered.status_code
                == 200
            )

            assert (
                recovered.json()[
                    "user"
                ][
                    "username"
                ]
                == USERNAME
            )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )

        _clear()


def test_basic_auth_cannot_bypass_active_ip_policy(
    tmp_path,
) -> None:
    init_db()
    _clear()

    settings = _settings(
        tmp_path,
        enforcement=True,
    )

    _seed_policy()

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app,
            client=(
                DENIED_IP,
                50000,
            ),
        ) as denied_client:
            denied = denied_client.get(
                "/api/auth/me",
                headers={
                    **_basic(),
                    "X-Forwarded-For":
                        ALLOWED_IP,
                },
            )

            assert (
                denied.status_code
                == 403
            )

            assert (
                denied.json()[
                    "detail"
                ]
                == "IP access denied"
            )

        with TestClient(
            app,
            client=(
                ALLOWED_IP,
                50000,
            ),
        ) as allowed_client:
            allowed = allowed_client.get(
                "/api/auth/me",
                headers=_basic(),
            )

            assert (
                allowed.status_code
                == 200
            )

        # Basic authorization never creates a durable Bearer session.
        assert _session_rows() == []

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )

        _clear()


def test_mfa_network_denial_does_not_consume_factor_or_challenge(
    tmp_path,
) -> None:
    init_db()
    _clear()

    settings = _settings(
        tmp_path,
        enforcement=True,
    )

    _seed_policy()

    enrolled_at = (
        datetime.now(
            UTC
        )
        - timedelta(
            minutes=2
        )
    )

    enrollment = (
        begin_totp_enrollment(
            username=USERNAME,
            settings=settings,
        )
    )

    secret = enrollment[
        "secret"
    ]

    enrollment_code = (
        pyotp.TOTP(
            secret
        ).at(
            enrolled_at
        )
    )

    completed = (
        complete_totp_enrollment_with_recovery(
            username=USERNAME,
            code=enrollment_code,
            settings=settings,
            now=enrolled_at,
        )
    )

    assert (
        completed
        is not None
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app,
            client=(
                ALLOWED_IP,
                50000,
            ),
        ) as allowed_client:
            first = allowed_client.post(
                "/api/auth/login",
                json={
                    "username":
                        USERNAME,
                    "password":
                        PASSWORD,
                },
            )

            assert (
                first.status_code
                == 200
            )

            body = first.json()

            assert (
                body[
                    "status"
                ]
                == "mfa_required"
            )

            challenge = str(
                body[
                    "challenge_token"
                ]
            )

        code = pyotp.TOTP(
            secret
        ).now()

        with TestClient(
            app,
            client=(
                DENIED_IP,
                50000,
            ),
        ) as denied_client:
            denied = denied_client.post(
                "/api/auth/login/mfa",
                json={
                    "challenge_token":
                        challenge,
                    "method":
                        "totp",
                    "code":
                        code,
                },
            )

            assert (
                denied.status_code
                == 403
            )

            assert (
                denied.json()[
                    "detail"
                ]
                == "IP access denied"
            )

        # Denied network must not consume the parent challenge.
        active_challenges = [
            row
            for row in _challenge_rows()
            if row.consumed_at is None
        ]

        assert len(
            active_challenges
        ) == 1

        with TestClient(
            app,
            client=(
                ALLOWED_IP,
                50001,
            ),
        ) as allowed_again:
            success = allowed_again.post(
                "/api/auth/login/mfa",
                json={
                    "challenge_token":
                        challenge,
                    "method":
                        "totp",
                    "code":
                        code,
                },
            )

            assert (
                success.status_code
                == 200
            )

            success_body = (
                success.json()
            )

            assert (
                success_body[
                    "status"
                ]
                == "authenticated"
            )

            assert (
                success_body[
                    "session"
                ][
                    "mfa_completed"
                ]
                is True
            )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )

        _clear()


def _call_lines(
    module_path: Path,
    function_name: str,
) -> dict[
    str,
    list[int],
]:
    tree = ast.parse(
        module_path.read_text(
            encoding="utf-8"
        )
    )

    function = next(
        node
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef
            | ast.AsyncFunctionDef,
        )
        and node.name
        == function_name
    )

    result: dict[
        str,
        list[int],
    ] = {}

    for node in ast.walk(
        function
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        name = None

        if isinstance(
            node.func,
            ast.Name,
        ):
            name = node.func.id

        elif isinstance(
            node.func,
            ast.Attribute,
        ):
            name = node.func.attr

        if name:
            result.setdefault(
                name,
                [],
            ).append(
                node.lineno
            )

    return result


def test_session_issuance_and_bearer_checks_are_structurally_ordered() -> None:
    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    path = (
        root
        / "app"
        / "auth_login.py"
    )

    password = _call_lines(
        path,
        "begin_password_login",
    )

    assert min(
        password[
            "_require_ip_access"
        ]
    ) < min(
        password[
            "create_auth_challenge"
        ]
    )

    authenticated = _call_lines(
        path,
        "_authenticated_result",
    )

    assert min(
        authenticated[
            "_require_ip_access"
        ]
    ) < min(
        authenticated[
            "create_auth_session"
        ]
    )

    mfa = _call_lines(
        path,
        "complete_mfa_login",
    )

    assert min(
        mfa[
            "_require_ip_access"
        ]
    ) < min(
        mfa[
            "verify_totp_for_user_in_session"
        ]
    )

    assert min(
        mfa[
            "_require_ip_access"
        ]
    ) < min(
        mfa[
            "consume_recovery_code_in_session"
        ]
    )

    passkey = _call_lines(
        path,
        "complete_passkey_mfa_login",
    )

    assert min(
        passkey[
            "_require_ip_access"
        ]
    ) < min(
        passkey[
            "verify_passkey_authentication_challenge_in_session"
        ]
    )

    bearer = _call_lines(
        path,
        "resolve_bearer_session",
    )

    assert min(
        bearer[
            "_require_ip_access"
        ]
    ) < min(
        bearer[
            "touch_auth_session"
        ]
    )
