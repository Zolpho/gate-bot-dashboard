from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.demo_wallet import DemoWalletStore
from app.demo_withdrawal import (
    DemoWithdrawalRegistryError,
    DemoWithdrawalStore,
)


def _store(
    tmp_path: Path,
) -> DemoWithdrawalStore:
    return DemoWithdrawalStore(
        tmp_path
        / "demo"
        / "demo.db"
    )


def _assets(
    wallet: DemoWalletStore,
    account_id: str,
) -> list[dict]:
    return (
        wallet.get_balance_state(
            account_id
        )["assets"]
    )


def test_withdrawal_seed_is_additive_and_does_not_change_wallet_balances(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    wallet = store.wallet_store

    wallet.ensure_seeded()

    before = {
        account_id:
            _assets(
                wallet,
                account_id,
            )
        for account_id
        in (
            "demo-wallet-1",
            "demo-wallet-2",
        )
    }

    assert store.ensure_seeded() is True

    after = {
        account_id:
            _assets(
                wallet,
                account_id,
            )
        for account_id
        in (
            "demo-wallet-1",
            "demo-wallet-2",
        )
    }

    assert before == after
    assert store.ensure_seeded() is False

    assert len(
        store.list_policies()
    ) == 5


def test_capabilities_are_synthetic_and_use_demo_wallet_networks(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    payload = store.capabilities(
        account_id="demo-wallet-1",
        currency="USDT",
    )

    assert payload["source"] == "demo"
    assert payload["simulation"] is True
    assert payload["gate_read_performed"] is False
    assert payload["gate_write_performed"] is False
    assert payload["withdrawals_enabled"] is False
    assert payload["demo_withdrawals_enabled"] is True

    assert payload["available"] == "12500"

    chains = {
        item["chain"]:
            item
        for item
        in payload["chains"]
    }

    assert set(chains) == {
        "ETH",
        "TRX",
    }

    assert (
        chains["ETH"]["fixed_fee"]
        == "1.04"
    )

    assert (
        chains["ETH"][
            "minimum_withdrawal"
        ]
        == "10"
    )


def test_seed_recipient_is_reusable_across_asset_network_routes(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    recipient = store.get_recipient(
        "demo-recipient-growth",
        owner_account_ids={
            "demo-wallet-1"
        },
    )

    destinations = (
        store.list_destinations(
            owner_account_ids={
                "demo-wallet-1"
            },
            status="approved",
        )
    )

    matching = [
        item
        for item
        in destinations
        if item["recipient_id"]
        == recipient["recipient_id"]
    ]

    assert {
        (
            item["currency"],
            item["chain"],
        )
        for item
        in matching
    } == {
        ("USDT", "ETH"),
        ("EQTY", "BASE"),
    }

    assert {
        item["address"]
        for item
        in matching
    } == {
        recipient["address"]
    }


def test_recipient_duplicate_identity_is_evm_case_insensitive(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    address = (
        "0xABCDEFabcdef"
        "ABCDEFabcdef"
        "ABCDEFabcdef"
        "ABCD"
    )

    assert len(address) == 42

    first = store.create_recipient(
        owner_account_id=(
            "demo-wallet-1"
        ),
        address=address,
        label="Case test",
    )

    second = store.create_recipient(
        owner_account_id=(
            "demo-wallet-1"
        ),
        address=address.lower(),
        label="Ignored duplicate label",
    )

    assert first["created"] is True
    assert second["created"] is False

    assert (
        first["item"]["recipient_id"]
        == second["item"]["recipient_id"]
    )


def test_recipient_address_is_immutable_while_metadata_is_audited(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    created = store.create_recipient(
        owner_account_id=(
            "demo-wallet-1"
        ),
        address="DEMO-ONLY-CUSTOM-ADDRESS",
        label="Original",
        occurred_at=(
            "2026-10-17T13:00:00+00:00"
        ),
    )

    recipient_id = (
        created["item"]["recipient_id"]
    )

    original_address = (
        created["item"]["address"]
    )

    renamed = store.rename_recipient(
        recipient_id=recipient_id,
        label="Renamed",
        occurred_at=(
            "2026-10-17T13:01:00+00:00"
        ),
    )

    archived = store.archive_recipient(
        recipient_id=recipient_id,
        reason="Demo archive",
        occurred_at=(
            "2026-10-17T13:02:00+00:00"
        ),
    )

    restored = store.restore_recipient(
        recipient_id=recipient_id,
        reason="Demo restore",
        occurred_at=(
            "2026-10-17T13:03:00+00:00"
        ),
    )

    assert renamed["item"]["label"] == "Renamed"
    assert archived["item"]["status"] == "archived"
    assert restored["item"]["status"] == "active"

    assert (
        restored["item"]["address"]
        == original_address
    )

    events = store.list_recipient_events(
        recipient_id
    )

    assert [
        event["action"]
        for event
        in events
    ] == [
        "created",
        "renamed",
        "archived",
        "restored",
    ]

    assert all(
        event["metadata"][
            "gate_write_performed"
        ]
        is False
        for event
        in events
    )


def test_archived_recipient_cannot_prepare_new_destination(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    created = store.create_recipient(
        owner_account_id=(
            "demo-wallet-1"
        ),
        address="DEMO-ONLY-ARCHIVED",
        label="Archived",
    )

    recipient_id = (
        created["item"]["recipient_id"]
    )

    store.archive_recipient(
        recipient_id=recipient_id,
    )

    with pytest.raises(
        DemoWithdrawalRegistryError,
        match="not active",
    ):
        store.create_destination_from_recipient(
            recipient_id=recipient_id,
            currency="BTC",
            chain="BTC",
        )


def test_new_demo_destination_is_auto_approved_and_idempotent(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    created = store.create_recipient(
        owner_account_id=(
            "demo-wallet-1"
        ),
        address="DEMO-ONLY-BTC-RECIPIENT",
        label="BTC demo",
    )

    recipient_id = (
        created["item"]["recipient_id"]
    )

    first = (
        store.create_destination_from_recipient(
            recipient_id=recipient_id,
            currency="BTC",
            chain="BTC",
        )
    )

    second = (
        store.create_destination_from_recipient(
            recipient_id=recipient_id,
            currency="BTC",
            chain="BTC",
        )
    )

    assert first["created"] is True
    assert first["auto_approved"] is True

    item = first["item"]

    assert item["status"] == "approved"

    assert (
        item["verification_method"]
        == "demo_auto_approved"
    )

    assert item["simulation"] is True
    assert item["gate_read_performed"] is False
    assert item["gate_write_performed"] is False

    assert second["created"] is False

    assert (
        second["item"]["destination_id"]
        == item["destination_id"]
    )

    events = (
        store.list_destination_events(
            item["destination_id"]
        )
    )

    assert [
        event["action"]
        for event
        in events
    ] == [
        "demo_auto_approved"
    ]


def test_registry_scope_hides_other_demo_wallet_account(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    recipients = (
        store.list_recipients(
            owner_account_ids={
                "demo-wallet-1"
            },
        )
    )

    assert recipients

    assert {
        item["owner_account_id"]
        for item
        in recipients
    } == {
        "demo-wallet-1"
    }

    with pytest.raises(
        KeyError,
        match="not found",
    ):
        store.get_recipient(
            "demo-recipient-treasury",
            owner_account_ids={
                "demo-wallet-1"
            },
        )

    destinations = (
        store.list_destinations(
            owner_account_ids={
                "demo-wallet-1"
            },
        )
    )

    assert destinations

    assert {
        item["owner_account_id"]
        for item
        in destinations
    } == {
        "demo-wallet-1"
    }


def test_unknown_or_unprovisioned_network_is_rejected(
    tmp_path: Path,
):
    store = _store(
        tmp_path
    )

    with pytest.raises(
        DemoWithdrawalRegistryError,
        match="not available",
    ):
        store.create_destination_from_recipient(
            recipient_id=(
                "demo-recipient-growth"
            ),
            currency="USDT",
            chain="NOPE",
        )


def test_demo_withdrawal_registry_has_no_gate_or_production_dependencies():
    path = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "app"
        / "demo_withdrawal.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    imports = []

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            imports.extend(
                alias.name
                for alias
                in node.names
            )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            imports.append(
                node.module or ""
            )

    forbidden_import_fragments = (
        "gate_client",
        "sqlalchemy",
        "models",
        "treasury_withdrawal",
        "treasury",
        "config",
        "database",
    )

    assert not any(
        fragment in imported
        for imported
        in imports
        for fragment
        in forbidden_import_fragments
    )

    forbidden_symbols = (
        "GateClient",
        "get_gate_account",
        "get_treasury_account",
        "session_scope",
        "require_account_access",
    )

    assert not any(
        symbol in source
        for symbol
        in forbidden_symbols
    )
