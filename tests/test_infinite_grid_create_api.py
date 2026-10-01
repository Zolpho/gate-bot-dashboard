from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.bot_control as bc
from app.account_action_policy import (
    AccountActionPolicyDenied,
)
from app.bot_control_actions import (
    INFINITE_GRID_CREATE_ACTION,
)
from app.bot_control_locks import (
    OperationLocked,
)
from app.gate_client import (
    GateAPIError,
)
from app.security import DashboardUser


class FakeGateClient:
    create_calls: list[dict] = []
    failure: Exception | None = None

    def __init__(
        self,
        *_args,
        **_kwargs,
    ) -> None:
        pass

    async def __aenter__(
        self,
    ):
        return self

    async def __aexit__(
        self,
        *_args,
    ):
        return False

    async def create_infinite_grid(
        self,
        payload,
    ):
        self.__class__.create_calls.append(
            payload
        )

        if (
            self.__class__.failure
            is not None
        ):
            raise self.__class__.failure

        return SimpleNamespace(
            status_code=200,
            data={
                "strategy_id":
                    "FAKE-INFINITY-001",
                "strategy_type":
                    "infinite_grid",
                "market":
                    payload["market"],
                "status":
                    "running",
                "jump_url":
                    None,
            },
            raw={
                "test_double":
                    True,
                "network_request":
                    False,
            },
        )


def user() -> DashboardUser:
    return DashboardUser(
        username="zolnode",
        role="account_operator",
        account_ids=(
            "zolnode",
        ),
    )


def request(
    *,
    request_id:
        str = "infinity-create-001",
    confirmation:
        str = "LIVE CREATE",
    money:
        str = "100",
) -> bc.InfiniteGridCreateRequest:
    return bc.InfiniteGridCreateRequest(
        account_id="zolnode",
        market="EQTY_USDT",
        money=money,
        price_floor="0.0015",
        profit_per_grid="0.01",
        grid_num=10,
        price_type=1,
        confirmation=confirmation,
        request_id=request_id,
    )


