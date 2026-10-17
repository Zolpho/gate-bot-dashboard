from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.demo_wallet import DemoWalletStore
from app.demo_withdrawal_flow import (
    DemoWithdrawalFlowStore,
)
from app.demo_withdrawal_lifecycle import (
    DemoWithdrawalLifecycleError,
    DemoWithdrawalLifecycleStore,
    DemoWithdrawalLocked,
    demo_withdrawal_confirmation_text,
    demo_withdrawal_execution_confirmation_text,
    demo_withdrawal_jit_execution_confirmation_text,
    demo_withdrawal_jit_preparation_confirmation_text,
    demo_withdrawal_reservation_confirmation_text,
)


def _db_path(
    tmp_path: Path,
) -> Path:
    return (
        tmp_path
        / "demo"
        / "demo.db"
    )


def _flow(
    tmp_path: Path,
) -> DemoWithdrawalFlowStore:
    return DemoWithdrawalFlowStore(
        _db_path(
            tmp_path
        )
    )


def _lifecycle(
    tmp_path: Path,
) -> DemoWithdrawalLifecycleStore:
    return DemoWithdrawalLifecycleStore(
        _db_path(
            tmp_path
        )
    )


def _wallet(
    tmp_path: Path,
) -> DemoWalletStore:
    return DemoWalletStore(
        _db_path(
            tmp_path
        )
    )


def _create_request(
    tmp_path: Path,
    request_id: str,
    amount: str = "50",
):
    flow = _flow(
        tmp_path
    )

    result = flow.create_request(
        request_id=request_id,
        owner_account_id=(
            "demo-wallet-1"
        ),
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount=amount,
        username="demo",
        occurred_at=(
            "2026-10-17T15:00:00+00:00"
        ),
    )

    assert (
        result[
            "audit_created"
        ]
        is True
    )

    return flow


def _progress_to_jit_ready(
    tmp_path: Path,
    request_id: str,
):
    flow = _create_request(
        tmp_path,
        request_id,
    )

    lifecycle = _lifecycle(
        tmp_path
    )

    lifecycle.reserve(
        request_id=request_id,
        confirmation=(
            demo_withdrawal_reservation_confirmation_text(
                request_id
            )
        ),
        occurred_at=(
            "2026-10-17T15:01:00+00:00"
        ),
    )

    request = flow.get_request(
        request_id
    )

    lifecycle.confirm(
        request_id=request_id,
        confirmation=(
            demo_withdrawal_confirmation_text(
                request
            )
        ),
        occurred_at=(
            "2026-10-17T15:02:00+00:00"
        ),
    )

    lifecycle.prepare_jit(
        request_id=request_id,
        confirmation=(
            demo_withdrawal_jit_preparation_confirmation_text(
                request_id
            )
        ),
        occurred_at=(
            "2026-10-17T15:03:00+00:00"
        ),
    )

    request = flow.get_request(
        request_id
    )

    lifecycle.execute_jit(
        request_id=request_id,
        confirmation=(
            demo_withdrawal_jit_execution_confirmation_text(
                request
            )
        ),
        occurred_at=(
            "2026-10-17T15:04:00+00:00"
        ),
    )

    return (
        flow,
        lifecycle,
    )


def _usdt_state(
    wallet: DemoWalletStore,
):
    state = wallet.get_balance_state(
        "demo-wallet-1"
    )

    return next(
        item
        for item
        in state["assets"]
        if item["currency"]
        == "USDT"
    )


def test_lifecycle_schema_is_additive_and_creates_no_lock_or_balance_change(
    tmp_path: Path,
):
    flow = _create_request(
        tmp_path,
        "demo-life-schema-001",
    )

    wallet = _wallet(
        tmp_path
    )

    before = _usdt_state(
        wallet
    )

    lifecycle = _lifecycle(
        tmp_path
    )

    lifecycle.ensure_ready()
    lifecycle.ensure_ready()

    after = _usdt_state(
        wallet
    )

    assert before == after
    assert lifecycle.list_locks() == []

    request = flow.get_request(
        "demo-life-schema-001"
    )

    assert (
        request["status"]
        == "simulated"
    )

    assert (
        request[
            "balance_debited"
        ]
        is False
    )


