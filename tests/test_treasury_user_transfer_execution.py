from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import treasury_user_transfer_execution as execution
from app.accounts import GateAccountConfig
from app.config import Settings
from app.gate_client import GateAPIError
from app.treasury_transfer import (
    TreasuryTransferValidationError,
    gate_client_order_id,
)


def _account(
    account_id: str,
    *,
    account_type: str,
    gate_uid: str,
) -> GateAccountConfig:
    return GateAccountConfig(
        id=account_id,
        name=account_id,
        api_key=f"{account_id}-key",
        api_secret=f"{account_id}-secret",
        enabled=True,
        account_type=account_type,
        gate_uid=gate_uid,
    )


def _settings(
    *,
    enabled: bool = True,
) -> Settings:
    return Settings(
        _env_file=None,
        treasury_user_transfers_enabled=enabled,
    )


def test_build_main_to_sub_payload():
    main = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )
    sub = _account(
        "sub",
        account_type="subaccount",
        gate_uid="101",
    )

    result = execution.build_user_gate_transfer(
        source_account=main,
        destination_account=sub,
        currency="usdt",
        amount=Decimal("1.25"),
        request_id="user-transfer-main-sub",
    )

    assert result["path"] == execution.MAIN_TO_SUB
    assert result["client_order_id_sent"] is True

    assert result["payload"] == {
        "sub_account": "101",
        "sub_account_type": "spot",
        "currency": "USDT",
        "amount": "1.25",
        "direction": "to",
        "client_order_id": gate_client_order_id(
            "user-transfer-main-sub"
        ),
    }


def test_build_sub_to_main_payload():
    sub = _account(
        "sub",
        account_type="subaccount",
        gate_uid="101",
    )
    main = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    result = execution.build_user_gate_transfer(
        source_account=sub,
        destination_account=main,
        currency="BTC",
        amount=Decimal("0.01"),
        request_id="user-transfer-sub-main",
    )

    assert result["path"] == execution.SUB_TO_MAIN
    assert result["client_order_id_sent"] is True

    assert result["payload"]["sub_account"] == "101"
    assert result["payload"]["direction"] == "from"
    assert result["payload"]["currency"] == "BTC"
    assert result["payload"]["amount"] == "0.01"


def test_build_sub_to_sub_has_no_client_order_id():
    source = _account(
        "source",
        account_type="subaccount",
        gate_uid="101",
    )
    destination = _account(
        "destination",
        account_type="subaccount",
        gate_uid="202",
    )

    result = execution.build_user_gate_transfer(
        source_account=source,
        destination_account=destination,
        currency="USDT",
        amount=Decimal("5"),
        request_id="user-transfer-sub-sub",
    )

    assert result["path"] == execution.SUB_TO_SUB
    assert result["client_order_id_sent"] is False

    assert result["payload"] == {
        "currency": "USDT",
        "sub_account_from": "101",
        "sub_account_from_type": "spot",
        "sub_account_to": "202",
        "sub_account_to_type": "spot",
        "amount": "5",
    }

    assert (
        "client_order_id"
        not in result["payload"]
    )


def test_build_rejects_too_many_decimals():
    source = _account(
        "source",
        account_type="subaccount",
        gate_uid="101",
    )
    destination = _account(
        "destination",
        account_type="subaccount",
        gate_uid="202",
    )

    with pytest.raises(
        TreasuryTransferValidationError
    ):
        execution.build_user_gate_transfer(
            source_account=source,
            destination_account=destination,
            currency="USDT",
            amount=Decimal("1.123456789"),
            request_id="too-many-decimals",
        )


@pytest.mark.asyncio
async def test_disabled_executor_never_touches_gate(
    monkeypatch,
):
    source = _account(
        "source",
        account_type="subaccount",
        gate_uid="101",
    )
    destination = _account(
        "destination",
        account_type="subaccount",
        gate_uid="202",
    )
    treasury = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    touched = False

    class ForbiddenGateClient:
        def __init__(self, *_args, **_kwargs):
            nonlocal touched
            touched = True

    monkeypatch.setattr(
        execution,
        "GateClient",
        ForbiddenGateClient,
    )

    with pytest.raises(HTTPException) as exc_info:
        await execution.execute_user_account_transfer(
            settings=_settings(enabled=False),
            source_account=source,
            destination_account=destination,
            treasury_account=treasury,
            request_id="disabled-transfer-test",
            username="alice",
            currency="USDT",
            amount=Decimal("1"),
            transfer_path=execution.SUB_TO_SUB,
            audit_payload={},
            gate_payload={},
        )

    assert exc_info.value.status_code == 403
    assert touched is False


@pytest.mark.asyncio
async def test_sub_to_sub_write_uses_treasury_key(
    monkeypatch,
):
    source = _account(
        "source",
        account_type="subaccount",
        gate_uid="101",
    )
    destination = _account(
        "destination",
        account_type="subaccount",
        gate_uid="202",
    )
    treasury = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    request_id = "user-sub-sub-execution"

    audit_payload = {
        "operation": execution.USER_TRANSFER_OPERATION,
        "transfer_path": execution.SUB_TO_SUB,
    }

    state = {
        "request_id": request_id,
        "source_account_id": "source",
        "destination_account_id": "destination",
        "username": "alice",
        "currency": "USDT",
        "amount": "1",
        "status": "reserved",
        "request": audit_payload,
        "client_order_id": gate_client_order_id(
            request_id
        ),
        "gate_transfer_id": None,
        "write_performed": False,
    }

    monkeypatch.setattr(
        execution,
        "reserve_user_account_transfer",
        lambda **_kwargs: (dict(state), True),
    )

    monkeypatch.setattr(
        execution,
        "acquire_transfer_lock",
        lambda **_kwargs: {
            "lock_key": "test-lock"
        },
    )

    monkeypatch.setattr(
        execution,
        "release_transfer_lock",
        lambda **_kwargs: True,
    )

    def fake_mark(
        _request_id,
        *,
        status,
        response=None,
        gate_transfer_id="",
        write_performed=None,
        **_kwargs,
    ):
        state["status"] = status

        if response is not None:
            state["response"] = response

        if gate_transfer_id:
            state["gate_transfer_id"] = (
                gate_transfer_id
            )

        if write_performed is not None:
            state["write_performed"] = (
                write_performed
            )

        return dict(state)

    monkeypatch.setattr(
        execution,
        "mark_transfer_request",
        fake_mark,
    )

    async def fake_reconcile(**kwargs):
        record = kwargs["record"]

        assert (
            record["gate_transfer_id"]
            == "777"
        )

        return {
            "status": "success",
            "gate_read_performed": True,
            "lock_released": True,
            "audit": record,
            "reconciliation": {
                "outcome": "success"
            },
        }

    monkeypatch.setattr(
        execution,
        "reconcile_user_account_transfer",
        fake_reconcile,
    )

    calls = []

    class FakeGateClient:
        def __init__(self, _settings, account):
            self.account = account

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
            calls.append(
                ("read", self.account.id)
            )

            return SimpleNamespace(
                data=[
                    {
                        "currency": "USDT",
                        "available": "5",
                    }
                ],
                raw=[],
            )

        async def create_sub_account_to_sub_account_transfer(
            self,
            payload,
        ):
            calls.append(
                (
                    "sub_to_sub_write",
                    self.account.id,
                    payload,
                )
            )

            return SimpleNamespace(
                data={"tx_id": 777},
                raw={"tx_id": 777},
            )

        async def create_sub_account_transfer(
            self,
            _payload,
        ):
            raise AssertionError(
                "Wrong Gate endpoint"
            )

    monkeypatch.setattr(
        execution,
        "GateClient",
        FakeGateClient,
    )

    gate_request = (
        execution.build_user_gate_transfer(
            source_account=source,
            destination_account=destination,
            currency="USDT",
            amount=Decimal("1"),
            request_id=request_id,
        )
    )

    result = await (
        execution.execute_user_account_transfer(
            settings=_settings(),
            source_account=source,
            destination_account=destination,
            treasury_account=treasury,
            request_id=request_id,
            username="alice",
            currency="USDT",
            amount=Decimal("1"),
            transfer_path=(
                gate_request["path"]
            ),
            audit_payload=audit_payload,
            gate_payload=(
                gate_request["payload"]
            ),
        )
    )

    assert result["status"] == "success"

    assert calls[0] == (
        "read",
        "source",
    )

    assert calls[1][0] == "sub_to_sub_write"
    assert calls[1][1] == "main"

    # Fresh balance read uses source credentials.
    # The money-moving POST uses Treasury/main.
    assert calls[0][1] != calls[1][1]


@pytest.mark.asyncio
async def test_ambiguous_sub_to_sub_error_keeps_lock(
    monkeypatch,
):
    source = _account(
        "source",
        account_type="subaccount",
        gate_uid="101",
    )
    destination = _account(
        "destination",
        account_type="subaccount",
        gate_uid="202",
    )
    treasury = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    request_id = "ambiguous-sub-sub"

    audit_payload = {
        "operation": execution.USER_TRANSFER_OPERATION,
        "transfer_path": execution.SUB_TO_SUB,
    }

    state = {
        "request_id": request_id,
        "source_account_id": "source",
        "destination_account_id": "destination",
        "username": "alice",
        "currency": "USDT",
        "status": "reserved",
        "request": audit_payload,
        "client_order_id": gate_client_order_id(
            request_id
        ),
        "gate_transfer_id": None,
        "write_performed": False,
    }

    monkeypatch.setattr(
        execution,
        "reserve_user_account_transfer",
        lambda **_kwargs: (dict(state), True),
    )

    monkeypatch.setattr(
        execution,
        "acquire_transfer_lock",
        lambda **_kwargs: {
            "lock_key": "test-lock"
        },
    )

    releases = []

    monkeypatch.setattr(
        execution,
        "release_transfer_lock",
        lambda **kwargs: releases.append(
            kwargs
        ) or True,
    )

    def fake_mark(
        _request_id,
        *,
        status,
        write_performed=None,
        **_kwargs,
    ):
        state["status"] = status

        if write_performed is not None:
            state["write_performed"] = (
                write_performed
            )

        return dict(state)

    monkeypatch.setattr(
        execution,
        "mark_transfer_request",
        fake_mark,
    )

    class FakeGateClient:
        def __init__(self, _settings, account):
            self.account = account

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
                        "available": "5",
                    }
                ]
            )

        async def create_sub_account_to_sub_account_transfer(
            self,
            _payload,
        ):
            raise GateAPIError(
                "simulated transport timeout",
                status_code=None,
            )

    monkeypatch.setattr(
        execution,
        "GateClient",
        FakeGateClient,
    )

    with pytest.raises(HTTPException) as exc_info:
        await execution.execute_user_account_transfer(
            settings=_settings(),
            source_account=source,
            destination_account=destination,
            treasury_account=treasury,
            request_id=request_id,
            username="alice",
            currency="USDT",
            amount=Decimal("1"),
            transfer_path=execution.SUB_TO_SUB,
            audit_payload=audit_payload,
            gate_payload={
                "currency": "USDT",
            },
        )

    assert exc_info.value.status_code == 502

    detail = exc_info.value.detail

    assert detail["status"] == "uncertain"
    assert detail["gate_write_performed"] is True
    assert (
        detail["automatic_retry_allowed"]
        is False
    )

    # An ambiguous post-boundary outcome must
    # retain the source/currency lock.
    assert releases == []


@pytest.mark.asyncio
async def test_sub_to_sub_without_txid_cannot_auto_reconcile(
    monkeypatch,
):
    treasury = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    record = {
        "request_id": "missing-tx-id",
        "source_account_id": "source",
        "destination_account_id": "destination",
        "username": "alice",
        "currency": "USDT",
        "status": "uncertain",
        "request": {
            "operation": (
                execution.USER_TRANSFER_OPERATION
            ),
            "transfer_path": execution.SUB_TO_SUB,
        },
        "gate_transfer_id": None,
        "client_order_id": gate_client_order_id(
            "missing-tx-id"
        ),
        "write_performed": True,
    }

    gate_touched = False

    class ForbiddenGateClient:
        def __init__(self, *_args, **_kwargs):
            nonlocal gate_touched
            gate_touched = True

    monkeypatch.setattr(
        execution,
        "GateClient",
        ForbiddenGateClient,
    )

    monkeypatch.setattr(
        execution,
        "record_transfer_reconciliation",
        lambda **kwargs: kwargs,
    )

    monkeypatch.setattr(
        execution,
        "mark_transfer_request",
        lambda _request_id, **kwargs: {
            **record,
            "status": kwargs["status"],
        },
    )

    result = await (
        execution.reconcile_user_account_transfer(
            settings=_settings(),
            record=record,
            treasury_account=treasury,
        )
    )

    assert result["status"] == "uncertain"
    assert result["gate_read_performed"] is False
    assert result["lock_released"] is False
    assert result["manual_review_required"] is True
    assert gate_touched is False


@pytest.mark.asyncio
async def test_partial_success_keeps_lock(
    monkeypatch,
):
    treasury = _account(
        "main",
        account_type="main",
        gate_uid="900",
    )

    record = {
        "request_id": "partial-sub-sub",
        "source_account_id": "source",
        "destination_account_id": "destination",
        "username": "alice",
        "currency": "USDT",
        "status": "submitted",
        "request": {
            "operation": (
                execution.USER_TRANSFER_OPERATION
            ),
            "transfer_path": execution.SUB_TO_SUB,
        },
        "gate_transfer_id": "777",
        "client_order_id": "",
        "write_performed": True,
    }

    class FakeGateClient:
        def __init__(self, _settings, _account):
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

        async def get_transfer_order_status(
            self,
            **kwargs,
        ):
            assert kwargs == {
                "tx_id": "777"
            }

            return SimpleNamespace(
                data={
                    "tx_id": "777",
                    "status": "PARTIAL_SUCCESS",
                },
                raw={
                    "tx_id": "777",
                    "status": "PARTIAL_SUCCESS",
                },
            )

    monkeypatch.setattr(
        execution,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        execution,
        "record_transfer_reconciliation",
        lambda **kwargs: kwargs,
    )

    monkeypatch.setattr(
        execution,
        "mark_transfer_request",
        lambda _request_id, **kwargs: {
            **record,
            "status": kwargs["status"],
        },
    )

    releases = []

    monkeypatch.setattr(
        execution,
        "release_transfer_lock",
        lambda **kwargs: releases.append(
            kwargs
        ) or True,
    )

    result = await (
        execution.reconcile_user_account_transfer(
            settings=_settings(),
            record=record,
            treasury_account=treasury,
        )
    )

    assert result["status"] == "attention"
    assert result["lock_released"] is False
    assert result["manual_review_required"] is True
    assert releases == []
