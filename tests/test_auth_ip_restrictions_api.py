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
    DashboardAuthIpAllowlistEntry,
    DashboardAuthIpPolicy,
    DashboardAuthPasskeyCredential,
    DashboardAuthPasskeyUser,
    DashboardAuthRateLimitEvent,
    DashboardAuthRecoveryCode,
    DashboardAuthSession,
)


def _clear_user_state(
    username: str,
) -> None:
    with session_scope() as db:
        db.execute(
            delete(
                DashboardAuthIpAllowlistEntry
            ).where(
                DashboardAuthIpAllowlistEntry
                .username
                == username
            )
        )

        db.execute(
            delete(
                DashboardAuthIpPolicy
            ).where(
                DashboardAuthIpPolicy
                .username
                == username
            )
        )

        for model in (
            DashboardAuthRecoveryCode,
            DashboardAuthSession,
            DashboardAuthChallenge,
            DashboardAuthFactor,
            DashboardAuthPasskeyCredential,
            DashboardAuthPasskeyUser,
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

        db.execute(
            delete(
                DashboardAuthRateLimitEvent
            )
        )


def _login(
    client: TestClient,
    *,
    username: str = "rootadmin",
    password: str = (
        "rootadmin-test-password"
    ),
) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "username":
                username,
            "password":
                password,
        },
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
        == "authenticated"
    )

    return str(
        body[
            "access_token"
        ]
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


def test_ip_policy_get_uses_observed_peer_and_requires_bearer() -> None:
    init_db()

    _clear_user_state(
        "rootadmin"
    )

    try:
        with TestClient(
            app,
            client=(
                "198.51.100.42",
                50000,
            ),
        ) as client:
            token = _login(
                client
            )

            unauthenticated = client.get(
                "/api/auth/ip-restrictions"
            )

            assert (
                unauthenticated.status_code
                == 401
            )

            basic = client.get(
                "/api/auth/ip-restrictions",
                headers=_basic(),
            )

            assert (
                basic.status_code
                == 400
            )

            response = client.get(
                "/api/auth/ip-restrictions",
                headers={
                    **_bearer(
                        token
                    ),
                    "X-Forwarded-For":
                        "203.0.113.250",
                    "X-Real-IP":
                        "203.0.113.251",
                    "Forwarded":
                        "for=203.0.113.252",
                },
            )

            assert (
                response.status_code
                == 200
            )

            body = response.json()

            assert (
                body[
                    "observed_client_ip"
                ]
                == "198.51.100.42"
            )

            assert (
                body[
                    "observed_client_network"
                ]
                == "198.51.100.42/32"
            )

            assert (
                body[
                    "observed_client_ip"
                ]
                not in {
                    "203.0.113.250",
                    "203.0.113.251",
                    "203.0.113.252",
                }
            )

            assert (
                body[
                    "policy"
                ][
                    "username"
                ]
                == "rootadmin"
            )

            assert (
                body[
                    "policy"
                ][
                    "enabled"
                ]
                is False
            )

            assert (
                body[
                    "policy"
                ][
                    "allowlist"
                ]
                == []
            )

            assert (
                body[
                    "global_enforcement_enabled"
                ]
                is False
            )

            assert (
                body[
                    "enforcement_active"
                ]
                is False
            )

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
            )

    finally:
        _clear_user_state(
            "rootadmin"
        )


