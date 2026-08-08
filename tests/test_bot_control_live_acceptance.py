from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.api.bot_control as bc
from app.main import app


def auth(
    username: str = "zolnode",
    password: str = "zolnode-test-password",
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    return {
        "Authorization": f"Basic {token}"
    }


class FakeGateClient:
    """
    Acceptance-test tripwire.

    This replaces app.api.bot_control.GateClient.
    Nothing in this suite can reach Gate through the
    Bot Control Create/Stop route.
    """

    create_calls: list[dict] = []
    stop_calls: list[tuple[str, str]] = []

    def __init__(
        self,
        *args,
        **kwargs,
    ) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False

    async def create_spot_grid(
        self,
        payload: dict,
    ):
        self.__class__.create_calls.append(
            payload
        )

        return SimpleNamespace(
            status_code=200,
            data={
                "strategy_id": (
                    "FAKE-ACCEPTANCE-STRATEGY"
                ),
                "strategy_type": "spot_grid",
                "market": payload.get(
                    "market"
                ),
                "status": "running",
                "jump_url": None,
            },
            raw={
                "acceptance_test": True,
                "network_request": False,
            },
        )

    async def stop_bot(
        self,
        strategy_id: str,
        strategy_type: str,
    ):
        self.__class__.stop_calls.append(
            (
                strategy_id,
                strategy_type,
            )
        )

        return SimpleNamespace(
            status_code=200,
            data={
                "strategy_id": strategy_id,
                "status": "stopped",
            },
            raw={
                "acceptance_test": True,
                "network_request": False,
            },
        )


def create_body(
    *,
    request_id: str,
    market: str = "EQTY_USDT",
    money: str = "100",
    confirmation: str = "CREATE",
) -> dict:
    return {
        "account_id": "zolnode",
        "market": market,
        "money": money,
        "low_price": "1",
        "high_price": "2",
        "grid_num": 10,
        "price_type": 0,
        "confirmation": confirmation,
        "request_id": request_id,
    }


def stop_body(
    *,
    request_id: str,
    confirmation: str = "STOP",
) -> dict:
    return {
        "request_id": request_id,
        "confirmation": confirmation,
    }


def configure_create(
    monkeypatch,
    *,
    simulation: bool,
    allow: bool,
    armed: bool,
    accounts: str = "zolnode",
) -> None:
    monkeypatch.setattr(
        bc.settings,
        "bot_create_simulation",
        simulation,
    )

    monkeypatch.setattr(
        bc.settings,
        "allow_bot_create",
        allow,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_armed",
        armed,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_accounts",
        accounts,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_create_confirmation_text",
        "CREATE",
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_create_confirmation_text",
        "LIVE CREATE",
    )


def configure_stop(
    monkeypatch,
    *,
    simulation: bool,
    allow: bool,
    armed: bool,
    accounts: str = "zolnode",
) -> None:
    monkeypatch.setattr(
        bc.settings,
        "bot_stop_simulation",
        simulation,
    )

    monkeypatch.setattr(
        bc.settings,
        "allow_bot_stop",
        allow,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_armed",
        armed,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_accounts",
        accounts,
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_stop_confirmation_text",
        "STOP",
    )

    monkeypatch.setattr(
        bc.settings,
        "bot_control_live_stop_confirmation_text",
        "LIVE STOP",
    )


def assert_no_fake_gate_write() -> None:
    assert FakeGateClient.create_calls == []
    assert FakeGateClient.stop_calls == []


def assert_rejected_without_write(
    response,
) -> None:
    assert response.status_code >= 400

    assert_no_fake_gate_write()

    payload = response.json()
    detail = payload.get("detail")

    # Where the API exposes write_performed on an
    # error path, it must explicitly be false.
    if (
        isinstance(detail, dict)
        and "write_performed" in detail
    ):
        assert (
            detail["write_performed"]
            is False
        )


@pytest.fixture
def route_env(
    monkeypatch,
):
    FakeGateClient.create_calls = []
    FakeGateClient.stop_calls = []

    state = {
        "available": "100",
        "can_create": True,
        "bot": {
            "id": 900001,
            "account_id": "zolnode",
            "strategy_id": (
                "FAKE-STOP-STRATEGY"
            ),
            "strategy_name": (
                "Acceptance Test Bot"
            ),
            "strategy_type": "spot_grid",
            "market": "EQTY_USDT",
            "status": "running",
            "source_status": "running",
            "invest_amount": "100",
            "total_profit": "0",
            "current_value": "100",
            "stop_supported": True,
        },
    }

    # Absolute network tripwire for the Bot Control
    # module.
    monkeypatch.setattr(
        bc,
        "GateClient",
        FakeGateClient,
    )

    # No prior idempotency record by default.
    monkeypatch.setattr(
        bc,
        "find_matching_request",
        lambda **kwargs: None,
    )

    # Rate limiting is separately tested below.
    monkeypatch.setattr(
        bc,
        "_enforce_bot_control_rate_limit",
        lambda **kwargs: None,
    )

    async def fake_prepare_spot_grid(
        request,
        user,
    ):
        market = (
            request.market
            .strip()
            .upper()
        )

        base, quote = market.split(
            "_",
            1,
        )

        payload = (
            bc.build_spot_grid_payload(
                market=market,
                money=request.money,
                low_price=request.low_price,
                high_price=request.high_price,
                grid_num=request.grid_num,
                price_type=request.price_type,
                trigger_price=(
                    request.trigger_price
                ),
                stop_profit=(
                    request.stop_profit
                ),
                stop_loss=(
                    request.stop_loss
                ),
            )
        )

        return {
            "status": (
                "ready"
                if state["can_create"]
                else "invalid"
            ),
            "can_create": (
                state["can_create"]
            ),
            "write_performed": False,
            "market": {
                "id": market,
                "base": base,
                "quote": quote,
            },
            "balance": {
                "currency": quote,
                "available": (
                    state["available"]
                ),
            },
            "errors": (
                []
                if state["can_create"]
                else [
                    "Synthetic validation failure"
                ]
            ),
            "warnings": [],
            "gate_create_payload_preview": (
                payload
            ),
        }

    monkeypatch.setattr(
        bc,
        "prepare_spot_grid",
        fake_prepare_spot_grid,
    )

    # Safe fake Bot Control credential.
    monkeypatch.setattr(
        bc,
        "get_bot_control_account",
        lambda account_id: object(),
    )

    def fake_reserve_request(
        **kwargs,
    ):
        return (
            {
                "request_id": (
                    kwargs["request_id"]
                ),
                "status": "reserved",
            },
            True,
        )

    monkeypatch.setattr(
        bc,
        "reserve_request",
        fake_reserve_request,
    )

    monkeypatch.setattr(
        bc,
        "create_intent_lock",
        lambda **kwargs: (
            "acceptance-create-lock",
            "acceptance-intent-hash",
        ),
    )

    def fake_acquire_operation_lock(
        **kwargs,
    ):
        return {
            "lock_key": (
                kwargs["lock_key"]
            ),
            "lock_type": (
                kwargs["lock_type"]
            ),
            "account_id": (
                kwargs["account_id"]
            ),
            "action": kwargs["action"],
            "owner_request_id": (
                kwargs[
                    "owner_request_id"
                ]
            ),
            "state": "held",
        }

    monkeypatch.setattr(
        bc,
        "acquire_operation_lock",
        fake_acquire_operation_lock,
    )

    monkeypatch.setattr(
        bc,
        "mark_request",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        bc,
        "release_operation_lock",
        lambda **kwargs: True,
    )

    monkeypatch.setattr(
        bc,
        "cooldown_operation_lock",
        lambda **kwargs: None,
    )

    def fake_load_target(
        bot_id,
        user,
    ):
        bot = dict(
            state["bot"]
        )

        # Preserve real account authorization even
        # though the DB lookup itself is mocked.
        bc.require_account_access(
            user,
            bot["account_id"],
        )

        return bot

    monkeypatch.setattr(
        bc,
        "_load_bot_control_target",
        fake_load_target,
    )

    async def fake_prepare_stop(
        bot_id,
        user,
    ):
        bot = fake_load_target(
            bot_id,
            user,
        )

        return {
            "status": "ready",
            "can_stop": True,
            "write_performed": False,
            "bot": bot,
            "gate_snapshot": {
                "status": "running",
            },
            "errors": [],
            "warnings": [],
            "gate_stop_payload_preview": {
                "strategy_id": (
                    bot["strategy_id"]
                ),
                "strategy_type": (
                    bot["strategy_type"]
                ),
            },
        }

    monkeypatch.setattr(
        bc,
        "prepare_bot_stop",
        fake_prepare_stop,
    )

    monkeypatch.setattr(
        bc,
        "strategy_lock_key",
        lambda **kwargs: (
            "acceptance-stop-lock"
        ),
    )

    return state


@pytest.fixture
def client(
    route_env,
):
    with TestClient(app) as value:
        yield value


# ------------------------------------------------------------
# Global kill switches
# ------------------------------------------------------------


def test_create_global_kill_switch_wins(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=False,
        armed=True,
        accounts="*",
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-create-kill-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 403
    assert_rejected_without_write(
        response
    )


def test_stop_global_kill_switch_wins(
    client,
    route_env,
    monkeypatch,
):
    configure_stop(
        monkeypatch,
        simulation=False,
        allow=False,
        armed=True,
        accounts="*",
    )

    response = client.post(
        "/api/bot-control/bots/900001/stop",
        headers=auth(),
        json=stop_body(
            request_id=(
                "accept-stop-kill-001"
            ),
            confirmation="LIVE STOP",
        ),
    )

    assert response.status_code == 403
    assert_rejected_without_write(
        response
    )


# ------------------------------------------------------------
# Simulation remains independent and safe
# ------------------------------------------------------------


def test_simulation_still_uses_create_confirmation(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=True,
        allow=False,
        armed=False,
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-sim-create-001"
            ),
            confirmation="CREATE",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "simulated"
    assert data["simulation"] is True
    assert data["write_performed"] is False

    assert_no_fake_gate_write()


def test_simulation_rejects_live_confirmation(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=True,
        allow=False,
        armed=False,
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-sim-confirm-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 400

    detail = response.json()["detail"]

    assert detail["mode"] == "simulation"
    assert (
        detail["required_confirmation"]
        == "CREATE"
    )

    assert_rejected_without_write(
        response
    )


# ------------------------------------------------------------
# Live Create safety policy
# ------------------------------------------------------------


def test_live_create_requires_arm(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=False,
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-live-unarmed-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 403

    detail = response.json()["detail"]

    assert (
        detail["reason"]
        == "live_not_armed"
    )
    assert detail["write_performed"] is False

    assert_rejected_without_write(
        response
    )


def test_live_create_requires_armed_account(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="arnold",
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-live-account-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 403

    detail = response.json()["detail"]

    assert (
        detail["reason"]
        == "account_not_live_enabled"
    )

    assert_rejected_without_write(
        response
    )


def test_dashboard_user_cannot_create_for_other_account(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="*",
    )

    body = create_body(
        request_id=(
            "accept-auth-account-001"
        ),
        confirmation="LIVE CREATE",
    )

    body["account_id"] = "arnold"

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=body,
    )

    assert response.status_code == 403

    assert_rejected_without_write(
        response
    )


def test_live_create_rejects_above_available_balance(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    # Keep preflight artificially "ready" so this
    # specifically proves the independent live policy.
    route_env["available"] = "100"

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-balance-over-001"
            ),
            money="101",
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 403

    detail = response.json()["detail"]

    assert (
        detail["reason"]
        == (
            "insufficient_available_quote_balance"
        )
    )

    assert detail["maximum_investment"] == "100"
    assert detail["write_performed"] is False

    assert_rejected_without_write(
        response
    )


def test_live_create_rejects_unknown_available_balance(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    route_env["available"] = None

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-balance-unknown-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert (
        detail["reason"]
        == "available_balance_unknown"
    )
    assert detail["write_performed"] is False

    assert_rejected_without_write(
        response
    )


@pytest.mark.parametrize(
    (
        "market",
        "money",
        "available",
    ),
    [
        (
            "EQTY_USDT",
            "100",
            "100",
        ),
        (
            "BTC_USDT",
            "2500",
            "2500",
        ),
        (
            "ETH_BTC",
            "0.4",
            "0.4",
        ),
        (
            "SOL_USDC",
            "900",
            "1000",
        ),
    ],
)
def test_live_create_accepts_generic_markets_and_dynamic_balance(
    client,
    route_env,
    monkeypatch,
    market,
    money,
    available,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="*",
    )

    route_env["available"] = (
        available
    )

    request_id = (
        "accept-market-"
        + market.lower()
        .replace("_", "-")
        + "-001"
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=request_id,
            market=market,
            money=money,
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    # This is a FAKE Gate submission. Seeing
    # write_performed=true here means the HTTP route
    # reached FakeGateClient, not Gate.io.
    assert data["write_performed"] is True

    assert (
        data["gate"][
            "network_request"
        ]
        is False
    )

    assert (
        FakeGateClient.create_calls[-1][
            "market"
        ]
        == market
    )

    assert FakeGateClient.stop_calls == []


def test_live_create_rejects_missing_control_credentials(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    monkeypatch.setattr(
        bc,
        "get_bot_control_account",
        lambda account_id: None,
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-no-creds-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 409

    assert_rejected_without_write(
        response
    )


# ------------------------------------------------------------
# Idempotency, rate limiting and operation locking
# ------------------------------------------------------------


def test_idempotent_replay_never_submits_again(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=False,
    )

    monkeypatch.setattr(
        bc,
        "find_matching_request",
        lambda **kwargs: {
            "request_id": (
                kwargs["request_id"]
            ),
            "status": "succeeded",
            "response": {
                "status": "submitted",
                "write_performed": True,
                "simulation": False,
                "strategy": {
                    "strategy_id": (
                        "OLD-FAKE-STRATEGY"
                    ),
                },
            },
        },
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-idempotent-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["idempotent_replay"]
        is True
    )

    # The response describes the old operation,
    # but no new write was attempted.
    assert_no_fake_gate_write()


def test_rate_limit_returns_429_before_write(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    def limited(
        **kwargs,
    ):
        raise HTTPException(
            status_code=429,
            detail={
                "message": (
                    "Bot Control rate limit exceeded"
                ),
                "scope": "user",
                "action": (
                    "spot_grid_create"
                ),
                "retry_after_seconds": 123,
            },
            headers={
                "Retry-After": "123",
            },
        )

    monkeypatch.setattr(
        bc,
        "_enforce_bot_control_rate_limit",
        limited,
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-rate-limit-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 429
    assert response.headers[
        "retry-after"
    ] == "123"

    assert_rejected_without_write(
        response
    )


def test_duplicate_create_intent_lock_blocks_write(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    def locked(
        **kwargs,
    ):
        raise bc.OperationLocked({
            "lock_key": (
                kwargs["lock_key"]
            ),
            "lock_type": (
                "create_intent"
            ),
            "account_id": "zolnode",
            "action": (
                "spot_grid_create"
            ),
            "owner_request_id": (
                "existing-owner-request"
            ),
            "state": "held",
        })

    monkeypatch.setattr(
        bc,
        "acquire_operation_lock",
        locked,
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-create-lock-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["write_performed"] is False

    assert_rejected_without_write(
        response
    )


def test_recovered_uncertain_request_cannot_be_retried(
    client,
    route_env,
    monkeypatch,
):
    configure_create(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    monkeypatch.setattr(
        bc,
        "find_matching_request",
        lambda **kwargs: {
            "request_id": (
                kwargs["request_id"]
            ),
            "status": "uncertain",
            "error": (
                "Recovered after application restart"
            ),
            "response": {},
        },
    )

    response = client.post(
        "/api/bot-control/spot-grid/create",
        headers=auth(),
        json=create_body(
            request_id=(
                "accept-uncertain-001"
            ),
            confirmation="LIVE CREATE",
        ),
    )

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["status"] == "uncertain"

    assert_rejected_without_write(
        response
    )


# ------------------------------------------------------------
# Live Stop safety policy
# ------------------------------------------------------------


def test_live_stop_requires_live_confirmation(
    client,
    route_env,
    monkeypatch,
):
    configure_stop(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    response = client.post(
        "/api/bot-control/bots/900001/stop",
        headers=auth(),
        json=stop_body(
            request_id=(
                "accept-stop-confirm-001"
            ),
            confirmation="STOP",
        ),
    )

    assert response.status_code == 400

    detail = response.json()["detail"]

    assert detail["mode"] == "live"
    assert (
        detail["required_confirmation"]
        == "LIVE STOP"
    )

    assert_rejected_without_write(
        response
    )


def test_live_stop_requires_arm(
    client,
    route_env,
    monkeypatch,
):
    configure_stop(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=False,
    )

    response = client.post(
        "/api/bot-control/bots/900001/stop",
        headers=auth(),
        json=stop_body(
            request_id=(
                "accept-stop-unarmed-001"
            ),
            confirmation="LIVE STOP",
        ),
    )

    assert response.status_code == 403

    detail = response.json()["detail"]

    assert (
        detail["reason"]
        == "live_not_armed"
    )

    assert_rejected_without_write(
        response
    )


def test_live_stop_requires_armed_account(
    client,
    route_env,
    monkeypatch,
):
    configure_stop(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="arnold",
    )

    response = client.post(
        "/api/bot-control/bots/900001/stop",
        headers=auth(),
        json=stop_body(
            request_id=(
                "accept-stop-account-001"
            ),
            confirmation="LIVE STOP",
        ),
    )

    assert response.status_code == 403

    detail = response.json()["detail"]

    assert (
        detail["reason"]
        == "account_not_live_enabled"
    )

    assert_rejected_without_write(
        response
    )


def test_other_dashboard_user_cannot_stop_zolnode_bot(
    client,
    route_env,
    monkeypatch,
):
    configure_stop(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="*",
    )

    response = client.post(
        "/api/bot-control/bots/900001/stop",
        headers=auth(
            "arnold",
            "arnold-test-password",
        ),
        json=stop_body(
            request_id=(
                "accept-stop-auth-001"
            ),
            confirmation="LIVE STOP",
        ),
    )

    assert response.status_code == 403

    assert_rejected_without_write(
        response
    )


def test_live_stop_allowed_path_reaches_only_fake_gate_client(
    client,
    route_env,
    monkeypatch,
):
    configure_stop(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    response = client.post(
        "/api/bot-control/bots/900001/stop",
        headers=auth(),
        json=stop_body(
            request_id=(
                "accept-stop-fake-live-001"
            ),
            confirmation="LIVE STOP",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["write_performed"] is True
    assert data["simulation"] is False

    assert (
        data["gate"][
            "network_request"
        ]
        is False
    )

    assert FakeGateClient.stop_calls == [
        (
            "FAKE-STOP-STRATEGY",
            "spot_grid",
        )
    ]

    assert FakeGateClient.create_calls == []


def test_duplicate_stop_lock_blocks_write(
    client,
    route_env,
    monkeypatch,
):
    configure_stop(
        monkeypatch,
        simulation=False,
        allow=True,
        armed=True,
        accounts="zolnode",
    )

    def locked(
        **kwargs,
    ):
        raise bc.OperationLocked({
            "lock_key": (
                kwargs["lock_key"]
            ),
            "lock_type": "strategy",
            "account_id": "zolnode",
            "action": "bot_stop",
            "strategy_id": (
                "FAKE-STOP-STRATEGY"
            ),
            "owner_request_id": (
                "existing-stop-owner"
            ),
            "state": "held",
        })

    monkeypatch.setattr(
        bc,
        "acquire_operation_lock",
        locked,
    )

    response = client.post(
        "/api/bot-control/bots/900001/stop",
        headers=auth(),
        json=stop_body(
            request_id=(
                "accept-stop-lock-001"
            ),
            confirmation="LIVE STOP",
        ),
    )

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["write_performed"] is False

    assert_rejected_without_write(
        response
    )
