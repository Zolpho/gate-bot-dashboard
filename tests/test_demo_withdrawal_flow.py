from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.demo_wallet import DemoWalletStore
from app.demo_withdrawal import DemoWithdrawalStore
from app.demo_withdrawal_flow import (
    DemoWithdrawalFlowStore,
    DemoWithdrawalIdempotencyConflict,
)


def _flow(
    tmp_path: Path,
) -> DemoWithdrawalFlowStore:
    return DemoWithdrawalFlowStore(
        tmp_path
        / "demo"
        / "demo.db"
    )


def test_flow_schema_is_additive_and_preserves_f6b_registry_and_wallet(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    wallet = DemoWalletStore(
        flow.database_path
    )

    registry = DemoWithdrawalStore(
        flow.database_path
    )

    registry.ensure_seeded()

    before_balance = (
        wallet.get_balance_state(
            "demo-wallet-1"
        )
    )

    before_recipients = (
        registry.list_recipients()
    )

    before_destinations = (
        registry.list_destinations()
    )

    assert flow.ensure_ready() is True
    assert flow.ensure_ready() is False

    after_balance = (
        wallet.get_balance_state(
            "demo-wallet-1"
        )
    )

    assert before_balance == after_balance

    assert (
        before_recipients
        == registry.list_recipients()
    )

    assert (
        before_destinations
        == registry.list_destinations()
    )

    assert flow.list_requests() == []


def test_preflight_models_gross_debit_fee_and_recipient_amount(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    preflight = flow.preflight(
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
        as_of=(
            "2026-10-17T14:00:00+00:00"
        ),
    )

    assert (
        preflight[
            "preflight_valid"
        ]
        is True
    )

    assert (
        preflight["amount"]
        == "50"
    )

    assert (
        preflight["fee"][
            "estimated_fee"
        ]
        == "1.04"
    )

    assert (
        preflight["fee"][
            "recipient_amount_estimate"
        ]
        == "48.96"
    )

    assert (
        preflight["fee"][
            "fee_is_inside_gross_amount"
        ]
        is True
    )

    assert (
        preflight["funding"][
            "conservative_funding_required"
        ]
        == "50"
    )

    assert (
        preflight["funding"][
            "jit_required"
        ]
        is False
    )

    assert (
        preflight[
            "gate_read_performed"
        ]
        is False
    )

    assert (
        preflight[
            "gate_write_performed"
        ]
        is False
    )


def test_preflight_enforces_recipient_minimum_and_precision(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    below_minimum = flow.preflight(
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="10",
    )

    assert (
        below_minimum[
            "preflight_valid"
        ]
        is False
    )

    assert (
        "recipient_below_minimum"
        in {
            item["type"]
            for item
            in below_minimum[
                "errors"
            ]
        }
    )

    excessive_precision = flow.preflight(
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50.0000001",
    )

    assert (
        excessive_precision[
            "preflight_valid"
        ]
        is False
    )

    assert (
        "amount_precision_exceeded"
        in {
            item["type"]
            for item
            in excessive_precision[
                "errors"
            ]
        }
    )


def test_preflight_enforces_maximum_and_available_balance(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    preflight = flow.preflight(
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="12501",
    )

    blockers = {
        item["type"]
        for item
        in preflight[
            "errors"
        ]
    }

    assert (
        "maximum_per_withdrawal_exceeded"
        in blockers
    )

    assert (
        "insufficient_available_balance"
        in blockers
    )

    assert (
        preflight[
            "preflight_valid"
        ]
        is False
    )


def test_valid_request_records_immutable_preflight_and_destination_snapshot(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    result = flow.create_request(
        request_id=(
            "demo-withdrawal-req-001"
        ),
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
        username="demo",
        occurred_at=(
            "2026-10-17T14:10:00+00:00"
        ),
    )

    assert (
        result["status"]
        == "ready"
    )

    assert (
        result[
            "audit_recorded"
        ]
        is True
    )

    assert (
        result[
            "audit_created"
        ]
        is True
    )

    audit = result["audit"]

    assert (
        audit["status"]
        == "simulated"
    )

    assert (
        audit["amount"]
        == "50"
    )

    assert (
        audit[
            "estimated_fee"
        ]
        == "1.04"
    )

    assert (
        audit[
            "recipient_amount"
        ]
        == "48.96"
    )

    assert (
        audit[
            "balance_debited"
        ]
        is False
    )

    snapshot = (
        audit[
            "destination_snapshot"
        ]
    )

    assert (
        snapshot[
            "destination_id"
        ]
        == (
            "demo-destination-growth-usdt-eth"
        )
    )

    assert (
        snapshot["currency"]
        == "USDT"
    )

    assert (
        snapshot["chain"]
        == "ETH"
    )

    assert (
        snapshot[
            "verification_method"
        ]
        == "demo_auto_approved"
    )


def test_invalid_preflight_never_creates_request_audit(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    result = flow.create_request(
        request_id=(
            "demo-withdrawal-bad-001"
        ),
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="10",
    )

    assert (
        result["status"]
        == "invalid"
    )

    assert (
        result[
            "audit_recorded"
        ]
        is False
    )

    assert (
        result[
            "audit_created"
        ]
        is False
    )

    assert flow.list_requests() == []

    with pytest.raises(
        KeyError,
        match="not found",
    ):
        flow.get_request(
            "demo-withdrawal-bad-001"
        )


def test_request_replay_resolves_before_fresh_preflight(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    first = flow.create_request(
        request_id=(
            "demo-withdrawal-replay-001"
        ),
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
        occurred_at=(
            "2026-10-17T14:20:00+00:00"
        ),
    )

    assert (
        first["audit_created"]
        is True
    )

    wallet = DemoWalletStore(
        flow.database_path
    )

    wallet.simulate_transfer(
        request_id=(
            "f6c1-balance-drain-001"
        ),
        source_account_id=(
            "demo-wallet-1"
        ),
        destination_account_id=(
            "demo-wallet-2"
        ),
        currency="USDT",
        amount="12490",
        username="demo",
        occurred_at=(
            "2026-10-17T14:21:00+00:00"
        ),
    )

    fresh_now = flow.preflight(
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
        as_of=(
            "2026-10-17T14:22:00+00:00"
        ),
    )

    assert (
        fresh_now[
            "preflight_valid"
        ]
        is False
    )

    replay = flow.create_request(
        request_id=(
            "demo-withdrawal-replay-001"
        ),
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
        occurred_at=(
            "2026-10-17T14:22:00+00:00"
        ),
    )

    assert (
        replay[
            "idempotent_replay"
        ]
        is True
    )

    assert (
        replay[
            "current_preflight_rechecked"
        ]
        is False
    )

    assert (
        replay["preflight"][
            "preflight_valid"
        ]
        is True
    )

    assert (
        len(
            flow.list_requests()
        )
        == 1
    )


def test_request_id_conflict_rejects_different_withdrawal_intent(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    flow.create_request(
        request_id=(
            "demo-withdrawal-conflict-001"
        ),
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
    )

    with pytest.raises(
        DemoWithdrawalIdempotencyConflict,
        match="different withdrawal operation",
    ):
        flow.create_request(
            request_id=(
                "demo-withdrawal-conflict-001"
            ),
            owner_account_id=(
                "demo-wallet-1"
            ),
            destination_id=(
                "demo-destination-growth-usdt-eth"
            ),
            currency="USDT",
            amount="51",
        )


def test_request_scope_and_event_history_are_demo_account_isolated(
    tmp_path: Path,
):
    flow = _flow(
        tmp_path
    )

    flow.create_request(
        request_id=(
            "demo-withdrawal-scope-001"
        ),
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
    )

    flow.create_request(
        request_id=(
            "demo-withdrawal-scope-002"
        ),
        owner_account_id=(
            "demo-wallet-2"
        ),
        destination_id=(
            "demo-destination-treasury-usdt-trx"
        ),
        currency="USDT",
        amount="100",
    )

    wallet_one = flow.list_requests(
        account_ids={
            "demo-wallet-1"
        }
    )

    assert [
        item[
            "request_id"
        ]
        for item
        in wallet_one
    ] == [
        "demo-withdrawal-scope-001"
    ]

    with pytest.raises(
        KeyError,
        match="not found",
    ):
        flow.get_request(
            "demo-withdrawal-scope-002",
            account_ids={
                "demo-wallet-1"
            },
        )

    events = (
        flow.list_request_events(
            "demo-withdrawal-scope-001"
        )
    )

    assert len(events) == 1

    assert (
        events[0][
            "action"
        ]
        == "simulated"
    )

    assert (
        events[0][
            "to_status"
        ]
        == "simulated"
    )

    assert (
        events[0][
            "details"
        ][
            "gate_write_performed"
        ]
        is False
    )

    replay = flow.create_request(
        request_id=(
            "demo-withdrawal-scope-001"
        ),
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
    )

    assert (
        replay[
            "idempotent_replay"
        ]
        is True
    )

    assert (
        len(
            flow.list_request_events(
                "demo-withdrawal-scope-001"
            )
        )
        == 1
    )


def test_flow_module_has_no_gate_treasury_or_production_dependencies():
    path = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "app"
        / "demo_withdrawal_flow.py"
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
        "submit_withdrawal",
    )

    assert not any(
        symbol in source
        for symbol
        in forbidden_symbols
    )