def test_user_can_stage_disabled_canonical_allowlist_and_audit() -> None:
    init_db()

    _clear_user_state(
        "rootadmin"
    )

    try:
        with TestClient(
            app,
            client=(
                "198.51.100.42",
                50000,
            ),
        ) as client:
            token = _login(
                client
            )

            response = client.put(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
                json={
                    "enabled":
                        False,
                    "allowlist": [
                        {
                            "network":
                                "192.0.2.77/24",
                            "label":
                                " Office ",
                        },
                        {
                            "network":
                                "2001:db8::1",
                            "label":
                                "IPv6",
                        },
                    ],
                    "current_password":
                        (
                            "rootadmin-"
                            "test-password"
                        ),
                    "reason":
                        "Stage trusted networks",
                },
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
                == "updated"
            )

            assert (
                body[
                    "changed"
                ]
                is True
            )

            assert (
                body[
                    "created"
                ]
                is True
            )

            assert (
                body[
                    "policy"
                ][
                    "enabled"
                ]
                is False
            )

            assert {
                (
                    item[
                        "network"
                    ],
                    item[
                        "label"
                    ],
                )
                for item
                in body[
                    "policy"
                ][
                    "allowlist"
                ]
            } == {
                (
                    "192.0.2.0/24",
                    "Office",
                ),
                (
                    "2001:db8::1/128",
                    "IPv6",
                ),
            }

            assert (
                body[
                    "global_enforcement_enabled"
                ]
                is False
            )

            assert (
                body[
                    "enforcement_active"
                ]
                is False
            )

            event = body[
                "event"
            ]

            assert (
                event[
                    "action"
                ]
                == (
                    "ip_restriction_"
                    "policy_updated"
                )
            )

            assert (
                event[
                    "actor_username"
                ]
                == "rootadmin"
            )

            assert (
                event[
                    "target_username"
                ]
                == "rootadmin"
            )

            metadata = event[
                "metadata"
            ]

            assert (
                metadata[
                    "source"
                ]
                == (
                    "security_"
                    "ip_restrictions"
                )
            )

            assert (
                metadata[
                    "observed_client_ip"
                ]
                == "198.51.100.42"
            )

            assert (
                metadata[
                    "old_enabled"
                ]
                is False
            )

            assert (
                metadata[
                    "new_enabled"
                ]
                is False
            )

            assert (
                body[
                    "gate_write_performed"
                ]
                is False
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
                        == (
                            "ip_restriction_"
                            "policy_updated"
                        ),
                    )
                )
            )

            assert len(
                events
            ) == 1

            persisted = json.loads(
                events[
                    0
                ].metadata_json
            )

            assert (
                persisted[
                    "source"
                ]
                == (
                    "security_"
                    "ip_restrictions"
                )
            )

    finally:
        _clear_user_state(
            "rootadmin"
        )


