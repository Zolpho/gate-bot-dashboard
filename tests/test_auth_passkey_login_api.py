from __future__ import annotations

import base64
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth_passkey as passkeys
from app.auth_passkey import (
    set_passkey_enabled,
)
from app.auth_passkey_flow import (
    begin_passkey_registration,
    complete_passkey_registration,
)
from app.auth_rate_limit import (
    hash_rate_limit_subject,
)
from app.auth_state import (
    create_auth_challenge,
    get_auth_challenge,
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
    DashboardAuthPasskeyCredential,
    DashboardAuthPasskeyUser,
    DashboardAuthRateLimitEvent,
    DashboardAuthSession,
)
from app.security import hash_password


def _settings(
    tmp_path,
    *,
    username: str,
    password: str,
    webauthn_enabled: bool = True,
    rate_limit_enabled: bool = False,
    mfa_challenge_limit: int = 5,
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
                            username,
                        "password_hash":
                            hash_password(
                                password,
                                iterations=100_000,
                            ),
                        "account_ids": [
                            username,
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

    return Settings(
        dashboard_users_file=(
            users_path
        ),
        dashboard_mfa_required=False,
        dashboard_webauthn_enabled=(
            webauthn_enabled
        ),
        dashboard_webauthn_rp_id=(
            "example.invalid"
        ),
        dashboard_webauthn_origin=(
            "https://example.invalid"
        ),
        dashboard_webauthn_rp_name=(
            "Gate Bot Dashboard Test"
        ),
        dashboard_auth_rate_limit_enabled=(
            rate_limit_enabled
        ),
        dashboard_auth_password_attempt_limit=20,
        dashboard_auth_password_attempt_window_seconds=300,
        dashboard_auth_mfa_user_attempt_limit=20,
        dashboard_auth_mfa_challenge_attempt_limit=(
            mfa_challenge_limit
        ),
        dashboard_auth_mfa_attempt_window_seconds=300,
        dashboard_auth_client_attempt_limit=30,
        dashboard_auth_client_attempt_window_seconds=300,
    )


def _clear(
    username: str,
) -> None:
    with session_scope() as db:
        for model in (
            DashboardAuthPasskeyCredential,
            DashboardAuthPasskeyUser,
            DashboardAuthSession,
            DashboardAuthChallenge,
        ):
            db.execute(
                delete(
                    model
                ).where(
                    model.username
                    == username
                )
            )

        db.execute(
            delete(
                DashboardAuthRateLimitEvent
            )
        )


def _b64url(
    value: bytes,
) -> str:
    return (
        base64
        .urlsafe_b64encode(
            value
        )
        .decode(
            "ascii"
        )
        .rstrip(
            "="
        )
    )


def _credential(
    credential_id: bytes,
) -> dict:
    encoded = (
        _b64url(
            credential_id
        )
    )

    return {
        "id":
            encoded,
        "rawId":
            encoded,
        "response": {
            "transports": [
                "internal",
            ],
        },
        "type":
            "public-key",
        "clientExtensionResults":
            {},
    }


def _fake_registration(
    credential_id: bytes,
):
    return SimpleNamespace(
        credential_id=(
            credential_id
        ),
        credential_public_key=(
            b"public-key-"
            + credential_id
        ),
        sign_count=0,
        credential_device_type=(
            SimpleNamespace(
                value="single_device"
            )
        ),
        credential_backed_up=False,
        user_verified=True,
    )


def _register_enabled_passkey(
    monkeypatch,
    *,
    username: str,
    credential_id: bytes,
    settings: Settings,
) -> None:
    started = (
        begin_passkey_registration(
            username=username,
            settings=settings,
        )
    )

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **_kwargs: (
            _fake_registration(
                credential_id
            )
        ),
    )

    complete_passkey_registration(
        challenge_token=(
            started[
                "challenge_token"
            ]
        ),
        credential=(
            _credential(
                credential_id
            )
        ),
        settings=settings,
        label="Login passkey",
    )

    status = (
        set_passkey_enabled(
            username,
            True,
        )
    )

    assert status[
        "available"
    ] is True


def _start_password_and_passkey(
    client: TestClient,
    *,
    username: str,
    password: str,
) -> tuple[dict, dict]:
    password_response = client.post(
        "/api/auth/login",
        json={
            "username":
                username,
            "password":
                password,
        },
    )

    assert (
        password_response.status_code
        == 200
    )

    parent = (
        password_response.json()
    )

    assert (
        parent[
            "status"
        ]
        == "mfa_required"
    )

    assert (
        "passkey"
        in parent[
            "methods"
        ]
    )

    begin_response = client.post(
        "/api/auth/login/passkey",
        json={
            "challenge_token":
                parent[
                    "challenge_token"
                ],
        },
    )

    assert (
        begin_response.status_code
        == 200
    )

    child = (
        begin_response.json()
    )

    assert (
        child[
            "status"
        ]
        == "passkey_authentication_required"
    )

    assert child[
        "challenge_token"
    ]

    return (
        parent,
        child,
    )


def test_password_passkey_http_round_trip_is_sanitized_and_one_time(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-http-login-user"
    )

    password = (
        "password-test-123"
    )

    credential_id = (
        b"passkey-http-login-credential"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
    )

    _clear(
        username
    )

    _register_enabled_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            credential_id
        ),
        settings=settings,
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app
        ) as client:
            parent, child = (
                _start_password_and_passkey(
                    client,
                    username=username,
                    password=password,
                )
            )

            assert (
                child[
                    "options"
                ][
                    "rpId"
                ]
                == "example.invalid"
            )

            child_serialized = (
                json.dumps(
                    child,
                    sort_keys=True,
                )
            )

            for forbidden in (
                "metadata",
                "metadata_json",
                "credential_public_key",
                "user_handle",
                "password_hash",
                "credential_fingerprint",
            ):
                assert (
                    forbidden
                    not in child_serialized
                )

            monkeypatch.setattr(
                passkeys,
                "verify_authentication_response",
                lambda **_kwargs: (
                    SimpleNamespace(
                        credential_id=(
                            credential_id
                        ),
                        new_sign_count=1,
                        credential_device_type=(
                            SimpleNamespace(
                                value="multi_device"
                            )
                        ),
                        credential_backed_up=True,
                        user_verified=True,
                    )
                ),
            )

            completed = client.post(
                (
                    "/api/auth/login/"
                    "passkey/complete"
                ),
                json={
                    "challenge_token":
                        parent[
                            "challenge_token"
                        ],
                    "passkey_challenge_token":
                        child[
                            "challenge_token"
                        ],
                    "credential":
                        _credential(
                            credential_id
                        ),
                },
            )

            assert (
                completed.status_code
                == 200
            )

            body = (
                completed.json()
            )

            assert (
                body[
                    "status"
                ]
                == "authenticated"
            )

            assert (
                body[
                    "token_type"
                ]
                == "bearer"
            )

            assert body[
                "access_token"
            ]

            assert (
                body[
                    "session"
                ][
                    "auth_method"
                ]
                == "password_passkey"
            )

            assert (
                body[
                    "session"
                ][
                    "mfa_completed"
                ]
                is True
            )

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
            )

            assert (
                "passkey"
                not in body
            )

            serialized = (
                json.dumps(
                    body,
                    sort_keys=True,
                )
            )

            for forbidden in (
                "credential_id",
                "credential_public_key",
                "user_handle",
                "metadata",
                "metadata_json",
                "password_hash",
                "credential_fingerprint",
            ):
                assert (
                    forbidden
                    not in serialized
                )

            me = client.get(
                "/api/auth/me",
                headers={
                    "Authorization":
                        "Bearer "
                        + body[
                            "access_token"
                        ],
                },
            )

            assert (
                me.status_code
                == 200
            )

            replay = client.post(
                (
                    "/api/auth/login/"
                    "passkey/complete"
                ),
                json={
                    "challenge_token":
                        parent[
                            "challenge_token"
                        ],
                    "passkey_challenge_token":
                        child[
                            "challenge_token"
                        ],
                    "credential":
                        _credential(
                            credential_id
                        ),
                },
            )

            assert (
                replay.status_code
                == 401
            )

        assert (
            get_auth_challenge(
                parent[
                    "challenge_token"
                ],
                purpose="login_mfa",
            )
            is None
        )

        assert (
            get_auth_challenge(
                child[
                    "challenge_token"
                ],
                purpose=(
                    "passkey_authentication"
                ),
            )
            is None
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_passkey_login_begin_rejects_parent_without_passkey_method(
    tmp_path,
) -> None:
    init_db()

    username = (
        "passkey-http-method-user"
    )

    password = (
        "password-test-123"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
    )

    _clear(
        username
    )

    parent_token, _ = (
        create_auth_challenge(
            username=username,
            purpose="login_mfa",
            metadata={
                "credential_fingerprint":
                    "0"
                    * 64,
                "allowed_methods": [
                    "totp",
                ],
            },
        )
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app
        ) as client:
            response = client.post(
                "/api/auth/login/passkey",
                json={
                    "challenge_token":
                        parent_token,
                },
            )

        assert (
            response.status_code
            == 401
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_passkey_login_http_is_fail_closed_when_rollout_gate_is_off(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path,
        username="passkey-http-gate-user",
        password="password-test-123",
        webauthn_enabled=False,
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app
        ) as client:
            begin_response = client.post(
                "/api/auth/login/passkey",
                json={
                    "challenge_token":
                        "opaque-parent-token",
                },
            )

            complete_response = client.post(
                (
                    "/api/auth/login/"
                    "passkey/complete"
                ),
                json={
                    "challenge_token":
                        "opaque-parent-token",
                    "passkey_challenge_token":
                        "opaque-child-token",
                    "credential":
                        {},
                },
            )

        assert (
            begin_response.status_code
            == 503
        )

        assert (
            complete_response.status_code
            == 503
        )

        assert (
            begin_response.json()[
                "detail"
            ]
            == "Passkey service is not available"
        )

        assert (
            complete_response.json()[
                "detail"
            ]
            == "Passkey service is not available"
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_failed_passkey_completion_is_rate_limited_by_parent_challenge(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-http-rate-user"
    )

    password = (
        "password-test-123"
    )

    credential_id = (
        b"passkey-http-rate-credential"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
        rate_limit_enabled=True,
        mfa_challenge_limit=1,
    )

    _clear(
        username
    )

    _register_enabled_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            credential_id
        ),
        settings=settings,
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app
        ) as client:
            parent, child = (
                _start_password_and_passkey(
                    client,
                    username=username,
                    password=password,
                )
            )

            monkeypatch.setattr(
                passkeys,
                "verify_authentication_response",
                lambda **_kwargs: (
                    (_ for _ in ())
                    .throw(
                        ValueError(
                            "invalid assertion"
                        )
                    )
                ),
            )

            headers = {
                "X-Forwarded-For":
                    "203.0.113.77",
                "X-Real-IP":
                    "203.0.113.78",
            }

            first = client.post(
                (
                    "/api/auth/login/"
                    "passkey/complete"
                ),
                headers=headers,
                json={
                    "challenge_token":
                        parent[
                            "challenge_token"
                        ],
                    "passkey_challenge_token":
                        child[
                            "challenge_token"
                        ],
                    "credential":
                        _credential(
                            credential_id
                        ),
                },
            )

            assert (
                first.status_code
                == 401
            )

            second = client.post(
                (
                    "/api/auth/login/"
                    "passkey/complete"
                ),
                headers=headers,
                json={
                    "challenge_token":
                        parent[
                            "challenge_token"
                        ],
                    "passkey_challenge_token":
                        child[
                            "challenge_token"
                        ],
                    "credential":
                        _credential(
                            credential_id
                        ),
                },
            )

        assert (
            second.status_code
            == 429
        )

        assert (
            int(
                second.headers[
                    "retry-after"
                ]
            )
            >= 1
        )

        assert (
            second.json()[
                "detail"
            ][
                "scope"
            ]
            == "challenge"
        )

        assert (
            get_auth_challenge(
                parent[
                    "challenge_token"
                ],
                purpose="login_mfa",
            )
            is not None
        )

        assert (
            get_auth_challenge(
                child[
                    "challenge_token"
                ],
                purpose=(
                    "passkey_authentication"
                ),
            )
            is not None
        )

        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(
                        DashboardAuthRateLimitEvent
                    )
                )
            )

        mfa_rows = [
            row
            for row in rows
            if (
                row.action
                == "mfa_login"
            )
        ]

        assert len(
            mfa_rows
        ) == 1

        assert (
            mfa_rows[0]
            .challenge_hash
        )

        assert (
            mfa_rows[0]
            .client_hash
            == hash_rate_limit_subject(
                "testclient"
            )
        )

        assert (
            mfa_rows[0]
            .client_hash
            != hash_rate_limit_subject(
                "203.0.113.77"
            )
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_passkey_login_request_models_are_strict_and_code_endpoint_stays_separate(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path,
        username="passkey-http-strict-user",
        password="password-test-123",
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app
        ) as client:
            begin_extra = client.post(
                "/api/auth/login/passkey",
                json={
                    "challenge_token":
                        "opaque-parent",
                    "unexpected":
                        True,
                },
            )

            complete_extra = client.post(
                (
                    "/api/auth/login/"
                    "passkey/complete"
                ),
                json={
                    "challenge_token":
                        "opaque-parent",
                    "passkey_challenge_token":
                        "opaque-child",
                    "credential":
                        {},
                    "unexpected":
                        True,
                },
            )

            code_endpoint = client.post(
                "/api/auth/login/mfa",
                json={
                    "challenge_token":
                        "opaque-parent",
                    "method":
                        "passkey",
                    "code":
                        "not-a-code",
                },
            )

        assert begin_extra.status_code == 422
        assert complete_extra.status_code == 422
        assert code_endpoint.status_code == 422

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )
