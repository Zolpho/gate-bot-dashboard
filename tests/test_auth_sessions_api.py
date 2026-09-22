from __future__ import annotations

import base64
import json

from fastapi.testclient import (
    TestClient,
)
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


def _login(
    client: TestClient,
) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "username":
                "rootadmin",
            "password":
                "rootadmin-test-password",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert (
        payload["status"]
        == "authenticated"
    )

    return str(
        payload["access_token"]
    )


def _bearer(
    token: str,
) -> dict[str, str]:
    return {
        "Authorization":
            f"Bearer {token}",
    }


def _basic() -> dict[str, str]:
    encoded = base64.b64encode(
        b"rootadmin:rootadmin-test-password"
    ).decode(
        "ascii"
    )

    return {
        "Authorization":
            f"Basic {encoded}",
    }


def test_active_sessions_are_sanitized_and_mark_current() -> None:
    init_db()
    _clear_rootadmin_auth_state()

    try:
        with TestClient(app) as client:
            first = _login(
                client
            )

            second = _login(
                client
            )

            response = client.get(
                "/api/auth/sessions",
                headers=_bearer(
                    second
                ),
            )

            assert (
                response.status_code
                == 200
            )

            body = response.json()

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
            )

            sessions = body[
                "sessions"
            ]

            assert len(
                sessions
            ) == 2

            assert sum(
                1
                for session in sessions
                if session[
                    "current"
                ]
            ) == 1

            expected_keys = {
                "id",
                "auth_method",
                "mfa_completed",
                "created_at",
                "expires_at",
                "client_ip",
                "user_agent",
                "last_seen_at",
                "current",
            }

            assert all(
                set(
                    session
                )
                == expected_keys
                for session in sessions
            )

            serialized = json.dumps(
                body,
                sort_keys=True,
            )

            for forbidden in (
                "token_hash",
                "credential_fingerprint",
                first,
                second,
            ):
                assert (
                    forbidden
                    not in serialized
                )

    finally:
        _clear_rootadmin_auth_state()


def test_user_can_revoke_one_other_active_session() -> None:
    init_db()
    _clear_rootadmin_auth_state()

    try:
        with TestClient(app) as client:
            first = _login(
                client
            )

            current = _login(
                client
            )

            listing = client.get(
                "/api/auth/sessions",
                headers=_bearer(
                    current
                ),
            )

            assert (
                listing.status_code
                == 200
            )

            other = next(
                session
                for session
                in listing.json()[
                    "sessions"
                ]
                if not session[
                    "current"
                ]
            )

            revoke = client.post(
                (
                    "/api/auth/sessions/"
                    f"{other['id']}/revoke"
                ),
                headers=_bearer(
                    current
                ),
            )

            assert (
                revoke.status_code
                == 200
            )

            body = revoke.json()

            assert (
                body[
                    "status"
                ]
                == "revoked"
            )

            assert (
                body[
                    "session"
                ][
                    "id"
                ]
                == other[
                    "id"
                ]
            )

            assert (
                body[
                    "session"
                ][
                    "current"
                ]
                is False
            )

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
            )

            old_me = client.get(
                "/api/auth/me",
                headers=_bearer(
                    first
                ),
            )

            current_me = client.get(
                "/api/auth/me",
                headers=_bearer(
                    current
                ),
            )

            assert (
                old_me.status_code
                == 401
            )

            assert (
                current_me.status_code
                == 200
            )

        with session_scope() as db:
            events = list(
                db.scalars(
                    select(
                        DashboardAuthEvent
                    ).where(
                        DashboardAuthEvent
                        .target_username
                        == "rootadmin",
                        DashboardAuthEvent
                        .action
                        == "session_revoked",
                    )
                )
            )

            assert len(
                events
            ) == 1

            metadata = json.loads(
                events[0].metadata_json
            )

            assert (
                metadata[
                    "session_id"
                ]
                == other[
                    "id"
                ]
            )

            assert (
                metadata[
                    "current_session"
                ]
                is False
            )

            assert (
                metadata[
                    "source"
                ]
                == (
                    "security_"
                    "active_sessions"
                )
            )

    finally:
        _clear_rootadmin_auth_state()


def test_revoke_others_preserves_current_session() -> None:
    init_db()
    _clear_rootadmin_auth_state()

    try:
        with TestClient(app) as client:
            first = _login(
                client
            )

            second = _login(
                client
            )

            current = _login(
                client
            )

            response = client.post(
                "/api/auth/sessions/revoke-others",
                headers=_bearer(
                    current
                ),
            )

            assert (
                response.status_code
                == 200
            )

            body = response.json()

            assert (
                body[
                    "status"
                ]
                == "revoked"
            )

            assert (
                body[
                    "revoked_count"
                ]
                == 2
            )

            assert len(
                body[
                    "revoked_session_ids"
                ]
            ) == 2

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
            )

            assert (
                client.get(
                    "/api/auth/me",
                    headers=_bearer(
                        first
                    ),
                ).status_code
                == 401
            )

            assert (
                client.get(
                    "/api/auth/me",
                    headers=_bearer(
                        second
                    ),
                ).status_code
                == 401
            )

            assert (
                client.get(
                    "/api/auth/me",
                    headers=_bearer(
                        current
                    ),
                ).status_code
                == 200
            )

            listing = client.get(
                "/api/auth/sessions",
                headers=_bearer(
                    current
                ),
            )

            assert (
                listing.status_code
                == 200
            )

            sessions = listing.json()[
                "sessions"
            ]

            assert len(
                sessions
            ) == 1

            assert (
                sessions[0][
                    "current"
                ]
                is True
            )

        with session_scope() as db:
            events = list(
                db.scalars(
                    select(
                        DashboardAuthEvent
                    ).where(
                        DashboardAuthEvent
                        .target_username
                        == "rootadmin",
                        DashboardAuthEvent
                        .action
                        == "session_revoked",
                    )
                )
            )

            assert len(
                events
            ) == 2

    finally:
        _clear_rootadmin_auth_state()


def test_session_management_requires_bearer_session() -> None:
    init_db()
    _clear_rootadmin_auth_state()

    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/sessions",
                headers=_basic(),
            )

            assert (
                response.status_code
                == 400
            )

            assert (
                response.json()[
                    "detail"
                ]
                == "Bearer session required"
            )

    finally:
        _clear_rootadmin_auth_state()
