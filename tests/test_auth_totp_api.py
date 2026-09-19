from __future__ import annotations

import base64
from datetime import UTC, datetime

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.auth_mfa as auth_mfa
import app.auth_totp as auth_totp
from app.auth_state import (
    generate_auth_encryption_key,
)
from app.config import (
    Settings,
    get_settings,
)
from app.db import session_scope
from app.main import app
from app.models import (
    DashboardAuthFactor,
)


def _auth(
    username: str,
    password: str,
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode(
        "ascii"
    )

    return {
        "Authorization":
            f"Basic {token}"
    }


ROOT = _auth(
    "rootadmin",
    "rootadmin-test-password",
)


def _settings(
    tmp_path,
) -> Settings:
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
        dashboard_auth_encryption_key_file=(
            key_path
        ),
        dashboard_mfa_required=False,
    )


def test_totp_api_requires_existing_authentication(
    tmp_path,
) -> None:
    settings = _settings(
        tmp_path
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            assert (
                client.get(
                    "/api/auth/mfa/totp"
                ).status_code
                == 401
            )

            assert (
                client.post(
                    "/api/auth/mfa/totp/enroll"
                ).status_code
                == 401
            )

            assert (
                client.post(
                    "/api/auth/mfa/totp/confirm",
                    json={
                        "code": "123456",
                    },
                ).status_code
                == 401
            )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_totp_api_enrolls_only_authenticated_user_and_returns_png_qr(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(
        tmp_path
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    monkeypatch.setattr(
        auth_totp,
        "utcnow",
        lambda: reference,
    )

    monkeypatch.setattr(
        auth_mfa,
        "utcnow",
        lambda: reference,
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            initial = client.get(
                "/api/auth/mfa/totp",
                headers=ROOT,
            )

            assert (
                initial.status_code
                == 200
            )

            initial_body = (
                initial.json()
            )

            assert (
                initial_body[
                    "factor"
                ][
                    "username"
                ]
                == "rootadmin"
            )

            assert (
                initial_body[
                    "factor"
                ][
                    "totp_enabled"
                ]
                is False
            )

            assert (
                initial_body[
                    "mfa_required"
                ]
                is False
            )

            assert (
                initial_body[
                    "gate_write_performed"
                ]
                is False
            )

            enrolled = client.post(
                "/api/auth/mfa/totp/enroll",
                headers=ROOT,
            )

            assert (
                enrolled.status_code
                == 200
            )

            body = (
                enrolled.json()
            )

            assert (
                body["status"]
                == "pending"
            )

            assert (
                body["factor"][
                    "username"
                ]
                == "rootadmin"
            )

            assert (
                body["factor"][
                    "totp_enabled"
                ]
                is False
            )

            assert (
                body["mfa_required"]
                is False
            )

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
            )

            secret = body[
                "secret"
            ]

            assert secret
            assert (
                "ciphertext"
                not in body
            )

            assert (
                body[
                    "provisioning_uri"
                ].startswith(
                    "otpauth://totp/"
                )
            )

            qr_data_uri = body[
                "qr_data_uri"
            ]

            assert (
                qr_data_uri.startswith(
                    "data:image/png;base64,"
                )
            )

            qr_bytes = (
                base64.b64decode(
                    qr_data_uri.split(
                        ",",
                        1,
                    )[1]
                )
            )

            assert qr_bytes.startswith(
                b"\x89PNG\r\n\x1a\n"
            )

            with session_scope() as db:
                row = db.scalar(
                    select(
                        DashboardAuthFactor
                    ).where(
                        DashboardAuthFactor
                        .username
                        == "rootadmin"
                    )
                )

                assert row is not None

                assert (
                    row
                    .totp_secret_ciphertext
                    != secret
                )

                assert (
                    secret
                    not in row
                    .totp_secret_ciphertext
                )

                assert (
                    row
                    .totp_enabled
                    is False
                )

            generator = pyotp.TOTP(
                secret
            )

            code = generator.at(
                reference
            )

            confirmed = client.post(
                "/api/auth/mfa/totp/confirm",
                headers=ROOT,
                json={
                    "code": code,
                },
            )

            assert (
                confirmed.status_code
                == 200
            )

            confirmed_body = (
                confirmed.json()
            )

            assert (
                confirmed_body[
                    "status"
                ]
                == "enabled"
            )

            assert (
                confirmed_body[
                    "factor"
                ][
                    "username"
                ]
                == "rootadmin"
            )

            assert (
                confirmed_body[
                    "factor"
                ][
                    "totp_enabled"
                ]
                is True
            )

            assert (
                confirmed_body[
                    "factor"
                ][
                    "totp_confirmed_at"
                ]
            )

            assert (
                confirmed_body[
                    "mfa_required"
                ]
                is False
            )

            assert (
                confirmed_body[
                    "gate_write_performed"
                ]
                is False
            )

            recovery_codes = (
                confirmed_body[
                    "recovery_codes"
                ]
            )

            assert len(
                recovery_codes
            ) == 10

            assert len(
                set(
                    recovery_codes
                )
            ) == 10

            assert (
                confirmed_body[
                    "recovery_code_count"
                ]
                == 10
            )

            status_after = client.get(
                "/api/auth/mfa/totp",
                headers=ROOT,
            )

            assert (
                status_after.status_code
                == 200
            )

            status_body = (
                status_after.json()
            )

            assert (
                "recovery_codes"
                not in status_body
            )

            assert (
                status_body[
                    "factor"
                ][
                    "totp_enabled"
                ]
                is True
            )

            # Enabled enrollment cannot be silently
            # replaced with a new seed.
            repeated = client.post(
                "/api/auth/mfa/totp/enroll",
                headers=ROOT,
            )

            assert (
                repeated.status_code
                == 400
            )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_totp_confirm_request_requires_six_digits(
    tmp_path,
) -> None:
    settings = _settings(
        tmp_path
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            for invalid in (
                "",
                "12345",
                "1234567",
                "abcdef",
                "12 345",
            ):
                response = client.post(
                    "/api/auth/mfa/totp/confirm",
                    headers=ROOT,
                    json={
                        "code": invalid,
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