def test_reservation_requires_exact_demo_confirmation_and_acquires_lock(
    tmp_path: Path,
):
    flow = _create_request(
        tmp_path,
        "demo-life-reserve-001",
    )

    lifecycle = _lifecycle(
        tmp_path
    )

    with pytest.raises(
        DemoWithdrawalLifecycleError,
        match="reservation confirmation",
    ):
        lifecycle.reserve(
            request_id=(
                "demo-life-reserve-001"
            ),
            confirmation="WRONG",
        )

    assert lifecycle.list_locks() == []

    result = lifecycle.reserve(
        request_id=(
            "demo-life-reserve-001"
        ),
        confirmation=(
            demo_withdrawal_reservation_confirmation_text(
                "demo-life-reserve-001"
            )
        ),
    )

    assert (
        result["status"]
        == "reserved"
    )

    assert (
        result[
            "reservation_created"
        ]
        is True
    )

    lock = lifecycle.get_lock(
        "demo-life-reserve-001"
    )

    assert lock is not None

    assert (
        lock[
            "owner_account_id"
        ]
        == "demo-wallet-1"
    )

    assert (
        lock["currency"]
        == "USDT"
    )

    assert (
        flow.get_request(
            "demo-life-reserve-001"
        )["balance_debited"]
        is False
    )


