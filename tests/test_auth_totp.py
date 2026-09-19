from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlalchemy import select

from app.auth_state import (
    generate_auth_encryption_key,
)
from app.auth_totp import (
    TotpSecretError,
    begin_totp_enrollment,
    confirm_totp_enrollment,
    decrypt_totp_secret,
    encrypt_totp_secret,
    totp_status,
    verify_totp_for_user,
)
from app.config import Settings
from app.db import (
    init_db,
    session_scope,
)
from app.models import (
    DashboardAuthFactor,
)


def _settings(
    tmp_path,
    *,
    filename: str = "dashboard_auth.key",
) -> Settings:
    key_path = (
        tmp_path
        / filename
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
        )
    )


def test_totp_secret_encryption_round_trip(tmp_path) -> None:
    settings = _settings(
        tmp_path
    )

    secret = (
        pyotp.random_base32()
    )

    ciphertext = (
        encrypt_totp_secret(
            secret,
            settings=settings,
        )
    )

    assert ciphertext
    assert ciphertext != secret
    assert secret not in ciphertext

    assert (
        decrypt_totp_secret(
            ciphertext,
            settings=settings,
        )
        == secret
    )


def test_totp_ciphertext_fails_with_wrong_key(tmp_path) -> None:
    first = _settings(
        tmp_path,
        filename="first.key",
    )

    second = _settings(
        tmp_path,
        filename="second.key",
    )

    secret = (
        pyotp.random_base32()
    )

    ciphertext = (
        encrypt_totp_secret(
            secret,
            settings=first,
        )
    )

    with pytest.raises(
        TotpSecretError
    ):
        decrypt_totp_secret(
            ciphertext,
            settings=second,
        )


def test_totp_enrollment_confirmation_and_replay_protection(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    username = (
        "totp-replay-user"
    )

    enrollment = (
        begin_totp_enrollment(
            username=username,
            settings=settings,
        )
    )

    secret = enrollment[
        "secret"
    ]

    assert enrollment[
        "provisioning_uri"
    ].startswith(
        "otpauth://totp/"
    )

    assert (
        "Gate%20Bot%20Dashboard"
        in enrollment[
            "provisioning_uri"
        ]
        or "Gate+Bot+Dashboard"
        in enrollment[
            "provisioning_uri"
        ]
    )

    pending = totp_status(
        username
    )

    assert pending[
        "totp_enabled"
    ] is False

    assert pending[
        "has_totp_secret"
    ] is True

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthFactor
            ).where(
                DashboardAuthFactor
                .username
                == username
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
            .totp_last_used_counter
            is None
        )

    first_time = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    generator = pyotp.TOTP(
        secret
    )

    first_code = (
        generator.at(
            first_time
        )
    )

    assert confirm_totp_enrollment(
        username=username,
        code=first_code,
        settings=settings,
        now=first_time,
    )

    enabled = totp_status(
        username
    )

    assert enabled[
        "totp_enabled"
    ] is True

    assert enabled[
        "totp_confirmed_at"
    ]

    # Confirmation consumed this moving counter.
    assert not verify_totp_for_user(
        username=username,
        code=first_code,
        settings=settings,
        now=first_time,
    )

    second_time = (
        first_time
        + timedelta(
            seconds=30
        )
    )

    second_code = (
        generator.at(
            second_time
        )
    )

    assert verify_totp_for_user(
        username=username,
        code=second_code,
        settings=settings,
        now=second_time,
    )

    # The exact same valid code cannot be replayed.
    assert not verify_totp_for_user(
        username=username,
        code=second_code,
        settings=settings,
        now=second_time,
    )


def test_invalid_totp_does_not_confirm_enrollment(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    username = (
        "totp-invalid-user"
    )

    begin_totp_enrollment(
        username=username,
        settings=settings,
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    assert not confirm_totp_enrollment(
        username=username,
        code="000000",
        settings=settings,
        now=reference,
    )

    status = totp_status(
        username
    )

    assert status[
        "totp_enabled"
    ] is False

    assert status[
        "totp_confirmed_at"
    ] is None

    assert status[
        "totp_last_used_counter"
    ] is None
