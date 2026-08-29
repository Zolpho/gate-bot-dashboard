from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from sqlalchemy import create_engine, inspect

from app.db import init_db
from app.migrations import migrate_database
from app.treasury_withdrawal_recipients import (
    TreasuryWithdrawalRecipientError,
    archive_recipient,
    create_recipient,
    get_recipient,
    list_recipient_events,
    list_recipients,
    rename_recipient,
    restore_recipient,
)



@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_recipient_test_database():
    # Focused execution of this module does not start
    # FastAPI's lifespan. Initialize the configured
    # pytest /tmp database explicitly.
    init_db()


def _owner(
    prefix: str = "recipient_test",
) -> str:
    return (
        prefix
        + "_"
        + uuid4().hex[:12]
    )


def _evm_address() -> str:
    return (
        "0x"
        + uuid4().hex
        + uuid4().hex[:8]
    )


def test_recipient_tables_migrate_on_existing_sqlite(
    tmp_path,
) -> None:
    path = (
        tmp_path
        / "recipient-migration.db"
    )

    engine = create_engine(
        f"sqlite:///{path}"
    )

    migrate_database(engine)

    inspector = inspect(engine)

    tables = set(
        inspector.get_table_names()
    )

    assert (
        "treasury_withdrawal_recipients"
        in tables
    )

    assert (
        "treasury_withdrawal_recipient_events"
        in tables
    )

    columns = {
        item["name"]
        for item
        in inspector.get_columns(
            "treasury_withdrawal_recipients"
        )
    }

    assert "address" in columns
    assert "label" in columns
    assert "status" in columns

    # Recipient is deliberately generic.
    assert "currency" not in columns
    assert "chain" not in columns
    assert "memo" not in columns

    engine.dispose()


def test_create_recipient_is_generic_and_audited():
    owner = _owner()

    created = create_recipient(
        owner_account_id=owner,
        address=_evm_address(),
        label="My Ledger",
        username="tester",
    )

    assert created["created"] is True

    item = created["item"]

    assert (
        item["owner_account_id"]
        == owner
    )

    assert item["label"] == "My Ledger"
    assert item["status"] == "active"

    assert "currency" not in item
    assert "chain" not in item
    assert "memo" not in item

    fetched = get_recipient(
        item["recipient_id"]
    )

    assert fetched == item

    assert item["created_at"].endswith(
        "+00:00"
    )
    assert item["updated_at"].endswith(
        "+00:00"
    )

    events = list_recipient_events(
        item["recipient_id"]
    )

    assert [
        event["action"]
        for event in events
    ] == [
        "created",
    ]

    assert events[0]["created_at"].endswith(
        "+00:00"
    )


def test_evm_recipient_identity_is_case_insensitive():
    owner = _owner()

    address = _evm_address()

    first = create_recipient(
        owner_account_id=owner,
        address=address,
        label="Primary",
        username="tester",
    )

    second = create_recipient(
        owner_account_id=owner,
        address=address.upper(),
        label="Duplicate",
        username="tester",
    )

    assert first["created"] is True
    assert second["created"] is False

    assert (
        second["item"]["recipient_id"]
        == first["item"]["recipient_id"]
    )

    # Duplicate creation never silently mutates metadata.
    assert (
        second["item"]["label"]
        == "Primary"
    )


def test_same_address_can_belong_to_different_owners():
    address = _evm_address()

    first = create_recipient(
        owner_account_id=_owner(
            "recipient_a"
        ),
        address=address,
        label="Owner A",
        username="tester",
    )

    second = create_recipient(
        owner_account_id=_owner(
            "recipient_b"
        ),
        address=address,
        label="Owner B",
        username="tester",
    )

    assert first["created"] is True
    assert second["created"] is True

    assert (
        first["item"]["recipient_id"]
        != second["item"]["recipient_id"]
    )


