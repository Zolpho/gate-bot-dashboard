from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth_rate_limit as auth_rate_limit
import app.auth_state as auth_state
import app.auth_totp as auth_totp
from app.auth_mfa import (
    complete_totp_enrollment_with_recovery,
)
from app.auth_rate_limit import (
    hash_rate_limit_subject,
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
    DashboardAuthRateLimitEvent,
    DashboardAuthRecoveryCode,
    DashboardAuthSession,
)
from app.security import hash_password


def _settings(
    tmp_path,
    *,
    username: str,
    password: str,
    password_limit: int = 10,
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
        dashboard_auth_rate_limit_enabled=True,
        dashboard_auth_password_attempt_limit=(
            password_limit
        ),
        dashboard_auth_password_attempt_window_seconds=300,
        dashboard_auth_mfa_user_attempt_limit=10,
        dashboard_auth_mfa_challenge_attempt_limit=5,
        dashboard_auth_mfa_attempt_window_seconds=300,
        dashboard_auth_client_attempt_limit=30,
        dashboard_auth_client_attempt_window_seconds=300,
    )


def _clear(
    username: str,
) -> None:
    with session_scope() as db:
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


def _enroll(
    *,
    username: str,
    settings: Settings,
    now: datetime,
) -> dict:
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

    return {
        "secret":
            enrollment[
                "secret"
            ],
        "recovery_codes":
            completed[
                "recovery_codes"
            ],
    }