@pytest.fixture
def route_env(
    monkeypatch,
):
    FakeGateClient.create_calls = []
    FakeGateClient.failure = None

    state = {
        "can_create": True,
        "available": "500",
        "existing": None,
        "marks": [],
        "rate_actions": [],
        "reserved_actions": [],
        "lock_calls": [],
        "released": [],
        "cooled": [],
    }

    monkeypatch.setattr(
        bc,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        bc.settings,
        "allow_infinite_grid_create",
        True,
    )

    monkeypatch.setattr(
        bc.settings,
        "allow_bot_create",
        True,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_create_simulation",
        False,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_armed",
        True,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_accounts",
        "*",
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_create_confirmation_text",
        "CREATE",
    )

    monkeypatch.setattr(
        bc.settings,
        (
            "bot_control_live_"
            "create_confirmation_text"
        ),
        "LIVE CREATE",
    )

    monkeypatch.setattr(
        bc,
        "find_matching_request",
        lambda **_kwargs: (
            state["existing"]
        ),
    )

    def fake_rate_limit(
        **kwargs,
    ):
        state[
            "rate_actions"
        ].append(
            kwargs["action"]
        )

    monkeypatch.setattr(
        bc,
        "_enforce_bot_control_rate_limit",
        fake_rate_limit,
    )

    async def fake_prepare(
        req,
        _user,
    ):
        payload = (
            bc.build_infinite_grid_payload(
                market=(
                    req.market
                    .strip()
                    .upper()
                ),
                money=req.money,
                price_floor=(
                    req.price_floor
                ),
                profit_per_grid=(
                    req.profit_per_grid
                ),
                grid_num=req.grid_num,
                price_type=req.price_type,
                trigger_price=(
                    req.trigger_price
                ),
                stop_profit=(
                    req.stop_profit
                ),
                stop_loss=(
                    req.stop_loss
                ),
            )
        )

        return {
            "status": (
                "ready"
                if state[
                    "can_create"
                ]
                else "invalid"
            ),
            "can_create":
                state["can_create"],
            "write_performed":
                False,
            "market": {
                "id":
                    "EQTY_USDT",
                "base":
                    "EQTY",
                "quote":
                    "USDT",
            },
            "balance": {
                "currency":
                    "USDT",
                "available":
                    state["available"],
            },
            "errors": (
                []
                if state[
                    "can_create"
                ]
                else [
                    "Synthetic Infinity "
                    "validation failure"
                ]
            ),
            "warnings": [],
            "gate_create_payload_preview":
                payload,
        }

    monkeypatch.setattr(
        bc,
        "prepare_infinite_grid",
        fake_prepare,
    )

    monkeypatch.setattr(
        bc,
        "get_bot_control_account",
        lambda _account_id: object(),
    )

    monkeypatch.setattr(
        bc,
        "require_account_action_allowed",
        lambda **_kwargs: None,
    )

    def fake_reserve(
        **kwargs,
    ):
        state[
            "reserved_actions"
        ].append(
            kwargs["action"]
        )

        return (
            {
                "request_id":
                    kwargs["request_id"],
                "status":
                    "reserved",
            },
            True,
        )

    monkeypatch.setattr(
        bc,
        "reserve_request",
        fake_reserve,
    )

    monkeypatch.setattr(
        bc,
        "create_intent_lock",
        lambda **_kwargs: (
            "create-intent:test",
            "fake-intent-hash",
        ),
    )

    def fake_acquire(
        **kwargs,
    ):
        state[
            "lock_calls"
        ].append(
            dict(kwargs)
        )

        return {
            **kwargs,
            "state": "held",
        }

    monkeypatch.setattr(
        bc,
        "acquire_operation_lock",
        fake_acquire,
    )

    def fake_mark(
        request_id,
        **kwargs,
    ):
        state["marks"].append(
            (
                request_id,
                dict(kwargs),
            )
        )

        return {}

    monkeypatch.setattr(
        bc,
        "mark_request",
        fake_mark,
    )

    def fake_release(
        **kwargs,
    ):
        state[
            "released"
        ].append(
            dict(kwargs)
        )

        return True

    monkeypatch.setattr(
        bc,
        "release_operation_lock",
        fake_release,
    )

    def fake_cooldown(
        **kwargs,
    ):
        state[
            "cooled"
        ].append(
            dict(kwargs)
        )

    monkeypatch.setattr(
        bc,
        "cooldown_operation_lock",
        fake_cooldown,
    )

    return state


def run(
    req,
):
    return asyncio.run(
        bc.create_infinite_grid(
            req,
            user(),
        )
    )


def test_independent_rollout_gate_wins_before_everything(
    route_env,
    monkeypatch,
):
    monkeypatch.setattr(
        bc.settings,
        "allow_infinite_grid_create",
        False,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request()
        )

    assert (
        caught.value.status_code
        == 403
    )

    assert (
        caught.value.detail[
            "reason"
        ]
        == "infinite_grid_create_disabled"
    )

    assert (
        route_env["rate_actions"]
        == []
    )

    assert (
        FakeGateClient.create_calls
        == []
    )


def test_global_create_kill_switch_remains_authoritative(
    route_env,
    monkeypatch,
):
    monkeypatch.setattr(
        bc.settings,
        "allow_bot_create",
        False,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_create_simulation",
        False,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request()
        )

    assert (
        caught.value.status_code
        == 403
    )

    assert (
        caught.value.detail[
            "reason"
        ]
        == "bot_create_disabled"
    )

    assert (
        FakeGateClient.create_calls
        == []
    )


def test_simulation_runs_full_safety_envelope_without_gate_write(
    route_env,
    monkeypatch,
):
    monkeypatch.setattr(
        bc.settings,
        "allow_bot_create",
        False,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_create_simulation",
        True,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_armed",
        False,
    )

    result = run(
        request(
            request_id=(
                "infinity-sim-001"
            ),
            confirmation="CREATE",
        )
    )

    assert (
        result["status"]
        == "simulated"
    )

    assert (
        result["write_performed"]
        is False
    )

    assert (
        result["strategy"][
            "strategy_type"
        ]
        == "infinite_grid"
    )

    assert (
        FakeGateClient.create_calls
        == []
    )

    assert (
        route_env[
            "rate_actions"
        ]
        == [
            INFINITE_GRID_CREATE_ACTION
        ]
    )

    assert (
        route_env[
            "reserved_actions"
        ]
        == [
            INFINITE_GRID_CREATE_ACTION
        ]
    )

    assert len(
        route_env[
            "released"
        ]
    ) == 1


