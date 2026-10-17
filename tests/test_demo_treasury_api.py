from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.demo_treasury_api import (
    DEMO_TRANSFER_PATH,
    DemoTreasuryConfirmationError,
    DemoTreasuryTransferBlocked,
    demo_ownership_balances_payload,
    demo_ownership_ledger_payload,
    demo_transfer_events_payload,
    demo_transfer_request_detail_payload,
    demo_transfer_requests_payload,
    demo_user_transfer_confirmation_text,
    demo_user_transfer_execute_payload,
    demo_user_transfer_participants_payload,
    demo_user_transfer_preview_payload,
)
from app.demo_wallet import (
    DemoWalletStore,
)


def _store(
    tmp_path: Path,
) -> DemoWalletStore:
    return DemoWalletStore(
        tmp_path
        / "isolated-demo"
        / "demo.db"
    )


def _asset(
    payload,
    currency: str,
):
    return next(
        item
        for item
        in payload[
            "assets"
        ]
        if item[
            "currency"
        ]
        == currency
    )


def test_ownership_payloads_match_live_envelopes_and_scope(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    balances = (
        demo_ownership_balances_payload(
            store=store,
            account_ids={
                "demo-wallet-1",
            },
        )
    )

    ledger = (
        demo_ownership_ledger_payload(
            store=store,
            account_ids={
                "demo-wallet-1",
            },
            limit=2,
        )
    )

    assert balances[
        "phase"
    ] == "T2B_TRANSFER_CONTROL"

    assert balances[
        "source"
    ] == "demo"

    assert balances[
        "gate_read_performed"
    ] is False

    assert balances[
        "gate_write_performed"
    ] is False

    assert {
        item[
            "currency"
        ]
        for item
        in balances[
            "items"
        ]
    } == {
        "USDT",
        "EQTY",
        "ETH",
    }

    assert ledger[
        "phase"
    ] == "T2B_TRANSFER_CONTROL"

    assert len(
        ledger[
            "items"
        ]
    ) == 2

    assert all(
        (
            item[
                "owner_account_id"
            ]
            == "demo-wallet-1"
            or item[
                "custody_account_id"
            ]
            == "demo-wallet-1"
        )
        for item
        in ledger[
            "items"
        ]
    )


def test_transfer_list_detail_and_events_payloads_are_demo_only(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    listing = (
        demo_transfer_requests_payload(
            store=store,
            account_ids={
                "demo-wallet-1",
            },
        )
    )

    assert listing[
        "phase"
    ] == "T2B_TRANSFER_CONTROL"

    assert len(
        listing[
            "items"
        ]
    ) == 2

    request_id = listing[
        "items"
    ][
        0
    ][
        "request_id"
    ]

    detail = (
        demo_transfer_request_detail_payload(
            store=store,
            request_id=request_id,
            account_ids={
                "demo-wallet-1",
            },
        )
    )

    assert detail[
        "item"
    ][
        "request_id"
    ] == request_id

    assert detail[
        "reconciliations"
    ] == []

    assert detail[
        "operation_lock"
    ] is None

    assert detail[
        "lock_resolutions"
    ] == []

    assert detail[
        "gate_read_performed"
    ] is False

    events = (
        demo_transfer_events_payload(
            store=store,
            request_id=request_id,
        )
    )

    assert [
        item[
            "event_type"
        ]
        for item
        in events[
            "items"
        ]
    ] == [
        "created",
        "completed",
    ]

    assert events[
        "gate_write_performed"
    ] is False


def test_participants_payload_uses_only_demo_accounts_and_fake_balances(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    payload = (
        demo_user_transfer_participants_payload(
            store=store,
            source_account_ids={
                "demo-wallet-1",
                "demo-wallet-2",
            },
        )
    )

    assert payload[
        "phase"
    ] == "USER_ACCOUNT_TRANSFER"

    assert payload[
        "user_transfers_enabled"
    ] is True

    assert payload[
        "execution_implemented"
    ] is True

    assert payload[
        "gate_read_performed"
    ] is False

    assert payload[
        "gate_write_performed"
    ] is False

    assert [
        item[
            "account_id"
        ]
        for item
        in payload[
            "items"
        ]
    ] == [
        "demo-wallet-1",
        "demo-wallet-2",
    ]

    assert all(
        item[
            "account_type"
        ]
        == "demo"
        for item
        in payload[
            "items"
        ]
    )

    assert all(
        item[
            "can_source"
        ]
        is True
        for item
        in payload[
            "items"
        ]
    )

    assert all(
        item[
            "can_receive"
        ]
        is True
        for item
        in payload[
            "items"
        ]
    )

    growth = payload[
        "items"
    ][
        0
    ]

    balances = {
        item[
            "currency"
        ]:
            item[
                "available"
            ]
        for item
        in growth[
            "available_balances"
        ]
    }

    assert balances[
        "USDT"
    ] == "12500"


def test_preview_payload_matches_user_transfer_contract_without_gate(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    payload = (
        demo_user_transfer_preview_payload(
            store=store,
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="100.00",
        )
    )

    assert payload[
        "status"
    ] == "ready"

    assert payload[
        "can_execute"
    ] is True

    assert payload[
        "gate_read_performed"
    ] is False

    assert payload[
        "gate_write_required"
    ] is False

    assert payload[
        "gate_write_performed"
    ] is False

    preview = payload[
        "preview"
    ]

    assert preview[
        "amount"
    ] == "100"

    assert preview[
        "source_available_before"
    ] == "12500"

    assert preview[
        "source_available_after"
    ] == "12400"

    assert preview[
        "destination_available_before"
    ] == "42000"

    assert preview[
        "destination_available_after"
    ] == "42100"

    assert preview[
        "transfer_path"
    ] == DEMO_TRANSFER_PATH

    assert preview[
        "ownership_changed"
    ] is False

    assert payload[
        "required_confirmation"
    ] == (
        "DEMO TRANSFER 100 USDT "
        "FROM demo-wallet-1 "
        "TO demo-wallet-2"
    )


def test_blocked_preview_is_read_only(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    before = store.get_balance_state(
        "demo-wallet-1"
    )

    payload = (
        demo_user_transfer_preview_payload(
            store=store,
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="999999",
        )
    )

    assert payload[
        "status"
    ] == "blocked"

    assert payload[
        "can_execute"
    ] is False

    assert payload[
        "preview"
    ][
        "operation_blockers"
    ][
        0
    ][
        "type"
    ] == (
        "insufficient_available_balance"
    )

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == before
    )


def test_execute_rejects_bad_confirmation_without_mutation(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    before = store.get_balance_state(
        "demo-wallet-1"
    )

    with pytest.raises(
        DemoTreasuryConfirmationError,
        match=(
            "Invalid Demo transfer confirmation text"
        ),
    ):
        demo_user_transfer_execute_payload(
            store=store,
            request_id=(
                "demo-api-transfer-001"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="25",
            username="demo",
            donation=False,
            confirmation="WRONG",
            occurred_at=(
                "2026-10-17T11:00:00+00:00"
            ),
        )

    assert (
        store.get_balance_state(
            "demo-wallet-1"
        )
        == before
    )

    with pytest.raises(
        KeyError
    ):
        store.get_transfer(
            "demo-api-transfer-001"
        )


def test_execute_success_mutates_demo_balances_and_preserves_ownership(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    ownership_before = (
        store.ownership_balances()
    )

    confirmation = (
        demo_user_transfer_confirmation_text(
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="250",
        )
    )

    payload = (
        demo_user_transfer_execute_payload(
            store=store,
            request_id=(
                "demo-api-transfer-002"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="250",
            username="demo",
            donation=False,
            confirmation=confirmation,
            occurred_at=(
                "2026-10-17T11:01:00+00:00"
            ),
        )
    )

    assert payload[
        "phase"
    ] == "USER_ACCOUNT_TRANSFER"

    assert payload[
        "status"
    ] == "success"

    assert payload[
        "simulation"
    ] is True

    assert payload[
        "gate_read_performed"
    ] is False

    assert payload[
        "gate_write_required"
    ] is False

    assert payload[
        "gate_write_performed"
    ] is False

    assert payload[
        "idempotent_replay"
    ] is False

    assert payload[
        "transfer_path"
    ] == DEMO_TRANSFER_PATH

    assert payload[
        "operation_lock"
    ] is None

    assert payload[
        "gate_payload"
    ] is None

    growth = store.get_balance_state(
        "demo-wallet-1"
    )

    treasury = store.get_balance_state(
        "demo-wallet-2"
    )

    assert _asset(
        growth,
        "USDT",
    )[
        "available"
    ] == "12250"

    assert _asset(
        treasury,
        "USDT",
    )[
        "available"
    ] == "42250"

    assert (
        store.ownership_balances()
        == ownership_before
    )


def test_execute_replay_is_idempotent_even_when_source_balance_is_zero(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    confirmation = (
        demo_user_transfer_confirmation_text(
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="12500",
        )
    )

    first = (
        demo_user_transfer_execute_payload(
            store=store,
            request_id=(
                "demo-api-transfer-003"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="12500",
            username="demo",
            donation=False,
            confirmation=confirmation,
            occurred_at=(
                "2026-10-17T11:02:00+00:00"
            ),
        )
    )

    assert first[
        "idempotent_replay"
    ] is False

    assert _asset(
        store.get_balance_state(
            "demo-wallet-1"
        ),
        "USDT",
    )[
        "available"
    ] == "0"

    replay = (
        demo_user_transfer_execute_payload(
            store=store,
            request_id=(
                "demo-api-transfer-003"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="12500.0",
            username="demo",
            donation=False,
            confirmation="STALE CONFIRMATION AFTER SUCCESS",
            occurred_at=(
                "2026-10-17T12:00:00+00:00"
            ),
        )
    )

    assert replay[
        "idempotent_replay"
    ] is True

    assert replay[
        "status"
    ] == "success"

    assert _asset(
        store.get_balance_state(
            "demo-wallet-1"
        ),
        "USDT",
    )[
        "available"
    ] == "0"

    matching = [
        item
        for item
        in store.list_transfers()
        if item[
            "request_id"
        ]
        == "demo-api-transfer-003"
    ]

    assert len(
        matching
    ) == 1


def test_execute_blocked_and_unknown_account_fail_closed(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    confirmation = (
        demo_user_transfer_confirmation_text(
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="999999",
        )
    )

    with pytest.raises(
        DemoTreasuryTransferBlocked,
        match="only",
    ):
        demo_user_transfer_execute_payload(
            store=store,
            request_id=(
                "demo-api-transfer-004"
            ),
            source_account_id=(
                "demo-wallet-1"
            ),
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="999999",
            username="demo",
            donation=False,
            confirmation=confirmation,
        )

    with pytest.raises(
        KeyError,
        match=(
            "Unknown Demo Wallet account"
        ),
    ):
        demo_user_transfer_participants_payload(
            store=store,
            source_account_ids={
                "zolnode",
            },
        )

    with pytest.raises(
        KeyError,
        match=(
            "Unknown Demo Wallet account"
        ),
    ):
        demo_user_transfer_preview_payload(
            store=store,
            source_account_id="zolnode",
            destination_account_id=(
                "demo-wallet-2"
            ),
            currency="USDT",
            amount="1",
        )


def test_demo_treasury_adapter_has_no_route_gate_or_production_dependencies():
    path = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "app"
        / "demo_treasury_api.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        ),
        filename=str(
            path
        ),
    )

    imported_modules: set[
        str
    ] = set()

    imported_symbols: set[
        str
    ] = set()

    called_names: set[
        str
    ] = set()

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                imported_modules.add(
                    alias.name
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            imported_modules.add(
                node.module
                or ""
            )

            for alias in node.names:
                imported_symbols.add(
                    alias.name
                )

        elif isinstance(
            node,
            ast.Call,
        ):
            if isinstance(
                node.func,
                ast.Name,
            ):
                called_names.add(
                    node.func.id
                )

            # Only direct-name calls matter here. Attribute
            # calls such as store.list_ownership_entries()
            # are legitimate isolated DemoWalletStore methods.

    forbidden_modules = {
        "accounts",
        "config",
        "db",
        "fastapi",
        "gate_client",
        "models",
        "security",
        "sqlalchemy",
        "treasury",
        "treasury_ownership",
        "treasury_transfer",
        "treasury_transfer_audit",
        "treasury_transfer_execution",
        "treasury_user_transfer_execution",
    }

    for module in imported_modules:
        normalized = (
            module
            .lstrip(".")
            .split(".")[0]
        )

        assert (
            normalized
            not in forbidden_modules
        ), module

    for symbol in (
        "GateClient",
        "HTTPException",
        "Session",
        "SessionLocal",
        "get_gate_account",
        "get_settings",
        "session_scope",
        "list_ownership_entries",
        "ownership_balances",
        "list_transfer_requests",
        "record_simulation",
        "execute_user_account_transfer",
    ):
        assert (
            symbol
            not in imported_symbols
        ), symbol

        assert (
            symbol
            not in called_names
        ), symbol

    assert (
        "DemoWalletStore"
        in imported_symbols
    )
