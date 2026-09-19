from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlalchemy import delete

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


def _clear_test_auth_state() -> None:
    usernames = (
        "rootadmin",
        "zolnode",
    )

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
                    model.username.in_(
                        usernames
                    )
                )
            )

        db.execute(
            delete(
                DashboardAuthEvent
            ).where(
                DashboardAuthEvent
                .target_username.in_(
                    usernames
                )
            )
        )

        db.execute(
            delete(
                DashboardAuthRateLimitEvent
            )
        )


def test_protected_api_accepts_bearer_and_keeps_basic_fallback() -> None:
    init_db()

    _clear_test_auth_state()

    try:
        with TestClient(
            app
        ) as client:
            basic_headers = _basic(
                "rootadmin",
                "rootadmin-test-password",
            )

            basic_me = client.get(
                "/api/auth/me",
                headers=basic_headers,
            )

            assert (
                basic_me.status_code
                == 200
            )

            assert (
                basic_me.json()[
                    "user"
                ][
                    "username"
                ]
                == "rootadmin"
            )

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

            login_payload = (
                login.json()
            )

            assert (
                login_payload[
                    "status"
                ]
                == "authenticated"
            )

            assert (
                login_payload[
                    "token_type"
                ]
                == "bearer"
            )

            assert (
                login_payload[
                    "session"
                ][
                    "auth_method"
                ]
                == "password"
            )

            token = login_payload[
                "access_token"
            ]

            bearer_headers = {
                "Authorization":
                    f"Bearer {token}",
            }

            bearer_me = client.get(
                "/api/auth/me",
                headers=bearer_headers,
            )

            assert (
                bearer_me.status_code
                == 200
            )

            assert (
                bearer_me.json()[
                    "user"
                ][
                    "username"
                ]
                == "rootadmin"
            )

            assert (
                bearer_me.json()[
                    "user"
                ][
                    "role"
                ]
                == "super_admin"
            )

            admin_route = client.get(
                "/api/auth/account-policies",
                headers=bearer_headers,
            )

            assert (
                admin_route.status_code
                == 200
            )

            assert (
                admin_route.json()[
                    "gate_write_performed"
                ]
                is False
            )

            operator_login = client.post(
                "/api/auth/login",
                json={
                    "username":
                        "zolnode",
                    "password":
                        "zolnode-test-password",
                },
            )

            assert (
                operator_login.status_code
                == 200
            )

            operator_payload = (
                operator_login.json()
            )

            assert (
                operator_payload[
                    "status"
                ]
                == "authenticated"
            )

            operator_token = (
                operator_payload[
                    "access_token"
                ]
            )

            operator_headers = {
                "Authorization":
                    f"Bearer {operator_token}",
            }

            own_balance = client.get(
                "/api/me/balance",
                headers=operator_headers,
            )

            assert (
                own_balance.status_code
                == 200
            )

            assert (
                own_balance.json()[
                    "account_id"
                ]
                == "zolnode"
            )

            forbidden_balance = client.get(
                (
                    "/api/me/balance"
                    "?account_id=arnold"
                ),
                headers=operator_headers,
            )

            assert (
                forbidden_balance.status_code
                == 403
            )

            invalid_bearer = (
                client.get(
                    "/api/auth/me",
                    headers={
                        "Authorization":
                            "Bearer invalid-token",
                    },
                )
            )

            assert (
                invalid_bearer.status_code
                == 401
            )

            assert (
                invalid_bearer.headers[
                    "www-authenticate"
                ]
                == "Bearer"
            )

            missing = client.get(
                "/api/auth/me"
            )

            assert (
                missing.status_code
                == 401
            )

            assert (
                missing.headers[
                    "www-authenticate"
                ].startswith(
                    "Basic"
                )
            )

            basic_again = client.get(
                "/api/auth/me",
                headers=basic_headers,
            )

            assert (
                basic_again.status_code
                == 200
            )

    finally:
        _clear_test_auth_state()