def test_fresh_preflight_failure_blocks_submission(
    route_env,
):
    route_env[
        "can_create"
    ] = False

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request(
                request_id=(
                    "infinity-invalid-001"
                )
            )
        )

    assert (
        caught.value.status_code
        == 409
    )

    assert (
        "Infinity Grid validation failed"
        in caught.value.detail[
            "message"
        ]
    )

    assert (
        FakeGateClient.create_calls
        == []
    )


def test_live_available_balance_policy_blocks_overspend(
    route_env,
):
    route_env[
        "available"
    ] = "50"

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request(
                request_id=(
                    "infinity-balance-001"
                ),
                money="100",
            )
        )

    assert (
        caught.value.status_code
        == 403
    )

    assert (
        caught.value.detail[
            "reason"
        ]
        == (
            "insufficient_available_quote_balance"
        )
    )

    assert (
        FakeGateClient.create_calls
        == []
    )


def test_rootadmin_trading_policy_blocks_live_create(
    route_env,
    monkeypatch,
):
    def deny(
        **_kwargs,
    ):
        raise AccountActionPolicyDenied(
            account_id="zolnode",
            capability="trading",
        )

    monkeypatch.setattr(
        bc,
        "require_account_action_allowed",
        deny,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request(
                request_id=(
                    "infinity-policy-001"
                )
            )
        )

    assert (
        caught.value.status_code
        == 403
    )

    assert (
        caught.value.detail[
            "reason"
        ]
        == (
            "trading_disabled_by_account_policy"
        )
    )

    assert (
        caught.value.detail[
            "operation"
        ]
        == INFINITE_GRID_CREATE_ACTION
    )

    assert (
        FakeGateClient.create_calls
        == []
    )


def test_existing_success_is_idempotent_replay_without_write(
    route_env,
):
    route_env["existing"] = {
        "request_id":
            "infinity-replay-001",
        "status":
            "succeeded",
        "response": {
            "status":
                "submitted",
            "write_performed":
                True,
            "strategy": {
                "strategy_id":
                    "EXISTING-001",
                "strategy_type":
                    "infinite_grid",
            },
        },
    }

    result = run(
        request(
            request_id=(
                "infinity-replay-001"
            )
        )
    )

    assert (
        result["idempotent_replay"]
        is True
    )

    assert (
        result["strategy"][
            "strategy_id"
        ]
        == "EXISTING-001"
    )

    assert (
        route_env[
            "rate_actions"
        ]
        == []
    )

    assert (
        FakeGateClient.create_calls
        == []
    )


def test_operation_lock_is_infinity_scoped(
    route_env,
):
    result = run(
        request(
            request_id=(
                "infinity-lock-meta-001"
            )
        )
    )

    assert (
        result["status"]
        == "submitted"
    )

    assert len(
        route_env["lock_calls"]
    ) == 1

    lock = route_env[
        "lock_calls"
    ][0]

    assert (
        lock["action"]
        == INFINITE_GRID_CREATE_ACTION
    )

    assert (
        lock["strategy_type"]
        == "infinite_grid"
    )

    assert (
        lock["market"]
        == "EQTY_USDT"
    )


def test_identical_held_intent_blocks_without_gate_write(
    route_env,
    monkeypatch,
):
    lock = {
        "lock_key":
            "create-intent:test",
        "owner_request_id":
            "other-request",
        "state":
            "held",
    }

    def blocked(
        **_kwargs,
    ):
        raise OperationLocked(
            lock
        )

    monkeypatch.setattr(
        bc,
        "acquire_operation_lock",
        blocked,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request(
                request_id=(
                    "infinity-lock-block-001"
                )
            )
        )

    assert (
        caught.value.status_code
        == 409
    )

    assert (
        caught.value.detail[
            "conflicting_lock"
        ]
        == lock
    )

    assert (
        FakeGateClient.create_calls
        == []
    )

    assert any(
        item[1].get(
            "status"
        )
        == "blocked"
        for item in route_env[
            "marks"
        ]
    )


