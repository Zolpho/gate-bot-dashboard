from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.demo_wallet import DemoWalletStore
from app.demo_withdrawal_api import (
    DemoWithdrawalApi,
    DemoWithdrawalAuthorizationError,
)


def _api(
    tmp_path: Path,
) -> DemoWithdrawalApi:
    return DemoWithdrawalApi(
        tmp_path
        / "demo"
        / "demo.db"
    )


def _scope_one() -> set[str]:
    return {
        "demo-wallet-1"
    }


def _scope_both() -> set[str]:
    return {
        "demo-wallet-1",
        "demo-wallet-2",
    }


def _simulate(
    api: DemoWithdrawalApi,
    request_id: str,
):
    result = api.simulate_request_payload(
        account_ids=_scope_one(),
        request_id=request_id,
        account_id="demo-wallet-1",
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
        username="demo",
    )

    assert (
        result[
            "audit_created"
        ]
        is True
    )

    return result


def test_capabilities_and_preflight_are_scoped_synthetic_contracts(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    capabilities = api.capabilities_payload(
        account_ids=_scope_one(),
        account_id="demo-wallet-1",
        currency="USDT",
    )

    assert (
        capabilities["source"]
        == "demo"
    )

    assert (
        capabilities["simulation"]
        is True
    )

    assert (
        capabilities[
            "gate_read_performed"
        ]
        is False
    )

    assert {
        item["chain"]
        for item
        in capabilities["chains"]
    } == {
        "ETH",
        "TRX",
    }

    preflight = api.preflight_payload(
        account_ids=_scope_one(),
        account_id="demo-wallet-1",
        destination_id=(
            "demo-destination-growth-usdt-eth"
        ),
        currency="USDT",
        amount="50",
    )

    assert (
        preflight[
            "preflight_valid"
        ]
        is True
    )

    assert (
        preflight["fee"][
            "recipient_amount_estimate"
        ]
        == "48.96"
    )

    assert (
        preflight[
            "gate_write_performed"
        ]
        is False
    )


def test_recipient_management_and_destination_preparation_remain_scoped(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    created = api.create_recipient_payload(
        account_ids=_scope_one(),
        owner_account_id="demo-wallet-1",
        address="DEMO-API-RECIPIENT-001",
        label="API recipient",
    )

    recipient_id = (
        created["recipient"][
            "recipient_id"
        ]
    )

    renamed = api.rename_recipient_payload(
        account_ids=_scope_one(),
        recipient_id=recipient_id,
        label="Renamed API recipient",
    )

    assert (
        renamed["recipient"]["label"]
        == "Renamed API recipient"
    )

    destination = (
        api.prepare_destination_payload(
            account_ids=_scope_one(),
            recipient_id=recipient_id,
            currency="BTC",
            chain="BTC",
        )
    )

    assert (
        destination[
            "destination"
        ][
            "status"
        ]
        == "approved"
    )

    assert (
        destination[
            "destination"
        ][
            "verification_method"
        ]
        == "demo_auto_approved"
    )

    archived = api.archive_recipient_payload(
        account_ids=_scope_one(),
        recipient_id=recipient_id,
    )

    assert (
        archived["recipient"]["status"]
        == "archived"
    )

    restored = api.restore_recipient_payload(
        account_ids=_scope_one(),
        recipient_id=recipient_id,
    )

    assert (
        restored["recipient"]["status"]
        == "active"
    )

    detail = api.recipient_detail_payload(
        account_ids=_scope_one(),
        recipient_id=recipient_id,
    )

    assert [
        event["action"]
        for event
        in detail["events"]
    ] == [
        "created",
        "renamed",
        "archived",
        "restored",
    ]


def test_simulation_payload_exposes_only_demo_reservation_next_step(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    result = _simulate(
        api,
        "demo-api-simulate-001",
    )

    assert (
        result["status"]
        == "ready"
    )

    assert (
        result["next_action"]
        == "reserve"
    )

    assert (
        result[
            "required_confirmation"
        ]
        == (
            "RESERVE DEMO WITHDRAWAL "
            "demo-api-simulate-001"
        )
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        result["executable"]
        is False
    )


def test_request_detail_exposes_only_safe_demo_workflow_actions(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    _simulate(
        api,
        "demo-api-detail-001",
    )

    detail = api.request_detail_payload(
        account_ids=_scope_one(),
        request_id="demo-api-detail-001",
    )

    workflow = detail["workflow"]

    assert (
        workflow["can_reserve"]
        is True
    )

    assert (
        workflow["next_action"]
        == "reserve"
    )

    assert (
        workflow["can_reconcile"]
        is False
    )

    assert (
        workflow["can_settle"]
        is False
    )

    assert (
        workflow["can_abandon"]
        is False
    )

    assert (
        workflow["can_hold_on_main"]
        is False
    )

    assert (
        workflow["can_cancel"]
        is False
    )


def test_adapter_drives_complete_demo_lifecycle_to_settlement(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    wallet = DemoWalletStore(
        api.flow.database_path
    )

    before = wallet.get_balance_state(
        "demo-wallet-1"
    )

    before_usdt = next(
        item
        for item
        in before["assets"]
        if item["currency"]
        == "USDT"
    )

    simulated = _simulate(
        api,
        "demo-api-life-001",
    )

    reserved = api.reserve_payload(
        account_ids=_scope_one(),
        request_id="demo-api-life-001",
        confirmation=(
            simulated[
                "required_confirmation"
            ]
        ),
    )

    assert (
        reserved[
            "detail"
        ][
            "next_action"
        ]
        == "confirm"
    )

    confirmed = api.confirm_payload(
        account_ids=_scope_one(),
        request_id="demo-api-life-001",
        confirmation=(
            reserved[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    assert (
        confirmed[
            "detail"
        ][
            "next_action"
        ]
        == "jit_prepare"
    )

    prepared = api.prepare_jit_payload(
        account_ids=_scope_one(),
        request_id="demo-api-life-001",
        confirmation=(
            confirmed[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    assert (
        prepared[
            "detail"
        ][
            "next_action"
        ]
        == "jit_execute"
    )

    jit_ready = api.execute_jit_payload(
        account_ids=_scope_one(),
        request_id="demo-api-life-001",
        confirmation=(
            prepared[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    assert (
        jit_ready[
            "detail"
        ][
            "next_action"
        ]
        == "execute"
    )

    settled = api.execute_payload(
        account_ids=_scope_one(),
        request_id="demo-api-life-001",
        confirmation=(
            jit_ready[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    assert (
        settled["status"]
        == "withdrawal_settled"
    )

    assert (
        settled[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        settled[
            "local_write_performed"
        ]
        is True
    )

    assert (
        settled[
            "detail"
        ][
            "workflow"
        ][
            "terminal"
        ]
        is True
    )

    assert (
        settled[
            "detail"
        ][
            "next_action"
        ]
        is None
    )

    after = wallet.get_balance_state(
        "demo-wallet-1"
    )

    after_usdt = next(
        item
        for item
        in after["assets"]
        if item["currency"]
        == "USDT"
    )

    assert (
        before_usdt["available"]
        == "12500"
    )

    assert (
        after_usdt["available"]
        == "12450"
    )

    assert (
        after_usdt["locked"]
        == before_usdt["locked"]
    )


def test_terminal_adapter_replay_never_debits_twice(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    wallet = DemoWalletStore(
        api.flow.database_path
    )

    simulated = _simulate(
        api,
        "demo-api-replay-001",
    )

    reserved = api.reserve_payload(
        account_ids=_scope_one(),
        request_id="demo-api-replay-001",
        confirmation=(
            simulated[
                "required_confirmation"
            ]
        ),
    )

    confirmed = api.confirm_payload(
        account_ids=_scope_one(),
        request_id="demo-api-replay-001",
        confirmation=(
            reserved[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    prepared = api.prepare_jit_payload(
        account_ids=_scope_one(),
        request_id="demo-api-replay-001",
        confirmation=(
            confirmed[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    jit_ready = api.execute_jit_payload(
        account_ids=_scope_one(),
        request_id="demo-api-replay-001",
        confirmation=(
            prepared[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    first = api.execute_payload(
        account_ids=_scope_one(),
        request_id="demo-api-replay-001",
        confirmation=(
            jit_ready[
                "detail"
            ][
                "required_confirmation"
            ]
        ),
    )

    balance_after_first = (
        wallet.get_balance_state(
            "demo-wallet-1"
        )
    )

    replay = api.execute_payload(
        account_ids=_scope_one(),
        request_id="demo-api-replay-001",
        confirmation="STALE CONFIRMATION",
    )

    balance_after_replay = (
        wallet.get_balance_state(
            "demo-wallet-1"
        )
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
            "local_write_performed"
        ]
        is False
    )

    assert (
        balance_after_first
        == balance_after_replay
    )


def test_cross_wallet_recipient_destination_and_request_access_fail_closed(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    with pytest.raises(
        DemoWithdrawalAuthorizationError,
        match="recipient",
    ):
        api.recipient_detail_payload(
            account_ids=_scope_one(),
            recipient_id=(
                "demo-recipient-treasury"
            ),
        )

    with pytest.raises(
        DemoWithdrawalAuthorizationError,
        match="destination",
    ):
        api.destination_detail_payload(
            account_ids=_scope_one(),
            destination_id=(
                "demo-destination-treasury-usdt-trx"
            ),
        )

    api.simulate_request_payload(
        account_ids={
            "demo-wallet-2"
        },
        request_id=(
            "demo-api-other-wallet-001"
        ),
        account_id=(
            "demo-wallet-2"
        ),
        destination_id=(
            "demo-destination-treasury-usdt-trx"
        ),
        currency="USDT",
        amount="100",
    )

    with pytest.raises(
        DemoWithdrawalAuthorizationError,
        match="request",
    ):
        api.request_detail_payload(
            account_ids=_scope_one(),
            request_id=(
                "demo-api-other-wallet-001"
            ),
        )


def test_request_and_lock_lists_are_filtered_to_demo_account_scope(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    first = _simulate(
        api,
        "demo-api-scope-001",
    )

    api.simulate_request_payload(
        account_ids={
            "demo-wallet-2"
        },
        request_id=(
            "demo-api-scope-002"
        ),
        account_id=(
            "demo-wallet-2"
        ),
        destination_id=(
            "demo-destination-treasury-usdt-trx"
        ),
        currency="USDT",
        amount="100",
    )

    requests = api.requests_payload(
        account_ids=_scope_one()
    )

    assert [
        item["request_id"]
        for item
        in requests["items"]
    ] == [
        "demo-api-scope-001"
    ]

    api.reserve_payload(
        account_ids=_scope_one(),
        request_id="demo-api-scope-001",
        confirmation=(
            first[
                "required_confirmation"
            ]
        ),
    )

    locks = api.locks_payload(
        account_ids=_scope_one()
    )

    assert (
        locks["count"]
        == 1
    )

    assert (
        locks["items"][0][
            "owner_account_id"
        ]
        == "demo-wallet-1"
    )


def test_destination_and_recipient_list_payloads_never_escape_scope(
    tmp_path: Path,
):
    api = _api(
        tmp_path
    )

    recipients = api.recipients_payload(
        account_ids=_scope_one()
    )

    assert recipients["items"]

    assert {
        item[
            "owner_account_id"
        ]
        for item
        in recipients["items"]
    } == {
        "demo-wallet-1"
    }

    destinations = api.destinations_payload(
        account_ids=_scope_one()
    )

    assert destinations["items"]

    assert {
        item[
            "owner_account_id"
        ]
        for item
        in destinations["items"]
    } == {
        "demo-wallet-1"
    }

    all_destinations = api.destinations_payload(
        account_ids=_scope_both()
    )

    assert {
        item[
            "owner_account_id"
        ]
        for item
        in all_destinations["items"]
    } == {
        "demo-wallet-1",
        "demo-wallet-2",
    }


def test_adapter_has_no_fastapi_gate_treasury_or_production_dependencies():
    path = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "app"
        / "demo_withdrawal_api.py"
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
        "fastapi",
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
        "APIRouter",
        "Depends",
        "HTTPException",
    )

    assert not any(
        symbol in source
        for symbol
        in forbidden_symbols
    )

    forbidden_adapter_methods = (
        "reconcile_payload",
        "settle_payload",
        "abandon_payload",
        "hold_on_main_payload",
        "cancel_payload",
    )

    assert not any(
        method in source
        for method
        in forbidden_adapter_methods
    )
