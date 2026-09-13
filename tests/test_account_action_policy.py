from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select

from app.account_action_policy import (
    AccountActionPolicyError,
    account_action_allowed,
    get_account_action_policy,
    list_account_action_policy_events,
    update_account_action_policy,
)
from app.db import init_db, session_scope
from app.migrations import migrate_database
from app.models import (
    AccountActionPolicy,
    AccountActionPolicyEvent,
    GateAccount,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_policy_test_database() -> None:
    # Match normal application startup for the shared
    # temporary test database configured by conftest.py.
    init_db()


def _new_account_id(prefix: str) -> str:
    return (
        prefix
        + "-"
        + uuid4().hex[:12]
    )


def _create_runtime_account(
    account_id: str,
) -> None:
    with session_scope() as db:
        db.add(
            GateAccount(
                id=account_id,
                name=account_id,
                account_type="subaccount",
                enabled=True,
                configured=True,
            )
        )


def test_missing_policy_fails_closed() -> None:
    account_id = _new_account_id(
        "policy-missing"
    )

    _create_runtime_account(
        account_id
    )

    policy = get_account_action_policy(
        account_id
    )

    assert policy == {
        "account_id": account_id,
        "exists": False,
        "transfers_enabled": False,
        "withdrawals_enabled": False,
        "trading_enabled": False,
        "updated_by": None,
        "created_at": None,
        "updated_at": None,
    }

    assert (
        account_action_allowed(
            account_id,
            "transfers",
        )
        is False
    )

    assert (
        account_action_allowed(
            account_id,
            "withdrawals",
        )
        is False
    )

    assert (
        account_action_allowed(
            account_id,
            "trading",
        )
        is False
    )


def test_policy_update_is_audited() -> None:
    account_id = _new_account_id(
        "policy-update"
    )

    _create_runtime_account(
        account_id
    )

    result = update_account_action_policy(
        account_id,
        username="rootadmin",
        transfers_enabled=True,
        withdrawals_enabled=False,
        trading_enabled=True,
        reason="Initial rootadmin policy",
        metadata={
            "source": "test",
        },
    )

    assert result["created"] is True
    assert result["changed"] is True

    policy = result["policy"]

    assert policy["exists"] is True
    assert (
        policy["transfers_enabled"]
        is True
    )
    assert (
        policy["withdrawals_enabled"]
        is False
    )
    assert (
        policy["trading_enabled"]
        is True
    )
    assert (
        policy["updated_by"]
        == "rootadmin"
    )

    assert {
        event["capability"]
        for event in result["events"]
    } == {
        "transfers",
        "withdrawals",
        "trading",
    }

    assert all(
        event["old_enabled"] is None
        for event in result["events"]
    )

    events = (
        list_account_action_policy_events(
            account_id
        )
    )

    assert len(events) == 3

    assert all(
        event["username"] == "rootadmin"
        for event in events
    )

    assert all(
        event["metadata"]
        == {
            "source": "test",
        }
        for event in events
    )

    assert (
        account_action_allowed(
            account_id,
            "transfers",
        )
        is True
    )

    assert (
        account_action_allowed(
            account_id,
            "withdrawals",
        )
        is False
    )

    assert (
        account_action_allowed(
            account_id,
            "trading",
        )
        is True
    )


def test_initial_explicit_false_is_audited() -> None:
    account_id = _new_account_id(
        "policy-initial-false"
    )

    _create_runtime_account(
        account_id
    )

    result = update_account_action_policy(
        account_id,
        username="rootadmin",
        withdrawals_enabled=False,
        reason="Explicit initial disable",
    )

    assert result["created"] is True
    assert result["changed"] is True
    assert len(result["events"]) == 1

    event = result["events"][0]

    assert event["capability"] == "withdrawals"
    assert event["old_enabled"] is None
    assert event["new_enabled"] is False
    assert event["username"] == "rootadmin"

    stored = get_account_action_policy(
        account_id
    )

    assert stored["exists"] is True
    assert (
        stored["withdrawals_enabled"]
        is False
    )


def test_policy_noop_does_not_append_event() -> None:
    account_id = _new_account_id(
        "policy-noop"
    )

    _create_runtime_account(
        account_id
    )

    first = update_account_action_policy(
        account_id,
        username="rootadmin",
        trading_enabled=True,
    )

    assert first["changed"] is True

    before = (
        list_account_action_policy_events(
            account_id
        )
    )

    second = update_account_action_policy(
        account_id,
        username="rootadmin",
        trading_enabled=True,
    )

    after = (
        list_account_action_policy_events(
            account_id
        )
    )

    assert second["created"] is False
    assert second["changed"] is False
    assert second["events"] == []
    assert len(after) == len(before)


def test_unknown_capability_is_rejected() -> None:
    account_id = _new_account_id(
        "policy-capability"
    )

    _create_runtime_account(
        account_id
    )

    with pytest.raises(
        AccountActionPolicyError
    ):
        account_action_allowed(
            account_id,
            "everything",
        )


def test_policy_migration_backfills_only_accounts_present_at_introduction(
    tmp_path,
) -> None:
    database_path = (
        tmp_path
        / "account-policy-migration.db"
    )

    engine = create_engine(
        f"sqlite:///{database_path}"
    )

    GateAccount.__table__.create(
        engine
    )

    existing_account = "existing-account"

    with engine.begin() as connection:
        connection.execute(
            GateAccount.__table__.insert().values(
                id=existing_account,
                name="Existing account",
                account_type="subaccount",
                enabled=True,
                configured=True,
            )
        )

    migrate_database(engine)
    migrate_database(engine)

    inspector = inspect(engine)

    assert (
        "account_action_policies"
        in inspector.get_table_names()
    )

    assert (
        "account_action_policy_events"
        in inspector.get_table_names()
    )

    with engine.begin() as connection:
        policy = connection.execute(
            select(
                AccountActionPolicy
            ).where(
                AccountActionPolicy.account_id
                == existing_account
            )
        ).mappings().one()

        assert (
            bool(
                policy[
                    "transfers_enabled"
                ]
            )
            is True
        )

        assert (
            bool(
                policy[
                    "withdrawals_enabled"
                ]
            )
            is True
        )

        assert (
            bool(
                policy[
                    "trading_enabled"
                ]
            )
            is True
        )

        events = connection.execute(
            select(
                AccountActionPolicyEvent
            ).where(
                AccountActionPolicyEvent
                .account_id
                == existing_account
            )
        ).mappings().all()

        assert len(events) == 3

        connection.execute(
            GateAccount.__table__.insert().values(
                id="new-after-policy",
                name="New after policy",
                account_type="subaccount",
                enabled=True,
                configured=True,
            )
        )

    migrate_database(engine)

    with engine.begin() as connection:
        new_policy = connection.execute(
            select(
                AccountActionPolicy
            ).where(
                AccountActionPolicy.account_id
                == "new-after-policy"
            )
        ).mappings().first()

        assert new_policy is None

        original_event_count = (
            connection.execute(
                select(
                    AccountActionPolicyEvent
                ).where(
                    AccountActionPolicyEvent
                    .account_id
                    == existing_account
                )
            )
            .mappings()
            .all()
        )

        assert len(
            original_event_count
        ) == 3

        assert (
            connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).all()
            == []
        )

    engine.dispose()

def test_policy_datetime_serializer_normalizes_naive_utc() -> None:
    from app.account_action_policy import _utc_iso

    naive = datetime(
        2026,
        9,
        13,
        19,
        30,
        1,
        484070,
    )

    assert (
        _utc_iso(naive)
        == "2026-09-13T19:30:01.484070+00:00"
    )


def test_policy_datetime_serializer_converts_aware_to_utc() -> None:
    from app.account_action_policy import _utc_iso

    aware = datetime.fromisoformat(
        "2026-09-13T21:30:01.484070+02:00"
    )

    assert (
        _utc_iso(aware)
        == "2026-09-13T19:30:01.484070+00:00"
    )


def test_policy_datetime_serializer_preserves_none() -> None:
    from app.account_action_policy import _utc_iso

    assert _utc_iso(None) is None
