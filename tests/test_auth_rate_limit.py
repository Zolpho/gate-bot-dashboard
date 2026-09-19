from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.auth_login import (
    LoginDenied,
    begin_password_login,
)
from app.auth_rate_limit import (
    MFA_LOGIN,
    PASSWORD_LOGIN,
    AuthRateLimitExceeded,
    enforce_auth_rate_limit,
    hash_rate_limit_subject,
)
from app.config import Settings
from app.db import (
    init_db,
    session_scope,
)
from app.models import (
    DashboardAuthRateLimitEvent,
)
from app.security import hash_password


def _settings(
    tmp_path,
    *,
    password_limit: int = 10,
    mfa_user_limit: int = 10,
    mfa_challenge_limit: int = 5,
    client_limit: int = 30,
    enabled: bool = True,
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
                            "rate-user",
                        "password_hash":
                            hash_password(
                                "password-test-123",
                                iterations=100_000,
                            ),
                        "account_ids": [
                            "rate-user",
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
        dashboard_auth_rate_limit_enabled=(
            enabled
        ),
        dashboard_auth_password_attempt_limit=(
            password_limit
        ),
        dashboard_auth_password_attempt_window_seconds=(
            300
        ),
        dashboard_auth_mfa_user_attempt_limit=(
            mfa_user_limit
        ),
        dashboard_auth_mfa_challenge_attempt_limit=(
            mfa_challenge_limit
        ),
        dashboard_auth_mfa_attempt_window_seconds=(
            300
        ),
        dashboard_auth_client_attempt_limit=(
            client_limit
        ),
        dashboard_auth_client_attempt_window_seconds=(
            300
        ),
    )


def _clear_rate_events() -> None:
    with session_scope() as db:
        db.execute(
            delete(
                DashboardAuthRateLimitEvent
            )
        )


def test_password_login_failures_are_persistently_throttled(
    tmp_path,
) -> None:
    init_db()
    _clear_rate_events()

    settings = _settings(
        tmp_path,
        password_limit=2,
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    for _ in range(2):
        with pytest.raises(
            LoginDenied,
            match="Invalid username or password",
        ):
            begin_password_login(
                username="rate-user",
                password="wrong-password-123",
                settings=settings,
                client_identifier="client-a",
                now=reference,
            )

    with pytest.raises(
        AuthRateLimitExceeded,
    ) as exc_info:
        begin_password_login(
            username="rate-user",
            password="wrong-password-123",
            settings=settings,
            client_identifier="client-a",
            now=reference,
        )

    assert (
        exc_info.value.scope
        == "username"
    )

    username_hash = (
        hash_rate_limit_subject(
            "rate-user"
        )
    )

    client_hash = (
        hash_rate_limit_subject(
            "client-a"
        )
    )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthRateLimitEvent
                )
            )
        )

    assert len(
        rows
    ) == 2

    assert {
        row.username_hash
        for row in rows
    } == {
        username_hash,
    }

    assert {
        row.client_hash
        for row in rows
    } == {
        client_hash,
    }

    serialized = json.dumps(
        [
            {
                "username_hash":
                    row.username_hash,
                "client_hash":
                    row.client_hash,
                "challenge_hash":
                    row.challenge_hash,
            }
            for row in rows
        ]
    )

    assert "rate-user" not in serialized
    assert "client-a" not in serialized
    assert "wrong-password-123" not in serialized


def test_client_bucket_spans_users_and_auth_actions(
    tmp_path,
) -> None:
    init_db()
    _clear_rate_events()

    settings = _settings(
        tmp_path,
        client_limit=2,
        password_limit=20,
        mfa_user_limit=20,
        mfa_challenge_limit=20,
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    enforce_auth_rate_limit(
        settings=settings,
        username="user-one",
        action=PASSWORD_LOGIN,
        client_identifier="shared-client",
        now=reference,
    )

    enforce_auth_rate_limit(
        settings=settings,
        username="user-two",
        action=MFA_LOGIN,
        client_identifier="shared-client",
        challenge_token="opaque-challenge-a",
        now=reference,
    )

    with pytest.raises(
        AuthRateLimitExceeded,
    ) as exc_info:
        enforce_auth_rate_limit(
            settings=settings,
            username="user-three",
            action=PASSWORD_LOGIN,
            client_identifier="shared-client",
            now=reference,
        )

    assert (
        exc_info.value.scope
        == "client"
    )


def test_mfa_username_bucket_spans_fresh_challenges(
    tmp_path,
) -> None:
    init_db()
    _clear_rate_events()

    settings = _settings(
        tmp_path,
        mfa_user_limit=2,
        mfa_challenge_limit=10,
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    for token in (
        "opaque-challenge-one",
        "opaque-challenge-two",
    ):
        enforce_auth_rate_limit(
            settings=settings,
            username="mfa-user",
            action=MFA_LOGIN,
            challenge_token=token,
            now=reference,
        )

    with pytest.raises(
        AuthRateLimitExceeded,
    ) as exc_info:
        enforce_auth_rate_limit(
            settings=settings,
            username="mfa-user",
            action=MFA_LOGIN,
            challenge_token="opaque-challenge-three",
            now=reference,
        )

    assert (
        exc_info.value.scope
        == "username"
    )


def test_mfa_challenge_bucket_blocks_repeated_factor_guessing(
    tmp_path,
) -> None:
    init_db()
    _clear_rate_events()

    settings = _settings(
        tmp_path,
        mfa_user_limit=20,
        mfa_challenge_limit=2,
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    token = (
        "opaque-challenge-repeat"
    )

    for _ in range(2):
        enforce_auth_rate_limit(
            settings=settings,
            username="mfa-challenge-user",
            action=MFA_LOGIN,
            challenge_token=token,
            now=reference,
        )

    with pytest.raises(
        AuthRateLimitExceeded,
    ) as exc_info:
        enforce_auth_rate_limit(
            settings=settings,
            username="mfa-challenge-user",
            action=MFA_LOGIN,
            challenge_token=token,
            now=reference,
        )

    assert (
        exc_info.value.scope
        == "challenge"
    )


def test_rate_limit_window_expires(
    tmp_path,
) -> None:
    init_db()
    _clear_rate_events()

    settings = _settings(
        tmp_path,
        password_limit=1,
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    first = enforce_auth_rate_limit(
        settings=settings,
        username="window-user",
        action=PASSWORD_LOGIN,
        now=reference,
    )

    assert first is not None

    second = enforce_auth_rate_limit(
        settings=settings,
        username="window-user",
        action=PASSWORD_LOGIN,
        now=(
            reference
            + timedelta(
                seconds=301
            )
        ),
    )

    assert second is not None
    assert (
        second[
            "username_count"
        ]
        == 1
    )


def test_disabled_rate_limit_records_nothing(
    tmp_path,
) -> None:
    init_db()
    _clear_rate_events()

    settings = _settings(
        tmp_path,
        enabled=False,
    )

    result = enforce_auth_rate_limit(
        settings=settings,
        username="disabled-user",
        action=PASSWORD_LOGIN,
        client_identifier="disabled-client",
    )

    assert result is None

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthRateLimitEvent
                )
            )
        )

    assert rows == []
