from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlalchemy import delete, select

import app.auth_login as auth_login
from app.auth_login import (
    begin_password_login,
    complete_mfa_login,
)
from app.auth_mfa import (
    complete_totp_enrollment_with_recovery,
)
from app.auth_recovery import (
    hash_recovery_code,
    recovery_code_status,
)
from app.auth_state import (
    generate_auth_encryption_key,
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
        dashboard_auth_session_ttl_seconds=3600,
        dashboard_auth_challenge_ttl_seconds=300,
        dashboard_mfa_required=False,
        dashboard_auth_rate_limit_enabled=False,
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


def _challenge_row(
    token: str,
):
    digest = hash_opaque_token(
        token
    )

    with session_scope() as db:
        return db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == digest
            )
        )


def test_totp_counter_and_challenge_roll_back_when_session_issue_fails(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "atomic-totp-user"
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
        12,
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

    started = begin_password_login(
        username=username,
        password=password,
        settings=settings,
        now=login_at,
    )

    challenge_token = (
        started[
            "challenge_token"
        ]
    )

    code = pyotp.TOTP(
        enrolled[
            "secret"
        ]
    ).at(
        login_at
    )

    with session_scope() as db:
        factor = db.get(
            DashboardAuthFactor,
            username,
        )

        assert factor is not None

        previous_counter = (
            factor
            .totp_last_used_counter
        )

        assert (
            previous_counter
            is not None
        )

    def fail_session_issue(
        *args,
        **kwargs,
    ):
        raise RuntimeError(
            "simulated session issuance failure"
        )

    with monkeypatch.context() as patch:
        patch.setattr(
            auth_login,
            "create_auth_session_in_session",
            fail_session_issue,
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "simulated session "
                "issuance failure"
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

    with session_scope() as db:
        factor = db.get(
            DashboardAuthFactor,
            username,
        )

        assert factor is not None

        assert (
            factor
            .totp_last_used_counter
            == previous_counter
        )

        challenge = db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == hash_opaque_token(
                    challenge_token
                )
            )
        )

        assert challenge is not None
        assert (
            challenge.consumed_at
            is None
        )

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

    # The exact same one-time code and challenge remain usable because
    # the failed session issuance rolled the whole transaction back.
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
        completed[
            "session"
        ][
            "auth_method"
        ]
        == "password_totp"
    )

    with session_scope() as db:
        factor = db.get(
            DashboardAuthFactor,
            username,
        )

        assert factor is not None

        assert (
            factor
            .totp_last_used_counter
            > previous_counter
        )

        challenge = db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == hash_opaque_token(
                    challenge_token
                )
            )
        )

        assert challenge is not None
        assert (
            challenge.consumed_at
            is not None
        )


def test_recovery_code_and_challenge_roll_back_when_session_issue_fails(
    tmp_path,
    monkeypatch,
) -> None:
    init_db()

    username = (
        "atomic-recovery-user"
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
        13,
        0,
        tzinfo=UTC,
    )

    enrolled = _enroll(
        username=username,
        settings=settings,
        now=enrolled_at,
    )

    recovery_code = (
        enrolled[
            "recovery_codes"
        ][0]
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

    challenge_token = (
        started[
            "challenge_token"
        ]
    )

    code_hash = (
        hash_recovery_code(
            recovery_code
        )
    )

    def fail_session_issue(
        *args,
        **kwargs,
    ):
        raise RuntimeError(
            "simulated session issuance failure"
        )

    with monkeypatch.context() as patch:
        patch.setattr(
            auth_login,
            "create_auth_session_in_session",
            fail_session_issue,
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "simulated session "
                "issuance failure"
            ),
        ):
            complete_mfa_login(
                challenge_token=(
                    challenge_token
                ),
                method="recovery",
                code=recovery_code,
                settings=settings,
                now=login_at,
            )

    with session_scope() as db:
        recovery = db.scalar(
            select(
                DashboardAuthRecoveryCode
            ).where(
                DashboardAuthRecoveryCode
                .username
                == username,
                DashboardAuthRecoveryCode
                .code_hash
                == code_hash,
            )
        )

        assert recovery is not None
        assert (
            recovery.consumed_at
            is None
        )

        challenge = db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == hash_opaque_token(
                    challenge_token
                )
            )
        )

        assert challenge is not None
        assert (
            challenge.consumed_at
            is None
        )

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

    assert (
        recovery_code_status(
            username
        )[
            "active_count"
        ]
        == 10
    )

    # Retry the same challenge and same recovery code. Both should
    # still be valid because the failed transaction consumed neither.
    completed = complete_mfa_login(
        challenge_token=(
            challenge_token
        ),
        method="recovery",
        code=recovery_code,
        settings=settings,
        now=login_at,
    )

    assert (
        completed[
            "session"
        ][
            "auth_method"
        ]
        == "password_recovery"
    )

    assert (
        recovery_code_status(
            username
        )[
            "active_count"
        ]
        == 9
    )

    with session_scope() as db:
        recovery = db.scalar(
            select(
                DashboardAuthRecoveryCode
            ).where(
                DashboardAuthRecoveryCode
                .username
                == username,
                DashboardAuthRecoveryCode
                .code_hash
                == code_hash,
            )
        )

        assert recovery is not None
        assert (
            recovery.consumed_at
            is not None
        )

        challenge = db.scalar(
            select(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .token_hash
                == hash_opaque_token(
                    challenge_token
                )
            )
        )

        assert challenge is not None
        assert (
            challenge.consumed_at
            is not None
        )
