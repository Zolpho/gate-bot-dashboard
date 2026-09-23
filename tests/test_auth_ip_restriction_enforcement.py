from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import (
    delete,
    select,
)

import app.auth_ip_restrictions as ip_service
from app.auth_ip_restrictions import (
    AuthIpRestrictionError,
    evaluate_ip_restriction_access,
)
from app.db import (
    init_db,
    session_scope,
)
from app.models import (
    DashboardAuthEvent,
    DashboardAuthIpAllowlistEntry,
    DashboardAuthIpPolicy,
)


def _clear(
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

        db.execute(
            delete(
                DashboardAuthEvent
            ).where(
                DashboardAuthEvent
                .target_username
                == username
            )
        )


def _seed(
    username: str,
    *,
    enabled: bool,
    networks: tuple[
        str,
        ...,
    ] = (),
) -> None:
    reference = datetime(
        2026,
        9,
        23,
        10,
        0,
        tzinfo=UTC,
    )

    with session_scope() as db:
        db.add(
            DashboardAuthIpPolicy(
                username=username,
                enabled=enabled,
                updated_by="test",
                created_at=reference,
                updated_at=reference,
            )
        )

        db.flush()

        for index, network in enumerate(
            networks,
            start=1,
        ):
            db.add(
                DashboardAuthIpAllowlistEntry(
                    username=username,
                    network=network,
                    label=f"Network {index}",
                    created_at=reference,
                )
            )


def test_global_off_short_circuits_without_policy_read(
    monkeypatch,
) -> None:
    def fail_policy_read(
        *,
        username: str,
    ):
        raise AssertionError(
            "policy must not be read "
            "while global arm is off"
        )

    monkeypatch.setattr(
        ip_service,
        "get_ip_restriction_policy",
        fail_policy_read,
    )

    decision = (
        evaluate_ip_restriction_access(
            username="zolnode",
            client_ip="198.51.100.44",
            global_enforcement_enabled=False,
        )
    )

    assert decision == {
        "allowed":
            True,
        "enforcement_active":
            False,
        "reason":
            "global_disabled",
        "policy_checked":
            False,
        "policy_enabled":
            None,
        "client_ip":
            None,
    }


def test_global_on_missing_policy_allows() -> None:
    init_db()

    username = (
        "a7c490d1-missing"
    )

    _clear(
        username
    )

    try:
        decision = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip=None,
                global_enforcement_enabled=True,
            )
        )

        assert decision == {
            "allowed":
                True,
            "enforcement_active":
                False,
            "reason":
                "policy_disabled",
            "policy_checked":
                True,
            "policy_enabled":
                False,
            "client_ip":
                None,
        }

    finally:
        _clear(
            username
        )


def test_disabled_policy_allows_without_validating_stored_networks() -> None:
    init_db()

    username = (
        "a7c490d1-disabled"
    )

    _clear(
        username
    )

    try:
        _seed(
            username,
            enabled=False,
            networks=(
                "not-a-network",
            ),
        )

        decision = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip=None,
                global_enforcement_enabled=True,
            )
        )

        assert (
            decision[
                "allowed"
            ]
            is True
        )

        assert (
            decision[
                "enforcement_active"
            ]
            is False
        )

        assert (
            decision[
                "reason"
            ]
            == "policy_disabled"
        )

    finally:
        _clear(
            username
        )


@pytest.mark.parametrize(
    (
        "client_ip",
        "expected_allowed",
        "expected_reason",
    ),
    (
        (
            "192.0.2.10",
            True,
            "allowlist_match",
        ),
        (
            "192.0.2.250",
            True,
            "allowlist_match",
        ),
        (
            "198.51.100.10",
            False,
            "allowlist_miss",
        ),
    ),
)
def test_enabled_ipv4_policy_matches_and_denies(
    client_ip: str,
    expected_allowed: bool,
    expected_reason: str,
) -> None:
    init_db()

    username = (
        "a7c490d1-ipv4"
    )

    _clear(
        username
    )

    try:
        _seed(
            username,
            enabled=True,
            networks=(
                "192.0.2.0/24",
            ),
        )

        decision = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip=client_ip,
                global_enforcement_enabled=True,
            )
        )

        assert (
            decision[
                "allowed"
            ]
            is expected_allowed
        )

        assert (
            decision[
                "enforcement_active"
            ]
            is True
        )

        assert (
            decision[
                "reason"
            ]
            == expected_reason
        )

        assert (
            decision[
                "policy_enabled"
            ]
            is True
        )

        assert (
            decision[
                "client_ip"
            ]
            == client_ip
        )

    finally:
        _clear(
            username
        )


def test_enabled_ipv6_policy_uses_canonical_client_identity() -> None:
    init_db()

    username = (
        "a7c490d1-ipv6"
    )

    _clear(
        username
    )

    try:
        _seed(
            username,
            enabled=True,
            networks=(
                "2001:db8:100::/48",
            ),
        )

        decision = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip=(
                    "2001:0db8:0100::0042"
                ),
                global_enforcement_enabled=True,
            )
        )

        assert (
            decision[
                "allowed"
            ]
            is True
        )

        assert (
            decision[
                "reason"
            ]
            == "allowlist_match"
        )

        assert (
            decision[
                "client_ip"
            ]
            == "2001:db8:100::42"
        )

    finally:
        _clear(
            username
        )


@pytest.mark.parametrize(
    (
        "client_ip",
        "expected_reason",
    ),
    (
        (
            None,
            "client_ip_unavailable",
        ),
        (
            "",
            "client_ip_unavailable",
        ),
        (
            "not-an-ip",
            "client_ip_invalid",
        ),
        (
            "fe80::1%eth0",
            "client_ip_invalid",
        ),
    ),
)
def test_active_policy_fails_closed_without_valid_client_ip(
    client_ip: str | None,
    expected_reason: str,
) -> None:
    init_db()

    username = (
        "a7c490d1-client"
    )

    _clear(
        username
    )

    try:
        _seed(
            username,
            enabled=True,
            networks=(
                "192.0.2.1/32",
            ),
        )

        decision = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip=client_ip,
                global_enforcement_enabled=True,
            )
        )

        assert (
            decision[
                "allowed"
            ]
            is False
        )

        assert (
            decision[
                "enforcement_active"
            ]
            is True
        )

        assert (
            decision[
                "reason"
            ]
            == expected_reason
        )

    finally:
        _clear(
            username
        )


def test_enabled_empty_allowlist_fails_closed() -> None:
    init_db()

    username = (
        "a7c490d1-empty"
    )

    _clear(
        username
    )

    try:
        _seed(
            username,
            enabled=True,
        )

        decision = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip="192.0.2.1",
                global_enforcement_enabled=True,
            )
        )

        assert decision[
            "allowed"
        ] is False

        assert (
            decision[
                "reason"
            ]
            == "empty_allowlist"
        )

        assert (
            decision[
                "enforcement_active"
            ]
            is True
        )

    finally:
        _clear(
            username
        )


def test_enabled_malformed_allowlist_fails_closed() -> None:
    init_db()

    username = (
        "a7c490d1-corrupt"
    )

    _clear(
        username
    )

    try:
        _seed(
            username,
            enabled=True,
            networks=(
                "definitely-not-a-network",
            ),
        )

        decision = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip="192.0.2.1",
                global_enforcement_enabled=True,
            )
        )

        assert decision[
            "allowed"
        ] is False

        assert (
            decision[
                "reason"
            ]
            == "policy_invalid"
        )

        assert (
            decision[
                "client_ip"
            ]
            == "192.0.2.1"
        )

    finally:
        _clear(
            username
        )


def test_decision_primitive_is_read_only() -> None:
    init_db()

    username = (
        "a7c490d1-readonly"
    )

    _clear(
        username
    )

    try:
        _seed(
            username,
            enabled=True,
            networks=(
                "192.0.2.1/32",
            ),
        )

        with session_scope() as db:
            before_policy = db.get(
                DashboardAuthIpPolicy,
                username,
            )

            assert (
                before_policy
                is not None
            )

            before_updated_at = (
                before_policy.updated_at
            )

            before_entries = [
                (
                    row.id,
                    row.network,
                    row.label,
                    row.created_at,
                )
                for row
                in db.scalars(
                    select(
                        DashboardAuthIpAllowlistEntry
                    )
                    .where(
                        DashboardAuthIpAllowlistEntry
                        .username
                        == username
                    )
                    .order_by(
                        DashboardAuthIpAllowlistEntry
                        .id
                    )
                )
            ]

            before_events = list(
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

        allowed = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip="192.0.2.1",
                global_enforcement_enabled=True,
            )
        )

        denied = (
            evaluate_ip_restriction_access(
                username=username,
                client_ip="198.51.100.1",
                global_enforcement_enabled=True,
            )
        )

        assert allowed[
            "allowed"
        ] is True

        assert denied[
            "allowed"
        ] is False

        with session_scope() as db:
            after_policy = db.get(
                DashboardAuthIpPolicy,
                username,
            )

            assert (
                after_policy
                is not None
            )

            assert (
                after_policy.updated_at
                == before_updated_at
            )

            after_entries = [
                (
                    row.id,
                    row.network,
                    row.label,
                    row.created_at,
                )
                for row
                in db.scalars(
                    select(
                        DashboardAuthIpAllowlistEntry
                    )
                    .where(
                        DashboardAuthIpAllowlistEntry
                        .username
                        == username
                    )
                    .order_by(
                        DashboardAuthIpAllowlistEntry
                        .id
                    )
                )
            ]

            after_events = list(
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

        assert (
            after_entries
            == before_entries
        )

        assert (
            after_events
            == before_events
        )

    finally:
        _clear(
            username
        )


def test_global_enforcement_value_must_be_boolean() -> None:
    with pytest.raises(
        AuthIpRestrictionError
    ):
        evaluate_ip_restriction_access(
            username="zolnode",
            client_ip="192.0.2.1",
            global_enforcement_enabled=1,  # type: ignore[arg-type]
        )
