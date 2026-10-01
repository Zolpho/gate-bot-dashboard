from __future__ import annotations

import ast
import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import app.bot_control_reconcile as reconcile_module
from app.bot_control_actions import (
    CREATE_ACTIONS,
    INFINITE_GRID_CREATE_ACTION,
    MUTATION_ACTIONS,
    SPOT_GRID_CREATE_ACTION,
)
from app.bot_control_live_policy import (
    evaluate_live_create_policy,
)
from app.bot_control_lock_resolution import (
    _cooldown_seconds,
    decide_reconciliation_lock_action,
)
from app.bot_control_rate_limit import (
    policy_for_action,
)
from app.bot_control_reconcile import (
    match_create_candidates,
)
from app.config import Settings


def isolated_settings(
    **overrides,
) -> Settings:
    return Settings(
        _env_file=None,
        **overrides,
    )


def test_infinity_rollout_gate_defaults_off(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "ALLOW_INFINITE_GRID_CREATE",
        raising=False,
    )

    settings = isolated_settings()

    assert (
        settings.allow_infinite_grid_create
        is False
    )


def test_infinity_create_is_registered_mutation_action(
) -> None:
    assert (
        INFINITE_GRID_CREATE_ACTION
        in CREATE_ACTIONS
    )

    assert (
        INFINITE_GRID_CREATE_ACTION
        in MUTATION_ACTIONS
    )

    assert (
        SPOT_GRID_CREATE_ACTION
        in CREATE_ACTIONS
    )


def test_infinity_create_uses_shared_create_rate_limit_policy(
) -> None:
    settings = isolated_settings(
        bot_control_create_user_limit=7,
        bot_control_create_user_window_seconds=321,
        bot_control_account_mutation_limit=11,
        bot_control_account_mutation_window_seconds=654,
    )

    spot = policy_for_action(
        settings,
        SPOT_GRID_CREATE_ACTION,
    )

    infinity = policy_for_action(
        settings,
        INFINITE_GRID_CREATE_ACTION,
    )

    assert spot is not None
    assert infinity is not None
    assert infinity == spot


def test_live_create_policy_accepts_infinity_action(
) -> None:
    settings = isolated_settings(
        bot_control_live_armed=True,
        bot_control_live_accounts="*",
    )

    decision = evaluate_live_create_policy(
        settings=settings,
        action=INFINITE_GRID_CREATE_ACTION,
        account_id="zolnode",
        market="BTC_USDT",
        quote_currency="USDT",
        requested_investment=Decimal("10"),
        available_quote=Decimal("20"),
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_live_create_policy_fails_closed_for_unknown_action(
) -> None:
    settings = isolated_settings(
        bot_control_live_armed=True,
        bot_control_live_accounts="*",
    )

    decision = evaluate_live_create_policy(
        settings=settings,
        action="unknown_create",
        account_id="zolnode",
        market="BTC_USDT",
        quote_currency="USDT",
        requested_investment=Decimal("10"),
        available_quote=Decimal("20"),
    )

    assert decision.allowed is False

    assert (
        decision.reason
        == "unsupported_create_action"
    )


def test_infinity_confirmed_create_enters_cooldown(
) -> None:
    assert (
        decide_reconciliation_lock_action(
            action=(
                INFINITE_GRID_CREATE_ACTION
            ),
            outcome="confirmed_created",
        )
        == "cooldown"
    )


def test_infinity_create_uses_create_duplicate_cooldown(
) -> None:
    settings = isolated_settings(
        bot_create_duplicate_cooldown_seconds=321,
    )

    assert (
        _cooldown_seconds(
            action=(
                INFINITE_GRID_CREATE_ACTION
            ),
            settings=settings,
        )
        == 321
    )


def test_infinity_candidate_matching_uses_strategy_type(
) -> None:
    record = {
        "created_at":
            "2026-10-01T10:00:00+00:00",
        "request": {
            "gate_payload": {
                "strategy_type":
                    "infinite_grid",
                "market":
                    "BTC_USDT",
                "create_params": {
                    "money": "100",
                },
            },
        },
    }

    items = [{
        "strategy_id": "IG-123",
        "strategy_type": "infinite_grid",
        "strategy_name": "Infinity Grid",
        "market": "BTC_USDT",
        "status": "running",
        "invest_amount": "100.000000",
        "created_at":
            "2026-10-01T10:01:00+00:00",
    }]

    matches = match_create_candidates(
        record,
        items,
    )

    assert len(matches) == 1

    assert (
        matches[0]["strategy_id"]
        == "IG-123"
    )

    assert (
        matches[0]["strategy_type"]
        == "infinite_grid"
    )

    assert (
        matches[0]["time_match"]
        is True
    )


def test_infinity_reconciliation_uses_create_handler(
    monkeypatch,
) -> None:
    calls = []

    class FakeGateClient:
        def __init__(
            self,
            *_args,
            **_kwargs,
        ):
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

        async def get_bot_detail(
            self,
            strategy_id,
            strategy_type,
        ):
            calls.append(
                (
                    strategy_id,
                    strategy_type,
                )
            )

            return SimpleNamespace(
                data={
                    "strategy_id":
                        strategy_id,
                    "strategy_type":
                        strategy_type,
                    "status":
                        "running",
                },
            )

    monkeypatch.setattr(
        reconcile_module,
        "GateClient",
        FakeGateClient,
    )

    result = asyncio.run(
        reconcile_module
        .reconcile_request_against_gate(
            record={
                "request_id":
                    "infinity-foundation-001",
                "action":
                    INFINITE_GRID_CREATE_ACTION,
                "status":
                    "uncertain",
                "strategy_id":
                    "IG-123",
                "request": {
                    "gate_payload": {
                        "strategy_type":
                            "infinite_grid",
                        "market":
                            "BTC_USDT",
                        "create_params": {
                            "money":
                                "100",
                        },
                    },
                },
            },
            monitor_account=object(),
            settings=object(),
        )
    )

    assert (
        result["outcome"]
        == "confirmed_created"
    )

    assert (
        result["gate_read_performed"]
        is True
    )

    assert (
        result["gate_write_performed"]
        is False
    )

    assert calls == [
        (
            "IG-123",
            "infinite_grid",
        )
    ]


def test_infinity_create_route_is_registered(
) -> None:
    tree = ast.parse(
        Path(
            "app/api/bot_control.py"
        ).read_text()
    )

    routes = []

    for node in tree.body:
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        for decorator in node.decorator_list:
            if not isinstance(
                decorator,
                ast.Call,
            ):
                continue

            func = decorator.func

            if not (
                isinstance(
                    func,
                    ast.Attribute,
                )
                and func.attr == "post"
                and decorator.args
                and isinstance(
                    decorator.args[0],
                    ast.Constant,
                )
            ):
                continue

            routes.append(
                str(
                    decorator.args[0].value
                )
            )

    assert (
        "/infinite-grid/create"
        in routes
    )