def test_password_login_is_sanitized_and_uses_request_client(
    tmp_path,
) -> None:
    init_db()

    username = (
        "api-password-user"
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

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/login",
                headers={
                    "X-Forwarded-For":
                        "203.0.113.250",
                    "X-Real-IP":
                        "203.0.113.251",
                },
                json={
                    "username":
                        username,
                    "password":
                        password,
                },
            )

        assert response.status_code == 200

        body = response.json()

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
            == "password"
        )

        serialized = json.dumps(
            body,
            sort_keys=True,
        )

        for forbidden in (
            "credential_fingerprint",
            "password_hash",
            "token_hash",
            "metadata_json",
        ):
            assert (
                forbidden
                not in serialized
            )

        assert (
            password
            not in serialized
        )

        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(
                        DashboardAuthRateLimitEvent
                    )
                )
            )

        assert rows

        client_hashes = {
            row.client_hash
            for row in rows
            if row.client_hash
        }

        assert client_hashes

        # TestClient's ASGI peer is "testclient". The application must
        # use that normalized peer and never parse spoofable forwarding
        # headers itself.
        assert (
            hash_rate_limit_subject(
                "testclient"
            )
            in client_hashes
        )

        assert (
            hash_rate_limit_subject(
                "203.0.113.250"
            )
            not in client_hashes
        )

        assert (
            hash_rate_limit_subject(
                "203.0.113.251"
            )
            not in client_hashes
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_password_login_rate_limit_returns_retry_after(
    tmp_path,
) -> None:
    init_db()

    username = (
        "api-rate-user"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=(
            "password-test-123"
        ),
        password_limit=1,
    )

    _clear(
        username
    )

    reference = datetime(
        2026,
        9,
        19,
        14,
        0,
        tzinfo=UTC,
    )

    original_now = (
        auth_rate_limit.utcnow
    )

    auth_rate_limit.utcnow = (
        lambda: reference
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/auth/login",
                json={
                    "username":
                        username,
                    "password":
                        "wrong-password",
                },
            )

            assert (
                first.status_code
                == 401
            )

            second = client.post(
                "/api/auth/login",
                json={
                    "username":
                        username,
                    "password":
                        "wrong-password",
                },
            )

        assert (
            second.status_code
            == 429
        )

        body = second.json()

        assert (
            body[
                "detail"
            ][
                "message"
            ]
            == (
                "Authentication rate limit "
                "exceeded"
            )
        )

        assert (
            body[
                "detail"
            ][
                "scope"
            ]
            == "username"
        )

        assert (
            int(
                second.headers[
                    "retry-after"
                ]
            )
            >= 1
        )

    finally:
        auth_rate_limit.utcnow = (
            original_now
        )

        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_totp_login_api_hides_internal_challenge_and_session_state(
    tmp_path,
) -> None:
    init_db()

    username = (
        "api-totp-user"
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

    enrolled_at = datetime(
        2026,
        9,
        19,
        15,
        0,
        tzinfo=UTC,
    )

    enrolled = _enroll(
        username=username,
        settings=settings,
        now=enrolled_at,
    )

    login_at = (
        enrolled_at
        + timedelta(
            seconds=30
        )
    )

    original_state_now = (
        auth_state.utcnow
    )

    original_totp_now = (
        auth_totp.utcnow
    )

    original_rate_now = (
        auth_rate_limit.utcnow
    )

    auth_state.utcnow = (
        lambda: login_at
    )

    auth_totp.utcnow = (
        lambda: login_at
    )

    auth_rate_limit.utcnow = (
        lambda: login_at
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            started = client.post(
                "/api/auth/login",
                json={
                    "username":
                        username,
                    "password":
                        password,
                },
            )

            assert (
                started.status_code
                == 200
            )

            started_body = (
                started.json()
            )

            assert (
                started_body[
                    "status"
                ]
                == "mfa_required"
            )

            assert (
                started_body[
                    "challenge_token"
                ]
            )

            assert set(
                started_body[
                    "methods"
                ]
            ) == {
                "totp",
                "recovery",
            }

            started_serialized = (
                json.dumps(
                    started_body,
                    sort_keys=True,
                )
            )

            for forbidden in (
                "credential_fingerprint",
                "metadata",
                "metadata_json",
                "token_hash",
            ):
                assert (
                    forbidden
                    not in started_serialized
                )

            code = pyotp.TOTP(
                enrolled[
                    "secret"
                ]
            ).at(
                login_at
            )

            completed = client.post(
                "/api/auth/login/mfa",
                json={
                    "challenge_token":
                        started_body[
                            "challenge_token"
                        ],
                    "method":
                        "totp",
                    "code":
                        code,
                },
            )

            assert (
                completed.status_code
                == 200
            )

            completed_body = (
                completed.json()
            )

            assert (
                completed_body[
                    "status"
                ]
                == "authenticated"
            )

            assert (
                completed_body[
                    "session"
                ][
                    "auth_method"
                ]
                == "password_totp"
            )

            assert (
                completed_body[
                    "session"
                ][
                    "mfa_completed"
                ]
                is True
            )

            completed_serialized = (
                json.dumps(
                    completed_body,
                    sort_keys=True,
                )
            )

            for forbidden in (
                "credential_fingerprint",
                "password_hash",
                "token_hash",
                "metadata",
                "metadata_json",
            ):
                assert (
                    forbidden
                    not in completed_serialized
                )

    finally:
        auth_state.utcnow = (
            original_state_now
        )

        auth_totp.utcnow = (
            original_totp_now
        )

        auth_rate_limit.utcnow = (
            original_rate_now
        )

        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_mfa_login_method_is_strictly_validated(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path,
        username=(
            "api-validation-user"
        ),
        password=(
            "password-test-123"
        ),
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/login/mfa",
                json={
                    "challenge_token":
                        "opaque-test-token",
                    "method":
                        "sms",
                    "code":
                        "123456",
                },
            )

        assert (
            response.status_code
            == 422
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_login_request_models_reject_unknown_fields(
    tmp_path,
) -> None:
    init_db()

    username = (
        "api-extra-field-user"
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

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            password_response = client.post(
                "/api/auth/login",
                json={
                    "username":
                        username,
                    "password":
                        password,
                    "unexpected":
                        True,
                },
            )

            mfa_response = client.post(
                "/api/auth/login/mfa",
                json={
                    "challenge_token":
                        "opaque-test-token",
                    "method":
                        "totp",
                    "code":
                        "123456",
                    "unexpected":
                        True,
                },
            )

        assert (
            password_response.status_code
            == 422
        )

        assert (
            mfa_response.status_code
            == 422
        )

        with session_scope() as db:
            rate_rows = list(
                db.scalars(
                    select(
                        DashboardAuthRateLimitEvent
                    )
                )
            )

            session_rows = list(
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

            challenge_rows = list(
                db.scalars(
                    select(
                        DashboardAuthChallenge
                    ).where(
                        DashboardAuthChallenge
                        .username
                        == username
                    )
                )
            )

        # Request validation occurs before the authentication service.
        assert rate_rows == []
        assert session_rows == []
        assert challenge_rows == []

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )
