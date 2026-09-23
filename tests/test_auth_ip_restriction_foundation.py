from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import (
    create_engine,
    delete,
    inspect,
)

from app.auth_ip_restrictions import (
    AuthIpRestrictionError,
    client_ip_matches_allowlist,
    get_ip_restriction_policy,
    normalize_ip_allowlist,
    normalize_ip_network,
)
from app.config import Settings
from app.db import (
    Base,
    init_db,
    session_scope,
)
from app.migrations import (
    migrate_database,
)
from app.models import (
    DashboardAuthIpAllowlistEntry,
    DashboardAuthIpPolicy,
)


def _clear_policy(
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


def test_ip_restriction_global_enforcement_defaults_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "DASHBOARD_IP_RESTRICTIONS_ENFORCEMENT_ENABLED",
        raising=False,
    )

    settings = Settings(
        _env_file=None,
    )

    assert (
        settings
        .dashboard_ip_restrictions_enforcement_enabled
        is False
    )

    explicitly_enabled = Settings(
        dashboard_ip_restrictions_enforcement_enabled=True,
    )

    assert (
        explicitly_enabled
        .dashboard_ip_restrictions_enforcement_enabled
        is True
    )


def test_ip_restriction_tables_have_expected_schema(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ip-foundation.db'}"
    )

    Base.metadata.create_all(
        engine
    )

    inspector = inspect(
        engine
    )

    tables = set(
        inspector.get_table_names()
    )

    assert (
        "dashboard_auth_ip_policies"
        in tables
    )

    assert (
        "dashboard_auth_ip_allowlist_entries"
        in tables
    )

    policy_columns = {
        column["name"]
        for column
        in inspector.get_columns(
            "dashboard_auth_ip_policies"
        )
    }

    entry_columns = {
        column["name"]
        for column
        in inspector.get_columns(
            "dashboard_auth_ip_allowlist_entries"
        )
    }

    assert policy_columns == {
        "username",
        "enabled",
        "updated_by",
        "created_at",
        "updated_at",
    }

    assert entry_columns == {
        "id",
        "username",
        "network",
        "label",
        "created_at",
    }

    uniques = {
        tuple(
            item[
                "column_names"
            ]
        )
        for item
        in inspector.get_unique_constraints(
            "dashboard_auth_ip_allowlist_entries"
        )
    }

    assert (
        "username",
        "network",
    ) in uniques


def test_ip_restriction_migration_is_idempotent_and_has_no_backfill(
    tmp_path,
) -> None:
    path = (
        tmp_path
        / "ip-migration.db"
    )

    engine = create_engine(
        f"sqlite:///{path}"
    )

    migrate_database(
        engine
    )

    migrate_database(
        engine
    )

    Base.metadata.create_all(
        engine
    )

    inspector = inspect(
        engine
    )

    assert (
        "dashboard_auth_ip_policies"
        in inspector.get_table_names()
    )

    assert (
        "dashboard_auth_ip_allowlist_entries"
        in inspector.get_table_names()
    )

    with engine.connect() as connection:
        policy_count = int(
            connection.exec_driver_sql(
                """
                SELECT COUNT(*)
                FROM dashboard_auth_ip_policies
                """
            ).scalar_one()
        )

        entry_count = int(
            connection.exec_driver_sql(
                """
                SELECT COUNT(*)
                FROM dashboard_auth_ip_allowlist_entries
                """
            ).scalar_one()
        )

    assert policy_count == 0
    assert entry_count == 0


@pytest.mark.parametrize(
    (
        "value",
        "expected",
    ),
    (
        (
            "192.0.2.10",
            "192.0.2.10/32",
        ),
        (
            " 192.0.2.77/24 ",
            "192.0.2.0/24",
        ),
        (
            "2001:db8::1",
            "2001:db8::1/128",
        ),
        (
            "2001:db8::abcd/64",
            "2001:db8::/64",
        ),
    ),
)
def test_ip_network_normalization(
    value: str,
    expected: str,
) -> None:
    assert (
        normalize_ip_network(
            value
        )
        == expected
    )


@pytest.mark.parametrize(
    "value",
    (
        "",
        "not-an-ip",
        "192.0.2.999",
        "fe80::1%eth0",
    ),
)
def test_invalid_ip_networks_are_rejected(
    value: str,
) -> None:
    with pytest.raises(
        AuthIpRestrictionError
    ):
        normalize_ip_network(
            value
        )


def test_allowlist_normalization_is_canonical_deduplicated_and_stable() -> None:
    assert (
        normalize_ip_allowlist(
            (
                "2001:db8::1",
                "192.0.2.8",
                "192.0.2.8/32",
                "192.0.2.77/24",
            )
        )
        == [
            "192.0.2.0/24",
            "192.0.2.8/32",
            "2001:db8::1/128",
        ]
    )


def test_client_ip_matcher_supports_ipv4_and_ipv6() -> None:
    allowlist = (
        "192.0.2.0/24",
        "2001:db8:100::/48",
    )

    assert client_ip_matches_allowlist(
        "192.0.2.41",
        allowlist,
    )

    assert not client_ip_matches_allowlist(
        "198.51.100.41",
        allowlist,
    )

    assert client_ip_matches_allowlist(
        "2001:db8:100::42",
        allowlist,
    )

    assert not client_ip_matches_allowlist(
        "2001:db8:200::42",
        allowlist,
    )


def test_missing_policy_is_disabled_without_creating_a_row() -> None:
    init_db()

    username = (
        "a7c490-missing-policy-user"
    )

    _clear_policy(
        username
    )

    try:
        snapshot = (
            get_ip_restriction_policy(
                username=username,
            )
        )

        assert snapshot == {
            "username":
                username,
            "enabled":
                False,
            "updated_by":
                "",
            "created_at":
                None,
            "updated_at":
                None,
            "allowlist":
                [],
        }

        with session_scope() as db:
            assert (
                db.get(
                    DashboardAuthIpPolicy,
                    username,
                )
                is None
            )

    finally:
        _clear_policy(
            username
        )


def test_policy_snapshot_returns_durable_allowlist() -> None:
    init_db()

    username = (
        "a7c490-policy-user"
    )

    _clear_policy(
        username
    )

    try:
        with session_scope() as db:
            db.add(
                DashboardAuthIpPolicy(
                    username=username,
                    enabled=True,
                    updated_by=(
                        "rootadmin"
                    ),
                )
            )

        with session_scope() as db:
            db.add_all(
                (
                    DashboardAuthIpAllowlistEntry(
                        username=username,
                        network=(
                            "192.0.2.10/32"
                        ),
                        label="Office",
                    ),
                    DashboardAuthIpAllowlistEntry(
                        username=username,
                        network=(
                            "2001:db8::/64"
                        ),
                        label="IPv6",
                    ),
                )
            )

        snapshot = (
            get_ip_restriction_policy(
                username=username,
            )
        )

        assert (
            snapshot["enabled"]
            is True
        )

        assert (
            snapshot["updated_by"]
            == "rootadmin"
        )

        allowlist = snapshot[
            "allowlist"
        ]

        assert isinstance(
            allowlist,
            list,
        )

        assert {
            item["network"]
            for item in allowlist
        } == {
            "192.0.2.10/32",
            "2001:db8::/64",
        }

        assert {
            item["label"]
            for item in allowlist
        } == {
            "Office",
            "IPv6",
        }

    finally:
        _clear_policy(
            username
        )


def test_ip_enforcement_wiring_is_limited_to_auth_boundaries() -> None:
    import ast

    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    allowed_files = {
        "app/api/auth.py",
        "app/auth_ip_restrictions.py",
        "app/auth_login.py",
        "app/config.py",
        "app/migrations.py",
        "app/models.py",
        "app/security.py",
    }

    references_by_file: dict[
        str,
        set[str],
    ] = {}

    unexpected = []

    for candidate in sorted(
        (
            root
            / "app"
        ).rglob(
            "*.py"
        )
    ):
        relative = str(
            candidate.relative_to(
                root
            )
        )

        source = candidate.read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source
        )

        references: set[str] = set()

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.ImportFrom,
            ):
                module = str(
                    node.module
                    or ""
                )

                if module.endswith(
                    "auth_ip_restrictions"
                ):
                    references.add(
                        "auth_ip_restrictions import"
                    )

                for alias in node.names:
                    if (
                        alias.name
                        == (
                            "evaluate_"
                            "ip_restriction_access"
                        )
                    ):
                        references.add(
                            "decision primitive"
                        )

                    if (
                        alias.name
                        == "DashboardAuthIpPolicy"
                    ):
                        references.add(
                            "policy model"
                        )

            elif isinstance(
                node,
                ast.Import,
            ):
                for alias in node.names:
                    if alias.name.endswith(
                        "auth_ip_restrictions"
                    ):
                        references.add(
                            "auth_ip_restrictions import"
                        )

            elif isinstance(
                node,
                ast.Name,
            ):
                if (
                    node.id
                    == (
                        "evaluate_"
                        "ip_restriction_access"
                    )
                ):
                    references.add(
                        "decision primitive"
                    )

                if (
                    node.id
                    == "DashboardAuthIpPolicy"
                ):
                    references.add(
                        "policy model"
                    )

            elif isinstance(
                node,
                ast.Attribute,
            ):
                if (
                    node.attr
                    == (
                        "dashboard_ip_restrictions_"
                        "enforcement_enabled"
                    )
                ):
                    references.add(
                        "global enforcement arm"
                    )

        if references:
            references_by_file[
                relative
            ] = references

            if relative not in allowed_files:
                unexpected.append(
                    (
                        relative,
                        sorted(
                            references
                        ),
                    )
                )

    assert unexpected == []

    assert (
        "decision primitive"
        in references_by_file[
            "app/auth_login.py"
        ]
    )

    assert (
        "decision primitive"
        in references_by_file[
            "app/security.py"
        ]
    )

    # Enforcement remains entirely within authentication/security
    # boundaries. No treasury/trading/bot-control module may acquire
    # direct policy or decision dependencies.
    for relative in references_by_file:
        assert not relative.startswith(
            (
                "app/api/treasury",
                "app/api/trading",
                "app/bot_control",
                "app/treasury",
                "app/trading",
            )
        )