def test_enabling_requires_current_observed_ip_but_does_not_enforce() -> None:
    init_db()

    _clear_user_state(
        "rootadmin"
    )

    try:
        with TestClient(
            app,
            client=(
                "198.51.100.42",
                50000,
            ),
        ) as client:
            token = _login(
                client
            )

            denied = client.put(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
                json={
                    "enabled":
                        True,
                    "allowlist": [
                        {
                            "network":
                                "203.0.113.0/24",
                            "label":
                                "Wrong network",
                        },
                    ],
                    "current_password":
                        (
                            "rootadmin-"
                            "test-password"
                        ),
                },
            )

            assert (
                denied.status_code
                == 400
            )

            assert (
                "Current observed client IP"
                in denied.json()[
                    "detail"
                ]
            )

            staged = client.get(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
            ).json()

            assert (
                staged[
                    "policy"
                ][
                    "enabled"
                ]
                is False
            )

            assert (
                staged[
                    "policy"
                ][
                    "allowlist"
                ]
                == []
            )

            enabled = client.put(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
                json={
                    "enabled":
                        True,
                    "allowlist": [
                        {
                            "network":
                                "198.51.100.42",
                            "label":
                                "Current connection",
                        },
                        {
                            "network":
                                "203.0.113.0/24",
                            "label":
                                "Future network",
                        },
                    ],
                    "current_password":
                        (
                            "rootadmin-"
                            "test-password"
                        ),
                    "reason":
                        "Prepare future enforcement",
                },
            )

            assert (
                enabled.status_code
                == 200
            )

            body = enabled.json()

            assert (
                body[
                    "policy"
                ][
                    "enabled"
                ]
                is True
            )

            assert (
                body[
                    "global_enforcement_enabled"
                ]
                is False
            )

            assert (
                body[
                    "enforcement_active"
                ]
                is False
            )

            assert (
                "198.51.100.42/32"
                in {
                    item[
                        "network"
                    ]
                    for item
                    in body[
                        "policy"
                    ][
                        "allowlist"
                    ]
                }
            )

        # The same Bearer token intentionally remains valid
        # from a client outside the staged allowlist because
        # A7C490B1 has no enforcement integration.
        with TestClient(
            app,
            client=(
                "203.0.113.77",
                50000,
            ),
        ) as other_client:
            me = other_client.get(
                "/api/auth/me",
                headers=_bearer(
                    token
                ),
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
        _clear_user_state(
            "rootadmin"
        )


def test_wrong_password_and_duplicate_networks_do_not_mutate_policy() -> None:
    init_db()

    _clear_user_state(
        "rootadmin"
    )

    try:
        with TestClient(
            app,
            client=(
                "198.51.100.42",
                50000,
            ),
        ) as client:
            token = _login(
                client
            )

            wrong_password = client.put(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
                json={
                    "enabled":
                        False,
                    "allowlist": [
                        {
                            "network":
                                "192.0.2.10",
                        },
                    ],
                    "current_password":
                        "wrong-password",
                },
            )

            assert (
                wrong_password.status_code
                == 403
            )

            duplicate = client.put(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
                json={
                    "enabled":
                        False,
                    "allowlist": [
                        {
                            "network":
                                "192.0.2.77/24",
                        },
                        {
                            "network":
                                "192.0.2.0/24",
                        },
                    ],
                    "current_password":
                        (
                            "rootadmin-"
                            "test-password"
                        ),
                },
            )

            assert (
                duplicate.status_code
                == 400
            )

            assert (
                "Duplicate IP network"
                in duplicate.json()[
                    "detail"
                ]
            )

            current = client.get(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    token
                ),
            ).json()

            assert (
                current[
                    "policy"
                ][
                    "enabled"
                ]
                is False
            )

            assert (
                current[
                    "policy"
                ][
                    "allowlist"
                ]
                == []
            )

        with session_scope() as db:
            assert (
                db.get(
                    DashboardAuthIpPolicy,
                    "rootadmin",
                )
                is None
            )

    finally:
        _clear_user_state(
            "rootadmin"
        )


def test_ip_policy_is_scoped_to_authenticated_dashboard_user() -> None:
    init_db()

    for username in (
        "rootadmin",
        "zolnode",
    ):
        _clear_user_state(
            username
        )

    try:
        with TestClient(
            app,
            client=(
                "198.51.100.42",
                50000,
            ),
        ) as client:
            root_token = _login(
                client
            )

            configured = client.put(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    root_token
                ),
                json={
                    "enabled":
                        False,
                    "allowlist": [
                        {
                            "network":
                                "192.0.2.10",
                            "label":
                                "Root only",
                        },
                    ],
                    "current_password":
                        (
                            "rootadmin-"
                            "test-password"
                        ),
                },
            )

            assert (
                configured.status_code
                == 200
            )

            zolnode_token = _login(
                client,
                username="zolnode",
                password=(
                    "zolnode-test-password"
                ),
            )

            zolnode = client.get(
                "/api/auth/ip-restrictions",
                headers=_bearer(
                    zolnode_token
                ),
            )

            assert (
                zolnode.status_code
                == 200
            )

            policy = zolnode.json()[
                "policy"
            ]

            assert (
                policy[
                    "username"
                ]
                == "zolnode"
            )

            assert (
                policy[
                    "enabled"
                ]
                is False
            )

            assert (
                policy[
                    "allowlist"
                ]
                == []
            )

    finally:
        for username in (
            "rootadmin",
            "zolnode",
        ):
            _clear_user_state(
                username
            )
