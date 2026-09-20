from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pyotp
import pytest
from sqlalchemy import delete, select

import app.auth_passkey as passkeys
from app.auth_login import (
    LoginDenied,
    begin_passkey_mfa_login,
    begin_password_login,
    complete_mfa_login,
    complete_passkey_mfa_login,
    resolve_bearer_session,
)
from app.auth_mfa import (
    complete_totp_enrollment_with_recovery,
)
from app.auth_passkey import (
    set_passkey_enabled,
)
from app.auth_passkey_flow import (
    begin_passkey_registration,
    complete_passkey_registration,
)
from app.auth_state import (
    generate_auth_encryption_key,
    get_auth_challenge,
)
from app.auth_totp import (
    begin_totp_enrollment,
)
from app.config import Settings
from app.db import (
    init_db,
    session_scope,
)
from app.models import (
    DashboardAuthChallenge,
    DashboardAuthEvent,
    DashboardAuthFactor,
    DashboardAuthPasskeyCredential,
    DashboardAuthPasskeyUser,
    DashboardAuthRateLimitEvent,
    DashboardAuthRecoveryCode,
    DashboardAuthSession,
)
from app.security import hash_password


def _write_user(
    path,
    *,
    username: str,
    password: str,
) -> None:
    path.write_text(
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


def _settings(
    tmp_path,
    *,
    username: str,
    password: str,
    webauthn_enabled: bool,
) -> Settings:
    users_path = (
        tmp_path
        / "dashboard_users.json"
    )

    _write_user(
        users_path,
        username=username,
        password=password,
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
        dashboard_mfa_required=False,
        dashboard_auth_rate_limit_enabled=False,
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
    )


def _clear(
    username: str,
) -> None:
    with session_scope() as db:
        for model in (
            DashboardAuthPasskeyCredential,
            DashboardAuthPasskeyUser,
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
                    == username
                )
            )

        db.execute(
            delete(
                DashboardAuthEvent
            ).where(
                DashboardAuthEvent
                .target_username
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


def _register_passkey(
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
        label="Test passkey",
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


def _enroll_totp(
    *,
    username: str,
    settings: Settings,
    now: datetime,
) -> None:
    enrollment = (
        begin_totp_enrollment(
            username=username,
            settings=settings,
        )
    )

    code = pyotp.TOTP(
        enrollment[
            "secret"
        ]
    ).at(
        now
    )

    completed = (
        complete_totp_enrollment_with_recovery(
            username=username,
            code=code,
            settings=settings,
            now=now,
        )
    )

    assert completed is not None


def test_passkey_enabled_user_gets_password_mfa_challenge(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-login-user"
    )

    password = (
        "password-test-123"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
        webauthn_enabled=True,
    )

    _clear(
        username
    )

    _register_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            b"passkey-login-credential"
        ),
        settings=settings,
    )

    started = (
        begin_password_login(
            username=username,
            password=password,
            settings=settings,
        )
    )

    assert (
        started[
            "status"
        ]
        == "mfa_required"
    )

    assert (
        started[
            "methods"
        ]
        == [
            "passkey",
        ]
    )


def test_rollout_gate_off_keeps_passkey_out_of_login_methods(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-gate-off-user"
    )

    password = (
        "password-test-123"
    )

    enabled_settings = (
        _settings(
            tmp_path,
            username=username,
            password=password,
            webauthn_enabled=True,
        )
    )

    _clear(
        username
    )

    _register_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            b"passkey-gate-off-credential"
        ),
        settings=enabled_settings,
    )

    disabled_settings = (
        enabled_settings
        .model_copy(
            update={
                "dashboard_webauthn_enabled":
                    False,
            }
        )
    )

    result = (
        begin_password_login(
            username=username,
            password=password,
            settings=disabled_settings,
        )
    )

    assert (
        result[
            "status"
        ]
        == "authenticated"
    )

    assert (
        result[
            "session"
        ][
            "auth_method"
        ]
        == "password"
    )

    assert (
        result[
            "session"
        ][
            "mfa_completed"
        ]
        is False
    )


def test_totp_recovery_and_passkey_can_coexist(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-coexist-user"
    )

    password = (
        "password-test-123"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
        webauthn_enabled=True,
    )

    _clear(
        username
    )

    reference = datetime(
        2026,
        9,
        20,
        12,
        0,
        tzinfo=UTC,
    )

    _enroll_totp(
        username=username,
        settings=settings,
        now=reference,
    )

    _register_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            b"passkey-coexist-credential"
        ),
        settings=settings,
    )

    started = (
        begin_password_login(
            username=username,
            password=password,
            settings=settings,
            now=reference,
        )
    )

    assert set(
        started[
            "methods"
        ]
    ) == {
        "totp",
        "recovery",
        "passkey",
    }


def test_password_passkey_completion_is_atomic_and_one_time(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-complete-user"
    )

    password = (
        "password-test-123"
    )

    credential_id = (
        b"passkey-complete-credential"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
        webauthn_enabled=True,
    )

    _clear(
        username
    )

    _register_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            credential_id
        ),
        settings=settings,
    )

    parent = (
        begin_password_login(
            username=username,
            password=password,
            settings=settings,
        )
    )

    child = (
        begin_passkey_mfa_login(
            challenge_token=(
                parent[
                    "challenge_token"
                ]
            ),
            settings=settings,
        )
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

    completed = (
        complete_passkey_mfa_login(
            challenge_token=(
                parent[
                    "challenge_token"
                ]
            ),
            passkey_challenge_token=(
                child[
                    "challenge_token"
                ]
            ),
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=settings,
        )
    )

    assert (
        completed[
            "status"
        ]
        == "authenticated"
    )

    assert (
        completed[
            "session"
        ][
            "auth_method"
        ]
        == "password_passkey"
    )

    assert (
        completed[
            "session"
        ][
            "mfa_completed"
        ]
        is True
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

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthPasskeyCredential
            ).where(
                DashboardAuthPasskeyCredential
                .username
                == username
            )
        )

        assert row is not None
        assert row.sign_count == 1

    assert (
        resolve_bearer_session(
            completed[
                "access_token"
            ],
            settings=settings,
        )
        is not None
    )

    with pytest.raises(
        LoginDenied,
        match=(
            "Invalid or expired "
            "login challenge"
        ),
    ):
        complete_passkey_mfa_login(
            challenge_token=(
                parent[
                    "challenge_token"
                ]
            ),
            passkey_challenge_token=(
                child[
                    "challenge_token"
                ]
            ),
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=settings,
        )


def test_failed_passkey_does_not_consume_parent_or_child(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-failure-user"
    )

    password = (
        "password-test-123"
    )

    credential_id = (
        b"passkey-failure-credential"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
        webauthn_enabled=True,
    )

    _clear(
        username
    )

    _register_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            credential_id
        ),
        settings=settings,
    )

    parent = (
        begin_password_login(
            username=username,
            password=password,
            settings=settings,
        )
    )

    child = (
        begin_passkey_mfa_login(
            challenge_token=(
                parent[
                    "challenge_token"
                ]
            ),
            settings=settings,
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

    with pytest.raises(
        LoginDenied,
        match=(
            "Invalid or expired passkey "
            "challenge or credential"
        ),
    ):
        complete_passkey_mfa_login(
            challenge_token=(
                parent[
                    "challenge_token"
                ]
            ),
            passkey_challenge_token=(
                child[
                    "challenge_token"
                ]
            ),
            credential=(
                _credential(
                    credential_id
                )
            ),
            settings=settings,
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
        sessions = list(
            db.scalars(
                select(
                    DashboardAuthSession
                ).where(
                    DashboardAuthSession
                    .username
                    == username
                )
            )
        )

    assert sessions == []


def test_existing_code_mfa_path_does_not_accept_passkey_method(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-code-path-user"
    )

    password = (
        "password-test-123"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
        webauthn_enabled=True,
    )

    _clear(
        username
    )

    _register_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            b"passkey-code-path-credential"
        ),
        settings=settings,
    )

    started = (
        begin_password_login(
            username=username,
            password=password,
            settings=settings,
        )
    )

    with pytest.raises(
        LoginDenied,
        match="Unsupported MFA method",
    ):
        complete_mfa_login(
            challenge_token=(
                started[
                    "challenge_token"
                ]
            ),
            method="passkey",
            code="not-a-recovery-code",
            settings=settings,
        )


def test_existing_password_session_is_revoked_when_passkey_becomes_required(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-session-policy-user"
    )

    password = (
        "password-test-123"
    )

    enabled_settings = _settings(
        tmp_path,
        username=username,
        password=password,
        webauthn_enabled=True,
    )

    _clear(
        username
    )

    _register_passkey(
        monkeypatch,
        username=username,
        credential_id=(
            b"passkey-session-policy-credential"
        ),
        settings=enabled_settings,
    )

    disabled_settings = (
        enabled_settings
        .model_copy(
            update={
                "dashboard_webauthn_enabled":
                    False,
            }
        )
    )

    password_only = (
        begin_password_login(
            username=username,
            password=password,
            settings=disabled_settings,
        )
    )

    token = (
        password_only[
            "access_token"
        ]
    )

    assert (
        resolve_bearer_session(
            token,
            settings=disabled_settings,
        )
        is not None
    )

    assert (
        resolve_bearer_session(
            token,
            settings=enabled_settings,
        )
        is None
    )
