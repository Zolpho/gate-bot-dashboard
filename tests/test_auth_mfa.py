from __future__ import annotations

import json
from datetime import UTC, datetime

import pyotp
import pytest
from sqlalchemy import delete, select

from app.auth_mfa import (
    MfaAdminError,
    complete_totp_enrollment_with_recovery,
    reset_user_mfa,
)
from app.auth_recovery import (
    RECOVERY_CODE_COUNT,
    hash_recovery_code,
    recovery_code_status,
)
from app.auth_state import (
    consume_auth_challenge,
    create_auth_challenge,
    create_auth_session,
    generate_auth_encryption_key,
    get_auth_session,
)
from app.auth_totp import (
    begin_totp_enrollment,
    totp_status,
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
        )
    )


def _clear_auth_state(
    username: str,
) -> None:
    with session_scope() as db:
        db.execute(
            delete(
                DashboardAuthRecoveryCode
            ).where(
                DashboardAuthRecoveryCode
                .username
                == username
            )
        )

        db.execute(
            delete(
                DashboardAuthSession
            ).where(
                DashboardAuthSession
                .username
                == username
            )
        )

        db.execute(
            delete(
                DashboardAuthChallenge
            ).where(
                DashboardAuthChallenge
                .username
                == username
            )
        )

        db.execute(
            delete(
                DashboardAuthFactor
            ).where(
                DashboardAuthFactor
                .username
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


def test_complete_totp_enrollment_is_atomic_with_recovery(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    username = (
        "mfa-complete-user"
    )

    _clear_auth_state(
        username
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

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    code = pyotp.TOTP(
        secret
    ).at(
        reference
    )

    completed = (
        complete_totp_enrollment_with_recovery(
            username=username,
            code=code,
            settings=settings,
            now=reference,
        )
    )

    assert completed is not None

    assert (
        completed["status"]
        == "enabled"
    )

    codes = completed[
        "recovery_codes"
    ]

    assert len(
        codes
    ) == RECOVERY_CODE_COUNT

    assert len(
        set(codes)
    ) == RECOVERY_CODE_COUNT

    status = totp_status(
        username
    )

    assert status[
        "totp_enabled"
    ] is True

    assert status[
        "totp_last_used_counter"
    ] is not None

    recovery = (
        recovery_code_status(
            username
        )
    )

    assert (
        recovery[
            "active_count"
        ]
        == RECOVERY_CODE_COUNT
    )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthRecoveryCode
                ).where(
                    DashboardAuthRecoveryCode
                    .username
                    == username
                )
            )
        )

        events = list(
            db.scalars(
                select(
                    DashboardAuthEvent
                ).where(
                    DashboardAuthEvent
                    .target_username
                    == username
                )
            )
        )

    assert len(
        rows
    ) == RECOVERY_CODE_COUNT

    assert {
        row.code_hash
        for row in rows
    } == {
        hash_recovery_code(
            code_value
        )
        for code_value in codes
    }

    assert len(
        events
    ) == 1

    event = events[0]

    assert (
        event.action
        == "totp_enrollment_completed"
    )

    metadata = json.loads(
        event.metadata_json
    )

    assert metadata == {
        "recovery_code_count":
            RECOVERY_CODE_COUNT,
    }

    serialized_metadata = (
        event.metadata_json
    )

    assert secret not in serialized_metadata

    for recovery_code in codes:
        assert (
            recovery_code
            not in serialized_metadata
        )


def test_invalid_totp_confirmation_rolls_back_everything(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    username = (
        "mfa-invalid-user"
    )

    _clear_auth_state(
        username
    )

    enrollment = (
        begin_totp_enrollment(
            username=username,
            settings=settings,
        )
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    valid_code = pyotp.TOTP(
        enrollment[
            "secret"
        ]
    ).at(
        reference
    )

    invalid_code = (
        f"{(int(valid_code) + 1) % 1_000_000:06d}"
    )

    assert invalid_code != valid_code

    result = (
        complete_totp_enrollment_with_recovery(
            username=username,
            code=invalid_code,
            settings=settings,
            now=reference,
        )
    )

    assert result is None

    status = totp_status(
        username
    )

    assert status[
        "totp_enabled"
    ] is False

    assert (
        recovery_code_status(
            username
        )[
            "active_count"
        ]
        == 0
    )

    with session_scope() as db:
        event_count = len(
            list(
                db.scalars(
                    select(
                        DashboardAuthEvent
                    ).where(
                        DashboardAuthEvent
                        .target_username
                        == username
                    )
                )
            )
        )

    assert event_count == 0


def test_administrator_reset_revokes_all_auth_state(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    target = "zolnode"
    actor = "rootadmin"

    _clear_auth_state(
        target
    )

    enrollment = (
        begin_totp_enrollment(
            username=target,
            settings=settings,
        )
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    code = pyotp.TOTP(
        enrollment[
            "secret"
        ]
    ).at(
        reference
    )

    completed = (
        complete_totp_enrollment_with_recovery(
            username=target,
            code=code,
            settings=settings,
            now=reference,
        )
    )

    assert completed is not None

    session_token, _ = (
        create_auth_session(
            username=target,
            credential_hash=(
                "a" * 64
            ),
            ttl_seconds=600,
            now=reference,
        )
    )

    challenge_token, _ = (
        create_auth_challenge(
            username=target,
            purpose="login_mfa",
            ttl_seconds=300,
            now=reference,
        )
    )

    result = reset_user_mfa(
        actor_username=actor,
        target_username=target,
        reason=(
            "Lost authenticator device"
        ),
        settings=settings,
        now=reference,
    )

    assert result[
        "status"
    ] == "reset"

    assert (
        result[
            "target_username"
        ]
        == target
    )

    assert (
        result[
            "totp_was_enabled"
        ]
        is True
    )

    assert (
        result[
            "recovery_codes_revoked"
        ]
        == RECOVERY_CODE_COUNT
    )

    assert (
        result[
            "sessions_revoked"
        ]
        >= 1
    )

    assert (
        result[
            "challenges_consumed"
        ]
        >= 1
    )

    factor = totp_status(
        target
    )

    assert (
        factor[
            "totp_enabled"
        ]
        is False
    )

    assert (
        factor[
            "has_totp_secret"
        ]
        is False
    )

    assert (
        factor[
            "totp_last_used_counter"
        ]
        is None
    )

    assert (
        recovery_code_status(
            target
        )[
            "active_count"
        ]
        == 0
    )

    assert (
        get_auth_session(
            session_token,
            now=reference,
        )
        is None
    )

    assert (
        consume_auth_challenge(
            challenge_token,
            purpose="login_mfa",
            now=reference,
        )
        is None
    )

    with session_scope() as db:
        events = list(
            db.scalars(
                select(
                    DashboardAuthEvent
                ).where(
                    DashboardAuthEvent
                    .target_username
                    == target
                )
                .order_by(
                    DashboardAuthEvent
                    .id
                    .asc()
                )
            )
        )

    assert [
        event.action
        for event in events
    ] == [
        "totp_enrollment_completed",
        "mfa_reset",
    ]

    reset_event = events[-1]

    assert (
        reset_event.actor_username
        == actor
    )

    assert (
        reset_event.reason
        == "Lost authenticator device"
    )


def test_administrator_reset_rejects_unknown_dashboard_user(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    target = (
        "not-a-dashboard-user"
    )

    _clear_auth_state(
        target
    )

    with pytest.raises(
        MfaAdminError,
        match="Dashboard user not found",
    ):
        reset_user_mfa(
            actor_username="rootadmin",
            target_username=target,
            reason="Test reset",
            settings=settings,
        )

    with session_scope() as db:
        events = list(
            db.scalars(
                select(
                    DashboardAuthEvent
                ).where(
                    DashboardAuthEvent
                    .target_username
                    == target
                )
            )
        )

    assert events == []
