from __future__ import annotations

from datetime import (
    UTC,
    datetime,
    timedelta,
)

from fastapi.testclient import (
    TestClient,
)
from sqlalchemy import (
    create_engine,
    delete,
    inspect,
    select,
)

from app.auth_state import (
    create_auth_session,
    touch_auth_session,
)
from app.db import (
    Base,
    init_db,
    session_scope,
)
from app.main import app
from app.migrations import (
    migrate_database,
)
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


def test_existing_auth_session_table_gets_metadata_columns(
    tmp_path,
) -> None:
    path = (
        tmp_path
        / "auth-session-metadata.db"
    )

    engine = create_engine(
        f"sqlite:///{path}"
    )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE dashboard_auth_sessions (
                id INTEGER PRIMARY KEY,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                username VARCHAR(64) NOT NULL,
                credential_fingerprint VARCHAR(64) NOT NULL,
                auth_method VARCHAR(32) NOT NULL,
                mfa_completed BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                last_seen_at DATETIME,
                revoked_at DATETIME
            )
            """
        )

        connection.exec_driver_sql(
            """
            INSERT INTO dashboard_auth_sessions
            (
                id,
                token_hash,
                username,
                credential_fingerprint,
                auth_method,
                mfa_completed,
                created_at,
                expires_at,
                last_seen_at,
                revoked_at
            )
            VALUES
            (
                7,
                ?,
                'migration-user',
                ?,
                'password_totp',
                1,
                '2026-09-22 12:00:00',
                '2026-09-22 13:00:00',
                NULL,
                NULL
            )
            """,
            (
                "a" * 64,
                "b" * 64,
            ),
        )

    migrate_database(
        engine
    )

    # Must be idempotent.
    migrate_database(
        engine
    )

    Base.metadata.create_all(
        engine
    )

    inspector = inspect(
        engine
    )

    columns = {
        column["name"]
        for column
        in inspector.get_columns(
            "dashboard_auth_sessions"
        )
    }

    assert (
        "client_ip"
        in columns
    )

    assert (
        "user_agent"
        in columns
    )

    with engine.connect() as connection:
        row = (
            connection
            .exec_driver_sql(
                """
                SELECT
                    id,
                    token_hash,
                    credential_fingerprint,
                    client_ip,
                    user_agent
                FROM dashboard_auth_sessions
                WHERE id=7
                """
            )
            .mappings()
            .one()
        )

    assert row[
        "token_hash"
    ] == "a" * 64

    assert row[
        "credential_fingerprint"
    ] == "b" * 64

    assert (
        row["client_ip"]
        is None
    )

    assert (
        row["user_agent"]
        is None
    )


def test_session_origin_metadata_is_sanitized_and_touch_is_throttled() -> None:
    init_db()

    username = (
        "session-metadata-user"
    )

    with session_scope() as db:
        db.execute(
            delete(
                DashboardAuthSession
            ).where(
                DashboardAuthSession
                .username
                == username
            )
        )

    reference = datetime(
        2026,
        9,
        22,
        12,
        0,
        tzinfo=UTC,
    )

    token, session = (
        create_auth_session(
            username=username,
            credential_hash=(
                "c" * 64
            ),
            auth_method=(
                "password_totp"
            ),
            mfa_completed=True,
            ttl_seconds=3600,
            client_ip=(
                " 203.0.113.17\r\n "
            ),
            user_agent=(
                " Browser\r\n"
                " Agent "
            ),
            now=reference,
        )
    )

    assert (
        session[
            "client_ip"
        ]
        == "203.0.113.17"
    )

    assert (
        session[
            "user_agent"
        ]
        == "Browser Agent"
    )

    assert (
        session[
            "last_seen_at"
        ]
        == reference.isoformat()
    )

    early = touch_auth_session(
        token,
        now=(
            reference
            + timedelta(
                seconds=30
            )
        ),
    )

    assert early is not None

    assert (
        early[
            "last_seen_at"
        ]
        == reference.isoformat()
    )

    later_at = (
        reference
        + timedelta(
            seconds=61
        )
    )

    later = touch_auth_session(
        token,
        now=later_at,
    )

    assert later is not None

    assert (
        later[
            "last_seen_at"
        ]
        == later_at.isoformat()
    )

    with session_scope() as db:
        db.execute(
            delete(
                DashboardAuthSession
            ).where(
                DashboardAuthSession
                .username
                == username
            )
        )


def test_login_persists_observed_peer_and_user_agent_not_forwarded_ip() -> None:
    init_db()
    _clear_rootadmin_auth_state()

    try:
        with TestClient(
            app
        ) as client:
            login = client.post(
                "/api/auth/login",
                headers={
                    "User-Agent":
                        "A7C489B2-test-browser/1.0",
                    "X-Forwarded-For":
                        "203.0.113.250",
                    "X-Real-IP":
                        "203.0.113.251",
                },
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

            token = str(
                payload[
                    "access_token"
                ]
            )

            listing = client.get(
                "/api/auth/sessions",
                headers={
                    "Authorization":
                        f"Bearer {token}",
                },
            )

            assert (
                listing.status_code
                == 200
            )

            sessions = (
                listing.json()[
                    "sessions"
                ]
            )

            assert len(
                sessions
            ) == 1

            session = sessions[
                0
            ]

            assert (
                session[
                    "current"
                ]
                is True
            )

            assert (
                session[
                    "client_ip"
                ]
                == "testclient"
            )

            assert (
                session[
                    "user_agent"
                ]
                == (
                    "A7C489B2-"
                    "test-browser/1.0"
                )
            )

            assert (
                session[
                    "last_seen_at"
                ]
                is not None
            )

            assert (
                session[
                    "client_ip"
                ]
                != "203.0.113.250"
            )

            assert (
                session[
                    "client_ip"
                ]
                != "203.0.113.251"
            )

        with session_scope() as db:
            row = db.scalar(
                select(
                    DashboardAuthSession
                ).where(
                    DashboardAuthSession
                    .username
                    == "rootadmin"
                )
            )

            assert row is not None

            assert (
                row.client_ip
                == "testclient"
            )

            assert (
                row.user_agent
                == (
                    "A7C489B2-"
                    "test-browser/1.0"
                )
            )

            assert (
                row.last_seen_at
                is not None
            )

    finally:
        _clear_rootadmin_auth_state()
