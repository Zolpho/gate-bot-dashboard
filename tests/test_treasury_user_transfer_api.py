from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import treasury as treasury_api
from app.config import Settings
from app.security import DashboardUser


def _user(
    username: str,
    account_ids: tuple[str, ...],
    *,
    role: str = "account_operator",
    enabled: bool = True,
) -> DashboardUser:
    return DashboardUser(
        username=username,
        role=role,
        account_ids=account_ids,
        enabled=enabled,
    )


def _account(
    account_id: str,
    *,
    account_type: str = "subaccount",
    gate_uid: str = "1001",
    enabled: bool = True,
    configured: bool = True,
):
    return SimpleNamespace(
        id=account_id,
        name=account_id,
        account_type=account_type,
        gate_uid=gate_uid,
        enabled=enabled,
        configured=configured,
    )


def _install_registry(
    monkeypatch,
    *,
    users,
    accounts,
    enabled: bool = False,
):
    monkeypatch.setattr(
        treasury_api,
        "load_dashboard_users",
        lambda _settings=None: tuple(users),
    )

    monkeypatch.setattr(
        treasury_api,
        "get_gate_account",
        lambda account_id: accounts.get(
            str(account_id).strip().lower()
        ),
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=enabled,
            treasury_rate_limit_enabled=False,
        ),
    )


@pytest.mark.asyncio
async def test_participants_are_account_scoped_and_do_not_leak_recipient_balances(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )
    disabled = _user(
        "disabled",
        ("disabled-account",),
        enabled=False,
    )

    accounts = {
        "alice-account": _account(
            "alice-account",
            gate_uid="101",
        ),
        "bob-account": _account(
            "bob-account",
            gate_uid="202",
        ),
        "disabled-account": _account(
            "disabled-account",
            gate_uid="303",
        ),
    }

    _install_registry(
        monkeypatch,
        users=(alice, bob, disabled),
        accounts=accounts,
    )

    calls: list[str] = []

    async def fake_balances(account_id: str):
        calls.append(account_id)

        if account_id == "alice-account":
            return [
                {
                    "currency": "BTC",
                    "available": "0.25",
                },
                {
                    "currency": "USDT",
                    "available": "5",
                },
            ]

        return [
            {
                "currency": "SECRET",
                "available": "999",
            }
        ]

    monkeypatch.setattr(
        treasury_api,
        "_gate_spot_available_balances",
        fake_balances,
    )

    payload = await (
        treasury_api
        .treasury_user_transfer_participants(alice)
    )

    by_id = {
        item["account_id"]: item
        for item in payload["items"]
    }

    assert set(by_id) == {
        "alice-account",
        "bob-account",
    }

    assert by_id["alice-account"]["can_source"] is True
    assert by_id["alice-account"]["can_receive"] is False

    assert by_id["bob-account"]["can_source"] is False
    assert by_id["bob-account"]["can_receive"] is True

    assert by_id["alice-account"]["available_balances"] == [
        {
            "currency": "BTC",
            "available": "0.25",
        },
        {
            "currency": "USDT",
            "available": "5",
        },
    ]

    # Recipient balances must never be disclosed.
    assert by_id["bob-account"]["available_balances"] == []

    # Only the authenticated user's source account was queried.
    assert calls == ["alice-account"]

    assert payload["execution_implemented"] is True
    assert payload["gate_write_performed"] is False


@pytest.mark.asyncio
async def test_super_admin_cannot_source_unassigned_account(
    monkeypatch,
):
    admin = _user(
        "admin",
        ("alice-account",),
        role="super_admin",
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )

    _install_registry(
        monkeypatch,
        users=(admin, bob),
        accounts={
            "alice-account": _account(
                "alice-account",
                gate_uid="101",
            ),
            "bob-account": _account(
                "bob-account",
                gate_uid="202",
            ),
        },
    )

    request = (
        treasury_api.TreasuryUserTransferPreviewRequest(
            source_account_id="bob-account",
            destination_account_id="alice-account",
            currency="USDT",
            amount=Decimal("1"),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await treasury_api.preview_treasury_user_transfer(
            request,
            admin,
        )

    assert exc_info.value.status_code == 403
    assert "not allowed to transfer funds" in str(
        exc_info.value.detail
    )


@pytest.mark.asyncio
async def test_preview_uses_fresh_gate_available_balance(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )

    _install_registry(
        monkeypatch,
        users=(alice, bob),
        accounts={
            "alice-account": _account(
                "alice-account",
                gate_uid="101",
            ),
            "bob-account": _account(
                "bob-account",
                gate_uid="202",
            ),
        },
    )

    calls: list[str] = []

    async def fake_balances(account_id: str):
        calls.append(account_id)

        return [
            {
                "currency": "USDT",
                "available": "5",
            }
        ]

    monkeypatch.setattr(
        treasury_api,
        "_gate_spot_available_balances",
        fake_balances,
    )

    request = (
        treasury_api.TreasuryUserTransferPreviewRequest(
            source_account_id="alice-account",
            destination_account_id="bob-account",
            currency="usdt",
            amount=Decimal("2"),
        )
    )

    result = await (
        treasury_api.preview_treasury_user_transfer(
            request,
            alice,
        )
    )

    assert calls == ["alice-account"]
    assert result["status"] == "ready"
    assert result["can_execute"] is False
    assert result["execution_implemented"] is True
    assert result["gate_write_required"] is True
    assert result["gate_write_performed"] is False
    assert result["required_confirmation"] == (
        "USER TRANSFER alice-account 2 USDT "
        "TO bob-account"
    )

    preview = result["preview"]

    assert preview["source_account_id"] == "alice-account"
    assert preview["destination_account_id"] == "bob-account"
    assert preview["currency"] == "USDT"
    assert preview["amount"] == "2"
    assert preview["source_available_before"] == "5"
    assert preview["source_available_after"] == "3"
    assert preview["transfer_path"] == (
        "subaccount_to_subaccount"
    )
    assert preview["operation_blockers"] == []


@pytest.mark.asyncio
async def test_preview_blocks_amount_over_available_balance(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )

    _install_registry(
        monkeypatch,
        users=(alice, bob),
        accounts={
            "alice-account": _account(
                "alice-account",
                gate_uid="101",
            ),
            "bob-account": _account(
                "bob-account",
                gate_uid="202",
            ),
        },
    )

    async def fake_balances(_account_id: str):
        return [
            {
                "currency": "USDT",
                "available": "5",
            }
        ]

    monkeypatch.setattr(
        treasury_api,
        "_gate_spot_available_balances",
        fake_balances,
    )

    request = (
        treasury_api.TreasuryUserTransferPreviewRequest(
            source_account_id="alice-account",
            destination_account_id="bob-account",
            currency="USDT",
            amount=Decimal("6"),
        )
    )

    result = await (
        treasury_api.preview_treasury_user_transfer(
            request,
            alice,
        )
    )

    assert result["status"] == "blocked"
    assert result["can_execute"] is False

    preview = result["preview"]

    assert preview["source_available_before"] == "5"
    assert preview["source_available_after"] == "5"

    assert preview["operation_blockers"] == [
        {
            "type": "insufficient_available_balance",
            "message": (
                "Requested 6 USDT, but only 5 is available"
            ),
        }
    ]


@pytest.mark.asyncio
async def test_preview_rejects_sender_owned_destination(
    monkeypatch,
):
    alice = _user(
        "alice",
        (
            "alice-primary",
            "alice-secondary",
        ),
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )

    _install_registry(
        monkeypatch,
        users=(alice, bob),
        accounts={
            "alice-primary": _account(
                "alice-primary",
                gate_uid="101",
            ),
            "alice-secondary": _account(
                "alice-secondary",
                gate_uid="102",
            ),
            "bob-account": _account(
                "bob-account",
                gate_uid="202",
            ),
        },
    )

    request = (
        treasury_api.TreasuryUserTransferPreviewRequest(
            source_account_id="alice-primary",
            destination_account_id="alice-secondary",
            currency="USDT",
            amount=Decimal("1"),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await treasury_api.preview_treasury_user_transfer(
            request,
            alice,
        )

    assert exc_info.value.status_code == 400
    assert "another enabled dashboard user" in str(
        exc_info.value.detail
    )


@pytest.mark.asyncio
async def test_execute_disabled_never_dispatches(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )

    _install_registry(
        monkeypatch,
        users=(alice, bob),
        accounts={
            "alice-account": _account(
                "alice-account",
                gate_uid="101",
            ),
            "bob-account": _account(
                "bob-account",
                gate_uid="202",
            ),
        },
        enabled=False,
    )

    monkeypatch.setattr(
        treasury_api,
        "find_matching_transfer_request",
        lambda **_kwargs: None,
    )

    dispatched = False

    async def forbidden_executor(**_kwargs):
        nonlocal dispatched
        dispatched = True
        raise AssertionError(
            "Disabled route reached executor"
        )

    monkeypatch.setattr(
        treasury_api,
        "execute_user_account_transfer",
        forbidden_executor,
    )

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id="user-transfer-test-0001",
            source_account_id="alice-account",
            destination_account_id="bob-account",
            currency="USDT",
            amount=Decimal("1"),
            confirmation=(
                "USER TRANSFER alice-account "
                "1 USDT TO bob-account"
            ),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await treasury_api.execute_treasury_user_transfer(
            request,
            alice,
        )

    assert exc_info.value.status_code == 403

    detail = exc_info.value.detail

    assert detail["reason"] == (
        "user_transfers_not_enabled"
    )
    assert detail["gate_write_performed"] is False
    assert dispatched is False


@pytest.mark.asyncio
async def test_execute_rejects_forged_source(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )

    _install_registry(
        monkeypatch,
        users=(alice, bob),
        accounts={
            "alice-account": _account(
                "alice-account",
                gate_uid="101",
            ),
            "bob-account": _account(
                "bob-account",
                gate_uid="202",
            ),
        },
        enabled=True,
    )

    request = (
        treasury_api.TreasuryUserTransferExecutionRequest(
            request_id="user-transfer-test-0002",
            source_account_id="bob-account",
            destination_account_id="alice-account",
            currency="USDT",
            amount=Decimal("1"),
            confirmation="FORGED",
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await treasury_api.execute_treasury_user_transfer(
            request,
            alice,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_gate_balance_reader_filters_and_sorts(
    monkeypatch,
):
    account = _account(
        "alice-account",
        gate_uid="101",
    )

    monkeypatch.setattr(
        treasury_api,
        "get_gate_account",
        lambda _account_id: account,
    )

    class FakeGateClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(
            self,
            _exc_type,
            _exc,
            _tb,
        ):
            return False

        async def list_spot_accounts(self):
            return SimpleNamespace(
                data=[
                    {
                        "currency": "USDT",
                        "available": "5.5000",
                    },
                    {
                        "currency": "BTC",
                        "available": "0",
                    },
                    {
                        "currency": "ETH",
                        "available": "-1",
                    },
                    {
                        "currency": "SOL",
                        "available": "invalid",
                    },
                    {
                        "currency": "ADA",
                        "available": "2",
                    },
                    None,
                ]
            )

    monkeypatch.setattr(
        treasury_api,
        "GateClient",
        FakeGateClient,
    )

    result = await (
        treasury_api._gate_spot_available_balances(
            "alice-account"
        )
    )

    assert result == [
        {
            "currency": "ADA",
            "available": "2",
        },
        {
            "currency": "USDT",
            "available": "5.5000",
        },
    ]


def test_transfer_path_classifies_supported_pairs(
    monkeypatch,
):
    accounts = {
        "main": _account(
            "main",
            account_type="main",
            gate_uid="900",
        ),
        "sub-a": _account(
            "sub-a",
            gate_uid="101",
        ),
        "sub-b": _account(
            "sub-b",
            gate_uid="202",
        ),
    }

    monkeypatch.setattr(
        treasury_api,
        "get_gate_account",
        lambda account_id: accounts.get(account_id),
    )

    assert treasury_api._user_transfer_path(
        source_account_id="sub-a",
        destination_account_id="sub-b",
    )["kind"] == "subaccount_to_subaccount"

    assert treasury_api._user_transfer_path(
        source_account_id="main",
        destination_account_id="sub-a",
    )["kind"] == "main_to_subaccount"

    assert treasury_api._user_transfer_path(
        source_account_id="sub-a",
        destination_account_id="main",
    )["kind"] == "subaccount_to_main"


def test_transfer_path_requires_subaccount_gate_uid(
    monkeypatch,
):
    accounts = {
        "sub-a": _account(
            "sub-a",
            gate_uid="",
        ),
        "sub-b": _account(
            "sub-b",
            gate_uid="202",
        ),
    }

    monkeypatch.setattr(
        treasury_api,
        "get_gate_account",
        lambda account_id: accounts.get(account_id),
    )

    with pytest.raises(HTTPException) as exc_info:
        treasury_api._user_transfer_path(
            source_account_id="sub-a",
            destination_account_id="sub-b",
        )

    assert exc_info.value.status_code == 503
    assert "Gate UID" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_execute_enabled_dispatches_treasury_write_path(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )
    bob = _user(
        "bob",
        ("bob-account",),
    )

    source = _account(
        "alice-account",
        gate_uid="101",
    )
    destination = _account(
        "bob-account",
        gate_uid="202",
    )
    treasury = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    _install_registry(
        monkeypatch,
        users=(alice, bob),
        accounts={
            "alice-account": source,
            "bob-account": destination,
        },
        enabled=True,
    )

    monkeypatch.setattr(
        treasury_api,
        "find_matching_transfer_request",
        lambda **_kwargs: None,
    )

    monkeypatch.setattr(
        treasury_api,
        "_treasury_account_or_http",
        lambda: treasury,
    )

    rate_calls = []

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        lambda **kwargs: rate_calls.append(
            kwargs
        ),
    )

    captured = {}

    async def fake_executor(**kwargs):
        captured.update(kwargs)

        return {
            "phase": "USER_ACCOUNT_TRANSFER",
            "status": "success",
            "gate_write_performed": True,
        }

    monkeypatch.setattr(
        treasury_api,
        "execute_user_account_transfer",
        fake_executor,
    )

    request = (
        treasury_api
        .TreasuryUserTransferExecutionRequest(
            request_id="user-transfer-test-1001",
            source_account_id="alice-account",
            destination_account_id="bob-account",
            currency="USDT",
            amount=Decimal("1"),
            confirmation=(
                "USER TRANSFER alice-account "
                "1 USDT TO bob-account"
            ),
        )
    )

    result = await (
        treasury_api.execute_treasury_user_transfer(
            request,
            alice,
        )
    )

    assert result["status"] == "success"

    assert captured["source_account"] is source
    assert (
        captured["destination_account"]
        is destination
    )
    assert captured["treasury_account"] is treasury

    assert captured["transfer_path"] == (
        "subaccount_to_subaccount"
    )

    assert (
        "client_order_id"
        not in captured["gate_payload"]
    )

    assert captured["audit_payload"]["operation"] == (
        "user_account_transfer"
    )

    assert rate_calls == [
        {
            "user": alice,
            "source_account_id": (
                "alice-account"
            ),
            "action": "user_transfer",
        }
    ]


@pytest.mark.asyncio
async def test_reconcile_uses_strict_source_scope(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )

    monkeypatch.setattr(
        treasury_api,
        "get_transfer_request",
        lambda _request_id: {
            "request_id": "user-reconcile-1",
            "source_account_id": "bob-account",
            "destination_account_id": (
                "alice-account"
            ),
            "username": "bob",
            "direction": (
                "user_account_transfer"
            ),
            "currency": "USDT",
            "status": "uncertain",
            "request": {
                "operation": (
                    "user_account_transfer"
                ),
                "transfer_path": (
                    "subaccount_to_subaccount"
                ),
            },
            "write_performed": True,
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        await (
            treasury_api
            .reconcile_treasury_user_transfer(
                "user-reconcile-1",
                alice,
            )
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_reconcile_allowed_while_live_arm_disabled(
    monkeypatch,
):
    alice = _user(
        "alice",
        ("alice-account",),
    )

    monkeypatch.setattr(
        treasury_api,
        "settings",
        Settings(
            _env_file=None,
            treasury_user_transfers_enabled=False,
            treasury_rate_limit_enabled=False,
        ),
    )

    record = {
        "request_id": "user-reconcile-2",
        "source_account_id": "alice-account",
        "destination_account_id": "bob-account",
        "username": "alice",
        "direction": "user_account_transfer",
        "currency": "USDT",
        "status": "uncertain",
        "request": {
            "operation": "user_account_transfer",
            "transfer_path": (
                "subaccount_to_subaccount"
            ),
        },
        "write_performed": True,
    }

    monkeypatch.setattr(
        treasury_api,
        "get_transfer_request",
        lambda _request_id: record,
    )

    treasury = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    monkeypatch.setattr(
        treasury_api,
        "_treasury_account_or_http",
        lambda: treasury,
    )

    monkeypatch.setattr(
        treasury_api,
        "_enforce_treasury_rate_limit",
        lambda **_kwargs: None,
    )

    called = False

    async def fake_reconcile(**kwargs):
        nonlocal called
        called = True

        assert kwargs["record"] is record
        assert kwargs["treasury_account"] is treasury

        return {
            "status": "uncertain",
            "gate_read_performed": False,
            "lock_released": False,
            "manual_review_required": True,
            "audit": record,
            "reconciliation": {},
        }

    monkeypatch.setattr(
        treasury_api,
        "reconcile_user_account_transfer",
        fake_reconcile,
    )

    result = await (
        treasury_api
        .reconcile_treasury_user_transfer(
            "user-reconcile-2",
            alice,
        )
    )

    assert called is True
    assert result["status"] == "uncertain"
    assert result["gate_write_performed"] is False
