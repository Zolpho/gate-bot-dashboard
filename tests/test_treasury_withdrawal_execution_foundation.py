from __future__ import annotations

import re

import pytest

from app.config import Settings
from app.gate_client import (
    GateClient,
    GateResponse,
)
from app.treasury_withdrawal_execution import (
    TreasuryWithdrawalExecutionError,
    build_gate_withdrawal_payload,
    classify_withdrawal_status,
    gate_withdraw_order_id,
    select_withdrawal_record,
    withdrawal_execution_confirmation_text,
)


def _request():
    return {
        "request_id": (
            "wd-foundation-"
            "0123456789abcdef"
        ),
        "owner_account_id": "arnold",
        "custody_account_id": "zolnode",
        "destination_id": (
            "wd_2df3805db5464fdea59ba7c9b840d687"
        ),
        "currency": "USDT",
        "chain": "ARBEVM",
        "address": (
            "0x4d784e00000000000000000000000000"
            "00b61fb6"
        ),
        "memo": "",
        "amount": "1.00000000",
    }


def test_gate_withdraw_order_id_is_deterministic_and_valid():
    first = gate_withdraw_order_id(
        _request()["request_id"]
    )

    second = gate_withdraw_order_id(
        _request()["request_id"]
    )

    assert first == second
    assert len(first) == 32

    assert re.fullmatch(
        r"[0-9A-Za-z_.-]{1,32}",
        first,
    )


def test_gate_withdrawal_payload_uses_immutable_snapshot():
    request = _request()

    payload = build_gate_withdrawal_payload(
        request
    )

    assert payload == {
        "withdraw_order_id": (
            gate_withdraw_order_id(
                request["request_id"]
            )
        ),
        "currency": "USDT",
        "address": request["address"],
        "amount": "1",
        "memo": "",
        "chain": "ARBEVM",
    }


def test_execution_confirmation_binds_owner_amount_chain_and_destination():
    request = _request()

    confirmation = (
        withdrawal_execution_confirmation_text(
            request
        )
    )

    assert confirmation.startswith(
        "LIVE WITHDRAWAL "
        "arnold USDT 1 ARBEVM TO "
    )

    assert request["destination_id"] in confirmation
    assert len(confirmation) <= 255


def test_done_is_definitive_success():
    decision = classify_withdrawal_status(
        "DONE"
    )

    assert decision.request_status == (
        "withdrawal_done"
    )
    assert decision.outcome == "success"
    assert decision.confidence == "definitive"
    assert decision.terminal is True
    assert decision.success is True

    assert (
        decision.requires_reconciliation
        is False
    )


@pytest.mark.parametrize(
    "status",
    [
        "CANCEL",
        "REJECT",
    ],
)
def test_definitive_negative_statuses(
    status,
):
    decision = classify_withdrawal_status(
        status
    )

    assert decision.request_status == (
        "withdrawal_failed"
    )
    assert decision.outcome == "failed"
    assert decision.confidence == "definitive"
    assert decision.terminal is True
    assert decision.success is False

    assert (
        decision.requires_reconciliation
        is False
    )


def test_fail_is_deliberately_not_terminal():
    decision = classify_withdrawal_status(
        "FAIL"
    )

    assert decision.request_status == (
        "withdrawal_reconciling"
    )
    assert decision.outcome == "pending"
    assert decision.terminal is False

    assert (
        decision.requires_reconciliation
        is True
    )


@pytest.mark.parametrize(
    "status",
    [
        "REQUEST",
        "EXTPEND",
        "REVIEW",
        "SOMETHING_NEW",
    ],
)
def test_nondefinitive_and_unknown_statuses_keep_reconciling(
    status,
):
    decision = classify_withdrawal_status(
        status
    )

    assert decision.request_status == (
        "withdrawal_reconciling"
    )

    assert decision.terminal is False

    assert (
        decision.requires_reconciliation
        is True
    )


def test_select_withdrawal_record_matches_exact_order_id():
    order_id = gate_withdraw_order_id(
        _request()["request_id"]
    )

    result = select_withdrawal_record(
        [
            [
                {
                    "id": "w1",
                    "withdraw_order_id": "other",
                    "status": "DONE",
                    "currency": "USDT",
                },
                {
                    "id": "w2",
                    "withdraw_order_id": order_id,
                    "status": "REQUEST",
                    "currency": "USDT",
                },
            ]
        ],
        withdraw_order_id=order_id,
    )

    assert result is not None
    assert result["id"] == "w2"


def test_select_withdrawal_record_rejects_duplicate_matches():
    order_id = gate_withdraw_order_id(
        _request()["request_id"]
    )

    with pytest.raises(
        TreasuryWithdrawalExecutionError
    ):
        select_withdrawal_record(
            [
                {
                    "id": "w1",
                    "withdraw_order_id": order_id,
                    "status": "REQUEST",
                    "currency": "USDT",
                },
                {
                    "id": "w2",
                    "withdraw_order_id": order_id,
                    "status": "DONE",
                    "currency": "USDT",
                },
            ],
            withdraw_order_id=order_id,
        )


@pytest.mark.asyncio
async def test_gate_client_uses_exact_withdrawal_endpoints(
    monkeypatch,
):
    settings = Settings(
        _env_file=None,
    )

    client = GateClient(settings)

    calls = []

    async def fake_request(
        method,
        endpoint,
        **kwargs,
    ):
        calls.append(
            (
                method,
                endpoint,
                kwargs,
            )
        )

        return GateResponse(
            data=[],
            status_code=200,
            headers={},
            raw=[],
        )

    monkeypatch.setattr(
        client,
        "request",
        fake_request,
    )

    try:
        payload = build_gate_withdrawal_payload(
            _request()
        )

        await client.create_withdrawal(
            payload
        )

        await client.list_withdrawals(
            currency="USDT",
            withdraw_order_id=(
                payload[
                    "withdraw_order_id"
                ]
            ),
        )

    finally:
        await client.close()

    assert calls[0][0:2] == (
        "POST",
        "/withdrawals",
    )

    assert (
        calls[0][2]["json_body"]
        == payload
    )

    assert calls[1][0:2] == (
        "GET",
        "/wallet/withdrawals",
    )

    params = dict(
        calls[1][2]["params"]
    )

    assert (
        params["withdraw_order_id"]
        == payload["withdraw_order_id"]
    )

    assert params["currency"] == "USDT"


def test_withdrawal_live_arm_is_independent_and_fail_closed():
    settings = Settings(
        _env_file=None,
        treasury_transfers_live_armed=True,
        treasury_transfers_live_accounts=(
            "arnold"
        ),
        treasury_withdrawals_live_armed=False,
        treasury_withdrawals_live_accounts="",
    )

    # Internal transfers being live must have no effect
    # on external withdrawal permission.
    assert (
        settings.treasury_transfers_live_armed
        is True
    )

    assert (
        settings
        .treasury_transfers_live_account_allowed(
            "arnold"
        )
        is True
    )

    assert (
        settings.treasury_withdrawals_live_armed
        is False
    )

    assert (
        settings
        .treasury_withdrawals_live_account_allowed(
            "arnold"
        )
        is False
    )
