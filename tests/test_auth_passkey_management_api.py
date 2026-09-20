from __future__ import annotations

import base64
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth_passkey as passkeys
from app.auth_state import (
    create_auth_challenge,
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


def _login(
    client: TestClient,
    *,
    username: str,
    password: str,
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
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

    token = body[
        "access_token"
    ]

    assert token

    return {
        "Authorization":
            f"Bearer {token}",
    }


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


def test_passkey_status_requires_authentication(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path,
        username="passkey-api-auth-user",
        password="password-test-123",
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app
        ) as client:
            response = client.get(
                "/api/auth/mfa/passkeys"
            )

        assert response.status_code == 401

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_passkey_status_is_public_state_only(
    tmp_path,
) -> None:
    init_db()

    username = (
        "passkey-api-status-user"
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
        with TestClient(
            app
        ) as client:
            headers = _login(
                client,
                username=username,
                password=password,
            )

            response = client.get(
                "/api/auth/mfa/passkeys",
                headers=headers,
            )

        assert response.status_code == 200

        body = response.json()

        assert (
            body[
                "factor"
            ][
                "enabled"
            ]
            is False
        )

        assert (
            body[
                "factor"
            ][
                "credential_count"
            ]
            == 0
        )

        assert (
            body[
                "service_available"
            ]
            is True
        )

        serialized = json.dumps(
            body,
            sort_keys=True,
        )

        for forbidden in (
            "credential_public_key",
            "user_handle",
            "password_hash",
            "credential_fingerprint",
            "metadata_json",
        ):
            assert (
                forbidden
                not in serialized
            )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_registration_begin_requires_current_password(
    tmp_path,
) -> None:
    init_db()

    username = (
        "passkey-api-password-user"
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
        with TestClient(
            app
        ) as client:
            headers = _login(
                client,
                username=username,
                password=password,
            )

            response = client.post(
                "/api/auth/mfa/passkeys/register",
                headers=headers,
                json={
                    "current_password":
                        "wrong-password-123",
                },
            )

        assert response.status_code == 403

        with session_scope() as db:
            user_row = db.get(
                DashboardAuthPasskeyUser,
                username,
            )

            challenges = list(
                db.scalars(
                    select(
                        DashboardAuthChallenge
                    ).where(
                        DashboardAuthChallenge
                        .username
                        == username,
                        DashboardAuthChallenge
                        .purpose
                        == "passkey_registration",
                    )
                )
            )

        assert user_row is None
        assert challenges == []

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_registration_is_blocked_when_rollout_gate_is_off(
    tmp_path,
) -> None:
    init_db()

    username = (
        "passkey-api-gate-user"
    )

    password = (
        "password-test-123"
    )

    settings = _settings(
        tmp_path,
        username=username,
        password=password,
        webauthn_enabled=False,
    )

    _clear(
        username
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(
            app
        ) as client:
            headers = _login(
                client,
                username=username,
                password=password,
            )

            response = client.post(
                "/api/auth/mfa/passkeys/register",
                headers=headers,
                json={
                    "current_password":
                        password,
                },
            )

        assert response.status_code == 503

        assert (
            response.json()[
                "detail"
            ]
            == "Passkey service is not available"
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_registration_round_trip_stores_disabled_credential(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "passkey-api-register-user"
    )

    password = (
        "password-test-123"
    )

    credential_id = (
        b"passkey-api-register-credential"
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
        with TestClient(
            app
        ) as client:
            headers = _login(
                client,
                username=username,
                password=password,
            )

            started = client.post(
                "/api/auth/mfa/passkeys/register",
                headers=headers,
                json={
                    "current_password":
                        password,
                },
            )

            assert started.status_code == 200

            started_body = (
                started.json()
            )

            assert (
                started_body[
                    "status"
                ]
                == "passkey_registration_required"
            )

            assert (
                started_body[
                    "challenge_token"
                ]
            )

            assert (
                started_body[
                    "options"
                ][
                    "rp"
                ][
                    "id"
                ]
                == "example.invalid"
            )

            started_serialized = json.dumps(
                started_body,
                sort_keys=True,
            )

            for forbidden in (
                "metadata",
                "metadata_json",
                "user_handle",
                "credential_public_key",
                "password_hash",
                password,
            ):
                assert (
                    forbidden
                    not in started_serialized
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

            completed = client.post(
                (
                    "/api/auth/mfa/passkeys/"
                    "register/complete"
                ),
                headers=headers,
                json={
                    "challenge_token":
                        started_body[
                            "challenge_token"
                        ],
                    "credential":
                        _credential(
                            credential_id
                        ),
                    "label":
                        "MacBook passkey",
                },
            )

            assert completed.status_code == 200

            completed_body = (
                completed.json()
            )

            assert (
                completed_body[
                    "status"
                ]
                == "registered"
            )

            assert (
                completed_body[
                    "factor"
                ][
                    "enabled"
                ]
                is False
            )

            assert (
                completed_body[
                    "factor"
                ][
                    "available"
                ]
                is False
            )

            assert (
                completed_body[
                    "factor"
                ][
                    "credential_count"
                ]
                == 1
            )

            assert (
                completed_body[
                    "credential"
                ][
                    "label"
                ]
                == "MacBook passkey"
            )

            completed_serialized = (
                json.dumps(
                    completed_body,
                    sort_keys=True,
                )
            )

            for forbidden in (
                "credential_public_key",
                "user_handle",
                "metadata",
                "metadata_json",
                "password_hash",
            ):
                assert (
                    forbidden
                    not in completed_serialized
                )

            status = client.get(
                "/api/auth/mfa/passkeys",
                headers=headers,
            )

            assert status.status_code == 200

            assert (
                status.json()[
                    "factor"
                ][
                    "credential_count"
                ]
                == 1
            )

            replay = client.post(
                (
                    "/api/auth/mfa/passkeys/"
                    "register/complete"
                ),
                headers=headers,
                json={
                    "challenge_token":
                        started_body[
                            "challenge_token"
                        ],
                    "credential":
                        _credential(
                            credential_id
                        ),
                },
            )

            assert replay.status_code == 400

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_registration_completion_rejects_another_users_challenge(
    tmp_path,
) -> None:
    init_db()

    username = (
        "passkey-api-owner-user"
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

    foreign_token, _ = (
        create_auth_challenge(
            username=(
                "different-dashboard-user"
            ),
            purpose=(
                "passkey_registration"
            ),
            metadata={
                "webauthn_challenge":
                    _b64url(
                        b"x"
                        * 32
                    ),
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
            headers = _login(
                client,
                username=username,
                password=password,
            )

            response = client.post(
                (
                    "/api/auth/mfa/passkeys/"
                    "register/complete"
                ),
                headers=headers,
                json={
                    "challenge_token":
                        foreign_token,
                    "credential":
                        _credential(
                            b"foreign-credential"
                        ),
                },
            )

        assert response.status_code == 403

        assert (
            response.json()[
                "detail"
            ]
            == (
                "Passkey registration challenge "
                "does not belong to this user"
            )
        )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_passkey_registration_models_reject_unknown_fields(
    tmp_path,
) -> None:
    init_db()

    username = (
        "passkey-api-strict-user"
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
        with TestClient(
            app
        ) as client:
            headers = _login(
                client,
                username=username,
                password=password,
            )

            begin_response = client.post(
                "/api/auth/mfa/passkeys/register",
                headers=headers,
                json={
                    "current_password":
                        password,
                    "unexpected":
                        True,
                },
            )

            complete_response = client.post(
                (
                    "/api/auth/mfa/passkeys/"
                    "register/complete"
                ),
                headers=headers,
                json={
                    "challenge_token":
                        "opaque-test-token",
                    "credential":
                        {},
                    "unexpected":
                        True,
                },
            )

        assert begin_response.status_code == 422
        assert complete_response.status_code == 422

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )
