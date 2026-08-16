from __future__ import annotations

import inspect
from decimal import Decimal
from uuid import uuid4

import pytest

import app.treasury_withdrawal_submission as submission
from app.accounts import GateAccountConfig
from app.config import Settings
from app.db import init_db
from app.gate_client import GateResponse
from app.treasury_withdrawal_audit import (
    begin_withdrawal_submission,
    get_withdrawal_request,
    record_withdrawal_simulation,
    transition_withdrawal_request,
)
from app.treasury_withdrawal_execution import (
    gate_withdraw_order_id,
)
from app.treasury_withdrawal_locks import (
    acquire_withdrawal_lock,
    get_withdrawal_lock_for_request,
    release_withdrawal_lock,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_withdrawal_submission_test_database():
    # This test module must work when run alone.
    # Do not depend on another test module or the
    # FastAPI lifespan to initialize SQLite.
    init_db()


def treasury_account() -> GateAccountConfig:
    return GateAccountConfig(
        id="zolnode",
        name="Treasury",
        api_key="treasury-test-key",
        api_secret="treasury-test-secret",
        enabled=True,
        account_type="main",
        gate_uid="13079163",
    )


def live_settings() -> Settings:
    return Settings(
        _env_file=None,
        treasury_main_account="zolnode",
        treasury_withdrawals_live_armed=True,
        treasury_withdrawals_live_accounts=(
            "arnold"
        ),
    )


@pytest.fixture
def withdrawal_request():
    request_id = (
        "wd-5b-" + uuid4().hex
    )

    payload = {
        "owner_account_id": "arnold",
        "destination_id": (
            "wd_test_destination"
        ),
        "currency": "USDT",
        "chain": "ARBEVM",
        "amount": "1",
    }

    record_withdrawal_simulation(
        request_id=request_id,
        owner_account_id="arnold",
        custody_account_id="zolnode",
        username="arnold",
        destination_id=(
            "wd_test_destination"
        ),
        currency="USDT",
        chain="ARBEVM",
        address=(
            "0x111111111111111111111111"
            "1111111111111111"
        ),
        memo="",
        amount=Decimal("1"),
        estimated_fee=Decimal("0.05"),
        conservative_funding_required=(
            Decimal("1.05")
        ),
        minimum_jit_transfer=(
            Decimal("0")
        ),
        jit_required=False,
        payload=payload,
        preflight={
            "preflight_valid": True,
        },
        destination_snapshot={
            "destination_id": (
                "wd_test_destination"
            ),
        },
    )

    transition_withdrawal_request(
        request_id,
        expected_statuses={"simulated"},
        new_status="jit_ready",
        username="arnold",
        action="test_jit_ready",
        details={},
        simulation=False,
        completed=False,
    )

    acquire_withdrawal_lock(
        owner_account_id="arnold",
        custody_account_id="zolnode",
        currency="USDT",
        owner_request_id=request_id,
        username="arnold",
    )

    try:
        yield request_id

    finally:
        release_withdrawal_lock(
            custody_account_id="zolnode",
            currency="USDT",
            owner_request_id=request_id,
        )


def install_fake(
    monkeypatch,
    *,
    post_data=None,
    post_error=None,
    get_data=None,
    on_post=None,
):
    calls = {
        "post": 0,
        "get": 0,
    }

    class FakeGateClient:
        def __init__(
            self,
            settings,
            account,
        ):
            self.settings = settings
            self.account = account

        async def __aenter__(self):
            return self

        async def __aexit__(
            self,
            exc_type,
            exc,
            tb,
        ):
            return None

        async def create_withdrawal(
            self,
            payload,
        ):
            calls["post"] += 1

            if on_post:
                on_post(payload)

            if post_error:
                raise post_error

            return GateResponse(
                data=post_data or {},
                status_code=200,
                headers={},
                raw=post_data or {},
            )

        async def list_withdrawals(
            self,
            **kwargs,
        ):
            calls["get"] += 1

            return GateResponse(
                data=(
                    get_data
                    if get_data is not None
                    else []
                ),
                status_code=200,
                headers={},
                raw=(
                    get_data
                    if get_data is not None
                    else []
                ),
            )

    monkeypatch.setattr(
        submission,
        "GateClient",
        FakeGateClient,
    )

    return calls


@pytest.mark.asyncio
async def test_submission_persists_order_before_post(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request

    def on_post(payload):
        row = get_withdrawal_request(
            request_id
        )

        assert row is not None
        assert (
            row["status"]
            == "withdrawal_submitting"
        )

        assert (
            row["gate_withdraw_order_id"]
            == payload["withdraw_order_id"]
        )

        assert (
            row["write_performed"]
            is False
        )

    calls = install_fake(
        monkeypatch,
        post_data={
            "id": "w123",
            "withdraw_order_id": (
                gate_withdraw_order_id(
                    request_id
                )
            ),
            "status": "REQUEST",
        },
        on_post=on_post,
    )

    result = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1
    assert (
        result["status"]
        == "withdrawal_submitted"
    )

    row = get_withdrawal_request(
        request_id
    )

    assert row["write_performed"] is True
    assert row["gate_withdrawal_id"] == "w123"


@pytest.mark.asyncio
async def test_submitted_request_never_posts_twice(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request

    calls = install_fake(
        monkeypatch,
        post_data={
            "id": "w124",
            "withdraw_order_id": (
                gate_withdraw_order_id(
                    request_id
                )
            ),
            "status": "REQUEST",
        },
    )

    await submission.submit_withdrawal_once(
        settings=live_settings(),
        request_id=request_id,
        username="arnold",
        treasury_account=treasury_account(),
    )

    replay = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1
    assert replay["idempotent_replay"] is True
    assert (
        replay["gate_write_performed"]
        is False
    )


@pytest.mark.asyncio
async def test_uncertain_post_is_never_retried(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request

    calls = install_fake(
        monkeypatch,
        post_error=TimeoutError(
            "simulated timeout"
        ),
    )

    first = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert (
        first["status"]
        == "withdrawal_reconciling"
    )
    assert calls["post"] == 1

    second = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1
    assert second["idempotent_replay"] is True


@pytest.mark.asyncio
async def test_crash_window_submitting_state_never_posts(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request

    order_id = gate_withdraw_order_id(
        request_id
    )

    begin_withdrawal_submission(
        request_id,
        username="arnold",
        gate_withdraw_order_id=order_id,
    )

    calls = install_fake(
        monkeypatch,
    )

    result = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 0
    assert result["requires_reconciliation"] is True


@pytest.mark.asyncio
async def test_pending_reconciliation_keeps_lock(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request

    order_id = gate_withdraw_order_id(
        request_id
    )

    begin_withdrawal_submission(
        request_id,
        username="arnold",
        gate_withdraw_order_id=order_id,
    )

    calls = install_fake(
        monkeypatch,
        get_data=[[
            {
                "id": "w200",
                "withdraw_order_id": order_id,
                "currency": "USDT",
                "amount": "1",
                "address": (
                    "0x111111111111111111111111"
                    "1111111111111111"
                ),
                "memo": "",
                "chain": "ARBEVM",
                "status": "REQUEST",
                "block_number": "0",
            }
        ]],
    )

    result = (
        await submission.reconcile_withdrawal(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 0
    assert calls["get"] == 1
    assert (
        result["status"]
        == "withdrawal_reconciling"
    )

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is not None
    )


@pytest.mark.asyncio
async def test_done_without_block_remains_reconciling(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request
    order_id = gate_withdraw_order_id(
        request_id
    )

    begin_withdrawal_submission(
        request_id,
        username="arnold",
        gate_withdraw_order_id=order_id,
    )

    install_fake(
        monkeypatch,
        get_data=[[
            {
                "id": "w201",
                "withdraw_order_id": order_id,
                "currency": "USDT",
                "amount": "1",
                "address": (
                    "0x111111111111111111111111"
                    "1111111111111111"
                ),
                "memo": "",
                "chain": "ARBEVM",
                "status": "DONE",
                "block_number": "0",
            }
        ]],
    )

    result = (
        await submission.reconcile_withdrawal(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert (
        result["status"]
        == "withdrawal_reconciling"
    )


@pytest.mark.asyncio
async def test_done_with_block_stops_at_unsettled(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request
    order_id = gate_withdraw_order_id(
        request_id
    )

    begin_withdrawal_submission(
        request_id,
        username="arnold",
        gate_withdraw_order_id=order_id,
    )

    install_fake(
        monkeypatch,
        get_data=[[
            {
                "id": "w202",
                "withdraw_order_id": order_id,
                "currency": "USDT",
                "amount": "1",
                "fee": "0.05",
                "address": (
                    "0x111111111111111111111111"
                    "1111111111111111"
                ),
                "memo": "",
                "chain": "ARBEVM",
                "status": "DONE",
                "txid": "0xabc",
                "block_number": "123",
            }
        ]],
    )

    result = (
        await submission.reconcile_withdrawal(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert (
        result["status"]
        == "withdrawal_done_unsettled"
    )

    assert result["definitive_success"] is True

    # Settlement is deliberately NOT T2C.5B.
    assert (
        result[
            "ownership_settlement_performed"
        ]
        is False
    )

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is not None
    )


@pytest.mark.asyncio
async def test_reject_releases_lock_without_settlement(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request
    order_id = gate_withdraw_order_id(
        request_id
    )

    begin_withdrawal_submission(
        request_id,
        username="arnold",
        gate_withdraw_order_id=order_id,
    )

    install_fake(
        monkeypatch,
        get_data=[[
            {
                "id": "w203",
                "withdraw_order_id": order_id,
                "currency": "USDT",
                "amount": "1",
                "address": (
                    "0x111111111111111111111111"
                    "1111111111111111"
                ),
                "memo": "",
                "chain": "ARBEVM",
                "status": "REJECT",
                "block_number": "0",
                "fail_reason": "test rejection",
            }
        ]],
    )

    result = (
        await submission.reconcile_withdrawal(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert (
        result["status"]
        == "withdrawal_failed"
    )

    assert (
        result[
            "ownership_settlement_performed"
        ]
        is False
    )

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is None
    )


@pytest.mark.asyncio
async def test_record_mismatch_fails_closed(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request
    order_id = gate_withdraw_order_id(
        request_id
    )

    begin_withdrawal_submission(
        request_id,
        username="arnold",
        gate_withdraw_order_id=order_id,
    )

    install_fake(
        monkeypatch,
        get_data=[[
            {
                "id": "w204",
                "withdraw_order_id": order_id,
                "currency": "USDT",
                "amount": "99",
                "address": (
                    "0x111111111111111111111111"
                    "1111111111111111"
                ),
                "memo": "",
                "chain": "ARBEVM",
                "status": "DONE",
                "block_number": "123",
            }
        ]],
    )

    result = (
        await submission.reconcile_withdrawal(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert (
        result["status"]
        == "withdrawal_reconciling"
    )

    assert "amount" in (
        result["record_mismatches"]
    )

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is not None
    )


def test_reconciliation_source_has_no_gate_write():
    source = inspect.getsource(
        submission.reconcile_withdrawal
    )

    assert "create_withdrawal(" not in source
    assert "list_withdrawals(" in source


@pytest.mark.asyncio
async def test_explicit_gate_4xx_is_definitive_rejection(
    monkeypatch,
    withdrawal_request,
):
    from app.gate_client import GateAPIError

    request_id = withdrawal_request

    calls = install_fake(
        monkeypatch,
        post_error=GateAPIError(
            "Gate API returned 403: forbidden",
            status_code=403,
            label="FORBIDDEN",
            response={
                "label": "FORBIDDEN",
                "message": (
                    "Account has no permission "
                    "to request operation"
                ),
            },
        ),
    )

    result = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1

    assert (
        result["status"]
        == "withdrawal_failed"
    )

    assert (
        result["gate_write_accepted"]
        is False
    )

    assert (
        result["requires_reconciliation"]
        is False
    )

    assert (
        result["automatic_retry_allowed"]
        is False
    )

    assert (
        result["definitive_rejection"]
        is True
    )

    evidence = result[
        "submission_error"
    ]

    assert (
        evidence["classification"]
        == "explicit_gate_rejection"
    )

    assert evidence["http_status"] == 403
    assert evidence["gate_label"] == "FORBIDDEN"

    row = get_withdrawal_request(
        request_id
    )

    assert row is not None

    assert (
        row["status"]
        == "withdrawal_failed"
    )

    assert row["write_performed"] is True
    assert row["error"]

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is None
    )

    assert result["lock_released"] is True

    assert (
        result["event"]["action"]
        == "withdrawal_submission_rejected"
    )


@pytest.mark.asyncio
async def test_order_exists_remains_ambiguous_and_locked(
    monkeypatch,
    withdrawal_request,
):
    from app.gate_client import GateAPIError

    request_id = withdrawal_request

    calls = install_fake(
        monkeypatch,
        post_error=GateAPIError(
            "Gate API returned 400: order exists",
            status_code=400,
            label="ORDER_EXISTS",
            response={
                "label": "ORDER_EXISTS",
                "message": (
                    "Order already exists, "
                    "do not resubmit"
                ),
            },
        ),
    )

    first = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1

    assert (
        first["status"]
        == "withdrawal_reconciling"
    )

    assert (
        first["gate_write_accepted"]
        is None
    )

    assert (
        first["requires_reconciliation"]
        is True
    )

    assert (
        first["definitive_rejection"]
        is False
    )

    evidence = first[
        "submission_error"
    ]

    assert (
        evidence["classification"]
        == "duplicate_or_existing_request"
    )

    assert (
        evidence["duplicate_or_existing"]
        is True
    )

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is not None
    )

    # Replay must never POST a second time.
    second = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1

    assert (
        second["idempotent_replay"]
        is True
    )


@pytest.mark.asyncio
async def test_gate_5xx_remains_uncertain_and_locked(
    monkeypatch,
    withdrawal_request,
):
    from app.gate_client import GateAPIError

    request_id = withdrawal_request

    calls = install_fake(
        monkeypatch,
        post_error=GateAPIError(
            (
                "Gate API returned 500: "
                "internal error"
            ),
            status_code=500,
            label="INTERNAL_SERVER_ERROR",
            response={
                "label": (
                    "INTERNAL_SERVER_ERROR"
                ),
                "message": (
                    "Operation failed"
                ),
            },
        ),
    )

    result = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1

    assert (
        result["status"]
        == "withdrawal_reconciling"
    )

    assert (
        result["requires_reconciliation"]
        is True
    )

    assert (
        result["definitive_rejection"]
        is False
    )

    evidence = result[
        "submission_error"
    ]

    assert (
        evidence["classification"]
        == "gate_server_or_http_error"
    )

    assert evidence["http_status"] == 500

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is not None
    )


@pytest.mark.asyncio
async def test_transport_error_preserves_nonempty_evidence(
    monkeypatch,
    withdrawal_request,
):
    request_id = withdrawal_request

    calls = install_fake(
        monkeypatch,
        post_error=TimeoutError(
            "simulated transport timeout"
        ),
    )

    result = (
        await submission.submit_withdrawal_once(
            settings=live_settings(),
            request_id=request_id,
            username="arnold",
            treasury_account=(
                treasury_account()
            ),
        )
    )

    assert calls["post"] == 1

    assert (
        result["status"]
        == "withdrawal_reconciling"
    )

    evidence = result[
        "submission_error"
    ]

    assert (
        evidence["classification"]
        == "transport_or_unknown_error"
    )

    assert evidence["http_status"] is None

    assert (
        evidence["exception_type"]
        == "TimeoutError"
    )

    assert "simulated transport timeout" in (
        evidence["error"]
    )

    assert (
        result["requires_reconciliation"]
        is True
    )

    assert (
        get_withdrawal_lock_for_request(
            request_id
        )
        is not None
    )