def test_live_create_uses_exact_infinity_payload_and_one_fake_write(
    route_env,
):
    result = run(
        request(
            request_id=(
                "infinity-live-001"
            )
        )
    )

    assert (
        result["status"]
        == "submitted"
    )

    assert (
        result["write_performed"]
        is True
    )

    assert (
        result["strategy"][
            "strategy_type"
        ]
        == "infinite_grid"
    )

    assert (
        result["gate"][
            "network_request"
        ]
        is False
    )

    assert len(
        FakeGateClient.create_calls
    ) == 1

    payload = (
        FakeGateClient
        .create_calls[0]
    )

    assert payload == {
        "strategy_type":
            "infinite_grid",
        "market":
            "EQTY_USDT",
        "create_params": {
            "money":
                "100",
            "price_floor":
                "0.0015",
            "profit_per_grid":
                "0.01",
            "grid_num":
                10,
            "price_type":
                1,
        },
    }

    assert len(
        route_env["cooled"]
    ) == 1

    assert (
        route_env["cooled"][0][
            "owner_request_id"
        ]
        == "infinity-live-001"
    )


def test_gate_network_failure_is_uncertain_and_not_retried(
    route_env,
):
    FakeGateClient.failure = (
        GateAPIError(
            "synthetic timeout",
            status_code=None,
        )
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request(
                request_id=(
                    "infinity-uncertain-001"
                )
            )
        )

    assert (
        caught.value.status_code
        == 502
    )

    assert (
        caught.value.detail[
            "status"
        ]
        == "uncertain"
    )

    assert (
        "Do not retry"
        in caught.value.detail[
            "message"
        ]
    )

    # Exactly one fake submission attempt.
    assert len(
        FakeGateClient.create_calls
    ) == 1

    uncertain_marks = [
        item
        for item in route_env[
            "marks"
        ]
        if item[1].get(
            "status"
        )
        == "uncertain"
    ]

    assert len(
        uncertain_marks
    ) == 1


def test_gate_business_rejection_is_terminal_rejected(
    route_env,
):
    FakeGateClient.failure = (
        GateAPIError(
            "synthetic Gate rejection",
            status_code=400,
            label="INVALID_PARAM",
            response={
                "label":
                    "INVALID_PARAM",
            },
        )
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        run(
            request(
                request_id=(
                    "infinity-rejected-001"
                )
            )
        )

    assert (
        caught.value.status_code
        == 502
    )

    assert (
        caught.value.detail[
            "status"
        ]
        == "rejected"
    )

    assert len(
        FakeGateClient.create_calls
    ) == 1

    assert any(
        item[1].get(
            "status"
        )
        == "rejected"
        for item in route_env[
            "marks"
        ]
    )


def test_frontend_infinity_create_uses_dashboard_api_only(
) -> None:
    from pathlib import Path

    html = Path(
        "frontend/index.html"
    ).read_text()

    app = Path(
        "frontend/app.js"
    ).read_text()

    controller = Path(
        "frontend/"
        "infinite-grid-preview.js"
    ).read_text()

    dashboard_endpoint = (
        "/api/bot-control/"
        "infinite-grid/create"
    )

    native_gate_endpoint = (
        "/bot/infinite-grid/create"
    )

    assert (
        dashboard_endpoint
        in controller
    )

    assert (
        controller.count(
            dashboard_endpoint
        )
        == 1
    )

    assert (
        dashboard_endpoint
        not in app
    )

    assert (
        dashboard_endpoint
        not in html
    )

    for frontend_source in (
        html,
        app,
        controller,
    ):
        assert (
            native_gate_endpoint
            not in frontend_source
        )

    assert (
        "submitInfiniteGridCreate"
        in controller
    )

    assert (
        "Create Infinity Grid"
        in html
    )

    assert (
        "Final confirmation"
        in html
    )