def test_same_wallet_currency_lock_blocks_second_unresolved_withdrawal(
    tmp_path: Path,
):
    flow = _create_request(
        tmp_path,
        "demo-life-lock-001",
    )

    flow.create_request(
        request_id=(
            "demo-life-lock-002"
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

    lifecycle = _lifecycle(
        tmp_path
    )

    lifecycle.reserve(
        request_id=(
            "demo-life-lock-001"
        ),
        confirmation=(
            demo_withdrawal_reservation_confirmation_text(
                "demo-life-lock-001"
            )
        ),
    )

    with pytest.raises(
        DemoWithdrawalLocked,
        match="operation lock",
    ):
        lifecycle.reserve(
            request_id=(
                "demo-life-lock-002"
            ),
            confirmation=(
                demo_withdrawal_reservation_confirmation_text(
                    "demo-life-lock-002"
                )
            ),
        )

    assert (
        len(
            lifecycle.list_locks()
        )
        == 1
    )

    assert (
        lifecycle.list_locks()[
            0
        ][
            "owner_request_id"
        ]
        == "demo-life-lock-001"
    )


def test_confirmation_rechecks_preflight_without_debit(
    tmp_path: Path,
):
    flow = _create_request(
        tmp_path,
        "demo-life-confirm-001",
    )

    lifecycle = _lifecycle(
        tmp_path
    )

    lifecycle.reserve(
        request_id=(
            "demo-life-confirm-001"
        ),
        confirmation=(
            demo_withdrawal_reservation_confirmation_text(
                "demo-life-confirm-001"
            )
        ),
    )

    request = flow.get_request(
        "demo-life-confirm-001"
    )

    result = lifecycle.confirm(
        request_id=(
            "demo-life-confirm-001"
        ),
        confirmation=(
            demo_withdrawal_confirmation_text(
                request
            )
        ),
    )

    assert (
        result["status"]
        == "confirmed_ready"
    )

    assert (
        result[
            "current_preflight_rechecked"
        ]
        is True
    )

    updated = flow.get_request(
        "demo-life-confirm-001"
    )

    assert (
        updated[
            "balance_debited"
        ]
        is False
    )

    assert (
        lifecycle.get_lock(
            "demo-life-confirm-001"
        )
        is not None
    )


def test_demo_jit_lifecycle_is_explicit_no_jit_and_never_moves_balance(
    tmp_path: Path,
):
    flow = _create_request(
        tmp_path,
        "demo-life-jit-001",
    )

    lifecycle = _lifecycle(
        tmp_path
    )

    wallet = _wallet(
        tmp_path
    )

    before = _usdt_state(
        wallet
    )

    lifecycle.reserve(
        request_id=(
            "demo-life-jit-001"
        ),
        confirmation=(
            demo_withdrawal_reservation_confirmation_text(
                "demo-life-jit-001"
            )
        ),
    )

    lifecycle.confirm(
        request_id=(
            "demo-life-jit-001"
        ),
        confirmation=(
            demo_withdrawal_confirmation_text(
                flow.get_request(
                    "demo-life-jit-001"
                )
            )
        ),
    )

    prepared = lifecycle.prepare_jit(
        request_id=(
            "demo-life-jit-001"
        ),
        confirmation=(
            demo_withdrawal_jit_preparation_confirmation_text(
                "demo-life-jit-001"
            )
        ),
    )

    assert (
        prepared["status"]
        == "jit_prepared"
    )

    assert (
        prepared[
            "jit_plan"
        ][
            "jit_required"
        ]
        is False
    )

    assert (
        prepared[
            "jit_plan"
        ][
            "jit_amount_preview"
        ]
        == "0"
    )

    ready = lifecycle.execute_jit(
        request_id=(
            "demo-life-jit-001"
        ),
        confirmation=(
            demo_withdrawal_jit_execution_confirmation_text(
                flow.get_request(
                    "demo-life-jit-001"
                )
            )
        ),
    )

    assert (
        ready["status"]
        == "jit_ready"
    )

    assert (
        ready[
            "jit_transfer_performed"
        ]
        is False
    )

    assert (
        _usdt_state(
            wallet
        )
        == before
    )

    assert (
        flow.get_request(
            "demo-life-jit-001"
        )[
            "balance_debited"
        ]
        is False
    )


def test_simulated_execution_atomically_debits_gross_once_and_releases_lock(
    tmp_path: Path,
):
    flow, lifecycle = (
        _progress_to_jit_ready(
            tmp_path,
            "demo-life-exec-001",
        )
    )

    wallet = _wallet(
        tmp_path
    )

    before = _usdt_state(
        wallet
    )

    request = flow.get_request(
        "demo-life-exec-001"
    )

    result = lifecycle.execute(
        request_id=(
            "demo-life-exec-001"
        ),
        confirmation=(
            demo_withdrawal_execution_confirmation_text(
                request
            )
        ),
        occurred_at=(
            "2026-10-17T15:05:00+00:00"
        ),
    )

    after = _usdt_state(
        wallet
    )

    assert (
        result["status"]
        == "withdrawal_settled"
    )

    assert (
        result[
            "local_write_performed"
        ]
        is True
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        result[
            "gross_debit"
        ]
        == "50"
    )

    assert (
        result[
            "estimated_fee"
        ]
        == "1.04"
    )

    assert (
        result[
            "recipient_amount"
        ]
        == "48.96"
    )

    assert (
        before["available"]
        == "12500"
    )

    assert (
        after["available"]
        == "12450"
    )

    assert (
        after["locked"]
        == before["locked"]
    )

    settled = flow.get_request(
        "demo-life-exec-001"
    )

    assert (
        settled[
            "balance_debited"
        ]
        is True
    )

    assert (
        settled[
            "write_performed"
        ]
        is False
    )

    assert (
        settled[
            "demo_withdrawal_id"
        ].startswith(
            "demo-withdrawal-"
        )
    )

    assert (
        lifecycle.get_lock(
            "demo-life-exec-001"
        )
        is None
    )


def test_settled_execution_replay_skips_fresh_preflight_and_second_debit(
    tmp_path: Path,
):
    flow, lifecycle = (
        _progress_to_jit_ready(
            tmp_path,
            "demo-life-replay-001",
        )
    )

    wallet = _wallet(
        tmp_path
    )

    request = flow.get_request(
        "demo-life-replay-001"
    )

    confirmation = (
        demo_withdrawal_execution_confirmation_text(
            request
        )
    )

    first = lifecycle.execute(
        request_id=(
            "demo-life-replay-001"
        ),
        confirmation=confirmation,
    )

    after_first = _usdt_state(
        wallet
    )

    replay = lifecycle.execute(
        request_id=(
            "demo-life-replay-001"
        ),
        confirmation=(
            "STALE CONFIRMATION IS IGNORED "
            "FOR TERMINAL REPLAY"
        ),
    )

    after_replay = _usdt_state(
        wallet
    )

    assert (
        first[
            "idempotent_replay"
        ]
        is False
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
        replay[
            "local_write_performed"
        ]
        is False
    )

    assert (
        after_first
        == after_replay
    )

    events = flow.list_request_events(
        "demo-life-replay-001"
    )

    assert (
        [
            event["action"]
            for event
            in events
        ].count(
            "simulated_withdrawal_settled"
        )
        == 1
    )


def test_wrong_execution_confirmation_never_debits_or_releases_lock(
    tmp_path: Path,
):
    flow, lifecycle = (
        _progress_to_jit_ready(
            tmp_path,
            "demo-life-wrong-confirm-001",
        )
    )

    wallet = _wallet(
        tmp_path
    )

    before = _usdt_state(
        wallet
    )

    with pytest.raises(
        DemoWithdrawalLifecycleError,
        match="execution confirmation",
    ):
        lifecycle.execute(
            request_id=(
                "demo-life-wrong-confirm-001"
            ),
            confirmation="WRONG",
        )

    after = _usdt_state(
        wallet
    )

    assert before == after

    request = flow.get_request(
        "demo-life-wrong-confirm-001"
    )

    assert (
        request["status"]
        == "jit_ready"
    )

    assert (
        request[
            "balance_debited"
        ]
        is False
    )

    assert (
        lifecycle.get_lock(
            "demo-life-wrong-confirm-001"
        )
        is not None
    )


def test_fresh_preflight_blocks_execution_if_available_balance_changed(
    tmp_path: Path,
):
    flow, lifecycle = (
        _progress_to_jit_ready(
            tmp_path,
            "demo-life-fresh-block-001",
        )
    )

    wallet = _wallet(
        tmp_path
    )

    wallet.simulate_transfer(
        request_id=(
            "demo-life-drain-001"
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
            "2026-10-17T15:05:00+00:00"
        ),
    )

    before_attempt = _usdt_state(
        wallet
    )

    request = flow.get_request(
        "demo-life-fresh-block-001"
    )

    with pytest.raises(
        DemoWithdrawalLifecycleError,
        match="Fresh Demo withdrawal preflight rejected",
    ):
        lifecycle.execute(
            request_id=(
                "demo-life-fresh-block-001"
            ),
            confirmation=(
                demo_withdrawal_execution_confirmation_text(
                    request
                )
            ),
            occurred_at=(
                "2026-10-17T15:06:00+00:00"
            ),
        )

    after_attempt = _usdt_state(
        wallet
    )

    assert (
        before_attempt
        == after_attempt
    )

    blocked = flow.get_request(
        "demo-life-fresh-block-001"
    )

    assert (
        blocked["status"]
        == "jit_ready"
    )

    assert (
        blocked[
            "balance_debited"
        ]
        is False
    )

    assert (
        lifecycle.get_lock(
            "demo-life-fresh-block-001"
        )
        is not None
    )


def test_lifecycle_module_has_no_gate_treasury_or_production_dependencies():
    path = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "app"
        / "demo_withdrawal_lifecycle.py"
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
        "submit_withdrawal",
        "reconcile_withdrawal",
    )

    assert not any(
        symbol in source
        for symbol
        in forbidden_symbols
    )
