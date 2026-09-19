from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

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


def _basic(
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
            f"Basic {token}",
    }


def _clear_rootadmin_auth_state() -> None:
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
                    == "rootadmin"
                )
            )

        db.execute(
            delete(
                DashboardAuthEvent
            ).where(
                DashboardAuthEvent
                .target_username
                == "rootadmin"
            )
        )

        db.execute(
            delete(
                DashboardAuthRateLimitEvent
            )
        )


def test_bearer_logout_revokes_only_current_session() -> None:
    init_db()
    _clear_rootadmin_auth_state()

    try:
        with TestClient(
            app
        ) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "username":
                        "rootadmin",
                    "password":
                        "rootadmin-test-password",
                },
            )

            assert (
                login.status_code
                == 200
            )

            payload = login.json()

            assert (
                payload[
                    "status"
                ]
                == "authenticated"
            )

            assert (
                payload[
                    "token_type"
                ]
                == "bearer"
            )

            token = payload[
                "access_token"
            ]

            headers = {
                "Authorization":
                    f"Bearer {token}",
            }

            before = client.get(
                "/api/auth/me",
                headers=headers,
            )

            assert (
                before.status_code
                == 200
            )

            logout = client.post(
                "/api/auth/logout",
                headers=headers,
            )

            assert (
                logout.status_code
                == 200
            )

            logout_payload = (
                logout.json()
            )

            assert (
                logout_payload[
                    "status"
                ]
                == "revoked"
            )

            assert (
                logout_payload[
                    "user"
                ][
                    "username"
                ]
                == "rootadmin"
            )

            assert (
                logout_payload[
                    "gate_write_performed"
                ]
                is False
            )

            assert (
                "access_token"
                not in logout_payload
            )

            assert (
                token
                not in logout.text
            )

            after = client.get(
                "/api/auth/me",
                headers=headers,
            )

            assert (
                after.status_code
                == 401
            )

            assert (
                after.headers[
                    "www-authenticate"
                ]
                == "Bearer"
            )

        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(
                        DashboardAuthSession
                    ).where(
                        DashboardAuthSession
                        .username
                        == "rootadmin"
                    )
                )
            )

            assert len(
                rows
            ) == 1

            assert (
                rows[0].revoked_at
                is not None
            )

    finally:
        _clear_rootadmin_auth_state()


def test_basic_auth_cannot_be_mistaken_for_bearer_session() -> None:
    init_db()
    _clear_rootadmin_auth_state()

    try:
        headers = _basic(
            "rootadmin",
            "rootadmin-test-password",
        )

        with TestClient(
            app
        ) as client:
            logout = client.post(
                "/api/auth/logout",
                headers=headers,
            )

            assert (
                logout.status_code
                == 400
            )

            assert (
                logout.json()[
                    "detail"
                ]
                == "Bearer session required"
            )

            me = client.get(
                "/api/auth/me",
                headers=headers,
            )

            assert (
                me.status_code
                == 200
            )

            assert (
                me.json()[
                    "user"
                ][
                    "username"
                ]
                == "rootadmin"
            )

    finally:
        _clear_rootadmin_auth_state()