def test_recipient_label_can_change_without_changing_identity():
    owner = _owner()

    created = create_recipient(
        owner_account_id=owner,
        address=_evm_address(),
        label="Old description",
        username="tester",
    )

    recipient_id = (
        created["item"]["recipient_id"]
    )

    address = created["item"]["address"]

    renamed = rename_recipient(
        recipient_id=recipient_id,
        label="My cold wallet",
        username="tester",
    )

    assert renamed["changed"] is True
    assert (
        renamed["item"]["recipient_id"]
        == recipient_id
    )
    assert (
        renamed["item"]["address"]
        == address
    )
    assert (
        renamed["item"]["label"]
        == "My cold wallet"
    )

    events = list_recipient_events(
        recipient_id
    )

    assert [
        event["action"]
        for event in events
    ] == [
        "created",
        "renamed",
    ]

    assert (
        events[-1]["metadata"]["old_label"]
        == "Old description"
    )

    assert (
        events[-1]["metadata"]["new_label"]
        == "My cold wallet"
    )


def test_archive_hides_recipient_from_active_list_and_restore_returns_it():
    owner = _owner()

    created = create_recipient(
        owner_account_id=owner,
        address=_evm_address(),
        label="Temporary wallet",
        username="tester",
    )

    recipient_id = (
        created["item"]["recipient_id"]
    )

    archived = archive_recipient(
        recipient_id=recipient_id,
        username="tester",
    )

    assert archived["changed"] is True
    assert (
        archived["item"]["status"]
        == "archived"
    )

    active_ids = {
        item["recipient_id"]
        for item in list_recipients(
            owner_account_ids={owner},
            status="active",
        )
    }

    archived_ids = {
        item["recipient_id"]
        for item in list_recipients(
            owner_account_ids={owner},
            status="archived",
        )
    }

    assert recipient_id not in active_ids
    assert recipient_id in archived_ids

    restored = restore_recipient(
        recipient_id=recipient_id,
        username="tester",
    )

    assert restored["changed"] is True
    assert (
        restored["item"]["status"]
        == "active"
    )

    active_ids = {
        item["recipient_id"]
        for item in list_recipients(
            owner_account_ids={owner},
            status="active",
        )
    }

    assert recipient_id in active_ids

    events = list_recipient_events(
        recipient_id
    )

    assert [
        event["action"]
        for event in events
    ] == [
        "created",
        "archived",
        "restored",
    ]


def test_readding_archived_address_does_not_silently_restore_it():
    owner = _owner()

    address = _evm_address()

    created = create_recipient(
        owner_account_id=owner,
        address=address,
        label="Archived wallet",
        username="tester",
    )

    recipient_id = (
        created["item"]["recipient_id"]
    )

    archive_recipient(
        recipient_id=recipient_id,
        username="tester",
    )

    repeated = create_recipient(
        owner_account_id=owner,
        address=address,
        label="Try to recreate",
        username="tester",
    )

    assert repeated["created"] is False
    assert (
        repeated["item"]["recipient_id"]
        == recipient_id
    )
    assert (
        repeated["item"]["status"]
        == "archived"
    )

    events = list_recipient_events(
        recipient_id
    )

    assert [
        event["action"]
        for event in events
    ] == [
        "created",
        "archived",
    ]


def test_recipient_address_validation_fails_closed():
    with pytest.raises(
        TreasuryWithdrawalRecipientError,
        match="cannot contain whitespace",
    ):
        create_recipient(
            owner_account_id=_owner(),
            address="bad address",
            label="Unsafe",
            username="tester",
        )

    with pytest.raises(
        TreasuryWithdrawalRecipientError,
        match="address is required",
    ):
        create_recipient(
            owner_account_id=_owner(),
            address="",
            label="Missing",
            username="tester",
        )


def test_recipient_service_has_no_hard_delete_surface():
    source = Path(
        "app/treasury_withdrawal_recipients.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "def delete_recipient" not in source
    assert "def remove_recipient" not in source
    assert "delete(" not in source

    assert "def archive_recipient" in source
    assert "def restore_recipient" in source
