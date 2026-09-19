from __future__ import annotations

import base64
import os
from datetime import UTC, datetime
from pathlib import Path

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth_mfa import (
    complete_totp_enrollment_with_recovery,
)
from app.auth_recovery import (
    RECOVERY_CODE_COUNT,
    recovery_code_status,
)
from app.auth_state import (
    generate_auth_encryption_key,
)
from app.auth_totp import (
    begin_totp_enrollment,
    totp_status,
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
    DashboardAuthRecoveryCode,
    DashboardAuthSession,
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

OPERATOR = _auth(
    "zolnode",
    "zolnode-test-password",
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
        dashboard_users_file=Path(
            os.environ[
                "DASHBOARD_USERS_FILE"
            ]
        ),
        dashboard_mfa_required=False,
    )


def _clear_target(
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


def _enable_totp(
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


def test_mfa_reset_api_requires_super_admin(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            unauthenticated = client.post(
                "/api/auth/mfa/users/arnold/reset",
                json={
                    "reason":
                        "Test reset",
                },
            )

            assert (
                unauthenticated.status_code
                == 401
            )

            denied = client.post(
                "/api/auth/mfa/users/arnold/reset",
                headers=OPERATOR,
                json={
                    "reason":
                        "Test reset",
                },
            )

            assert (
                denied.status_code
                == 403
            )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
        )


def test_super_admin_can_reset_target_mfa_with_audit(
    tmp_path,
) -> None:
    init_db()

    settings = _settings(
        tmp_path
    )

    target = "arnold"

    _clear_target(
        target
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    _enable_totp(
        username=target,
        settings=settings,
        now=reference,
    )

    assert (
        totp_status(
            target
        )[
            "totp_enabled"
        ]
        is True
    )

    assert (
        recovery_code_status(
            target
        )[
            "active_count"
        ]
        == RECOVERY_CODE_COUNT
    )

    app.dependency_overrides[
        get_settings
    ] = lambda: settings

    try:
        with TestClient(app) as client:
            response = client.post(
                (
                    "/api/auth/mfa/users/"
                    f"{target}/reset"
                ),
                headers=ROOT,
                json={
                    "reason":
                        "Lost authenticator device",
                },
            )

            assert (
                response.status_code
                == 200
            )

            body = response.json()

            assert (
                body["status"]
                == "reset"
            )

            assert (
                body[
                    "target_username"
                ]
                == target
            )

            assert (
                body[
                    "totp_was_enabled"
                ]
                is True
            )

            assert (
                body[
                    "recovery_codes_revoked"
                ]
                == RECOVERY_CODE_COUNT
            )

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
            )

    finally:
        app.dependency_overrides.pop(
            get_settings,
            None,
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
        recovery_code_status(
            target
        )[
            "active_count"
        ]
        == 0
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
        == "rootadmin"
    )

    assert (
        reset_event.reason
        == "Lost authenticator device"
    )
