from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlalchemy import delete, select

from app.auth_login import (
    LoginDenied,
    MfaEnrollmentRequired,
    begin_password_login,
    complete_mfa_login,
    resolve_bearer_session,
)
from app.auth_mfa import (
    complete_totp_enrollment_with_recovery,
)
from app.auth_recovery import (
    recovery_code_status,
)
from app.auth_state import (
    generate_auth_encryption_key,
    get_auth_session,
    hash_opaque_token,
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
    DashboardAuthRecoveryCode,
    DashboardAuthSession,
)
from app.security import hash_password


def _write_user(
    path,
    *,
    username: str,
    password: str,
    enabled: bool = True,
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
                            enabled,
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
    mfa_required: bool = False,
) -> tuple[Settings, object]:
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

    settings = Settings(
        dashboard_users_file=(
            users_path
        ),
        dashboard_auth_encryption_key_file=(
            key_path
        ),
        dashboard_auth_session_ttl_seconds=(
            3600
        ),
        dashboard_auth_challenge_ttl_seconds=(
            300
        ),
        dashboard_mfa_required=(
            mfa_required
        ),
    )

    return (
        settings,
        users_path,
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


def _enroll_mfa(
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


def test_password_only_bearer_session_when_mfa_not_enrolled(
    tmp_path,
) -> None:
    init_db()

    username = (
        "login-password-user"
    )

    password = (
        "password-test-123"
    )

    settings, _ = _settings(
        tmp_path,
        username=username,
        password=password,
    )

    _clear(
        username
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    result = begin_password_login(
        username=username,
        password=password,
        settings=settings,
        now=reference,
    )

    assert (
        result["status"]
        == "authenticated"
    )

    assert (
        result["token_type"]
        == "bearer"
    )

    token = result[
        "access_token"
    ]

    assert token

    assert (
        result["session"][
            "auth_method"
        ]
        == "password"
    )

    assert (
        result["session"][
            "mfa_completed"
        ]
        is False
    )

    resolved = resolve_bearer_session(
        token,
        settings=settings,
        now=reference,
    )

    assert resolved is not None

    assert (
        resolved["user"].username
        == username
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthSession
            ).where(
                DashboardAuthSession
                .username
                == username
            )
        )

        assert row is not None

        assert (
            row.token_hash
            == hash_opaque_token(
                token
            )
        )

        assert token != row.token_hash


def test_enrolled_user_gets_mfa_challenge_and_totp_session(
    tmp_path,
) -> None:
    init_db()

    username = (
        "login-totp-user"
    )

    password = (
        "password-test-123"
    )

    settings, _ = _settings(
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
        12,
        0,
        tzinfo=UTC,
    )

    enrolled = _enroll_mfa(
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

    started = begin_password_login(
        username=username,
        password=password,
        settings=settings,
        now=login_at,
    )

    assert (
        started["status"]
        == "mfa_required"
    )

    assert set(
        started["methods"]
    ) == {
        "totp",
        "recovery",
    }

    assert (
        "access_token"
        not in started
    )

    challenge_token = (
        started[
            "challenge_token"
        ]
    )

    challenge_metadata = (
        started[
            "challenge"
        ][
            "metadata"
        ]
    )

    serialized = json.dumps(
        challenge_metadata,
        sort_keys=True,
    )

    assert password not in serialized

    code = pyotp.TOTP(
        enrolled[
            "secret"
        ]
    ).at(
        login_at
    )

    completed = complete_mfa_login(
        challenge_token=(
            challenge_token
        ),
        method="totp",
        code=code,
        settings=settings,
        now=login_at,
    )

    assert (
        completed["status"]
        == "authenticated"
    )

    assert (
        completed["session"][
            "auth_method"
        ]
        == "password_totp"
    )

    assert (
        completed["session"][
            "mfa_completed"
        ]
        is True
    )

    resolved = resolve_bearer_session(
        completed[
            "access_token"
        ],
        settings=settings,
        now=login_at,
    )

    assert resolved is not None

    with pytest.raises(
        LoginDenied,
        match=(
            "Invalid or expired "
            "login challenge"
        ),
    ):
        complete_mfa_login(
            challenge_token=(
                challenge_token
            ),
            method="totp",
            code=code,
            settings=settings,
            now=login_at,
        )


def test_recovery_code_can_complete_mfa_login_once(
    tmp_path,
) -> None:
    init_db()

    username = (
        "login-recovery-user"
    )

    password = (
        "password-test-123"
    )

    settings, _ = _settings(
        tmp_path,
        username=username,
        password=password,
    )

    _clear(
        username
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    enrolled = _enroll_mfa(
        username=username,
        settings=settings,
        now=reference,
    )

    recovery_code = (
        enrolled[
            "recovery_codes"
        ][0]
    )

    login_at = (
        reference
        + timedelta(
            seconds=30
        )
    )

    started = begin_password_login(
        username=username,
        password=password,
        settings=settings,
        now=login_at,
    )

    completed = complete_mfa_login(
        challenge_token=(
            started[
                "challenge_token"
            ]
        ),
        method="recovery",
        code=recovery_code,
        settings=settings,
        now=login_at,
    )

    assert (
        completed["session"][
            "auth_method"
        ]
        == "password_recovery"
    )

    assert (
        completed["session"][
            "mfa_completed"
        ]
        is True
    )

    assert (
        recovery_code_status(
            username
        )[
            "active_count"
        ]
        == 9
    )

    second = begin_password_login(
        username=username,
        password=password,
        settings=settings,
        now=login_at,
    )

    with pytest.raises(
        LoginDenied,
        match="Invalid MFA code",
    ):
        complete_mfa_login(
            challenge_token=(
                second[
                    "challenge_token"
                ]
            ),
            method="recovery",
            code=recovery_code,
            settings=settings,
            now=login_at,
        )


def test_invalid_password_creates_no_auth_state(
    tmp_path,
) -> None:
    init_db()

    username = (
        "login-invalid-user"
    )

    settings, _ = _settings(
        tmp_path,
        username=username,
        password=(
            "password-test-123"
        ),
    )

    _clear(
        username
    )

    with pytest.raises(
        LoginDenied,
        match="Invalid username or password",
    ):
        begin_password_login(
            username=username,
            password="wrong-password-123",
            settings=settings,
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

        challenges = list(
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

    assert sessions == []
    assert challenges == []


def test_password_record_change_invalidates_existing_bearer_session(
    tmp_path,
) -> None:
    init_db()

    username = (
        "login-fingerprint-user"
    )

    old_password = (
        "old-password-123"
    )

    settings, users_path = _settings(
        tmp_path,
        username=username,
        password=old_password,
    )

    _clear(
        username
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    result = begin_password_login(
        username=username,
        password=old_password,
        settings=settings,
        now=reference,
    )

    token = result[
        "access_token"
    ]

    assert (
        resolve_bearer_session(
            token,
            settings=settings,
            now=reference,
        )
        is not None
    )

    _write_user(
        users_path,
        username=username,
        password=(
            "new-password-456"
        ),
    )

    assert (
        resolve_bearer_session(
            token,
            settings=settings,
            now=reference,
        )
        is None
    )

    assert (
        get_auth_session(
            token,
            now=reference,
        )
        is None
    )


def test_global_mfa_requirement_blocks_password_only_session(
    tmp_path,
) -> None:
    init_db()

    username = (
        "login-required-user"
    )

    password = (
        "password-test-123"
    )

    settings, _ = _settings(
        tmp_path,
        username=username,
        password=password,
        mfa_required=True,
    )

    _clear(
        username
    )

    with pytest.raises(
        MfaEnrollmentRequired,
        match="MFA enrollment is required",
    ):
        begin_password_login(
            username=username,
            password=password,
            settings=settings,
        )

    with session_scope() as db:
        rows = list(
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

    assert rows == []
