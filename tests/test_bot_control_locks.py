from __future__ import annotations

import uuid

import pytest

from app.bot_control_locks import (
    OperationLocked,
    acquire_operation_lock,
    cooldown_operation_lock,
    create_intent_lock,
    release_operation_lock,
    strategy_lock_key,
)
from app.db import init_db


def uid() -> str:
    return uuid.uuid4().hex


def test_strategy_lock_blocks_second_request():
    init_db()

    suffix = uid()

    key = strategy_lock_key(
        account_id="test-account",
        strategy_type="spot_grid",
        strategy_id=suffix,
    )

    first = "first-" + suffix
    second = "second-" + suffix

    acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=first,
        username="tester",
        strategy_id=suffix,
        strategy_type="spot_grid",
        market="EQTY_USDT",
    )

    with pytest.raises(
        OperationLocked
    ) as exc:
        acquire_operation_lock(
            lock_key=key,
            lock_type="strategy",
            account_id="test-account",
            action="bot_stop",
            owner_request_id=second,
            username="tester",
            strategy_id=suffix,
            strategy_type="spot_grid",
            market="EQTY_USDT",
        )

    assert (
        exc.value.lock[
            "owner_request_id"
        ]
        == first
    )

    release_operation_lock(
        lock_key=key,
        owner_request_id=first,
    )


def test_same_request_can_reobserve_own_lock():
    init_db()

    suffix = uid()

    key = strategy_lock_key(
        account_id="test-account",
        strategy_type="spot_grid",
        strategy_id=suffix,
    )

    request_id = "owner-" + suffix

    first = acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=request_id,
        username="tester",
        strategy_id=suffix,
        strategy_type="spot_grid",
    )

    second = acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=request_id,
        username="tester",
        strategy_id=suffix,
        strategy_type="spot_grid",
    )

    assert (
        first["owner_request_id"]
        == second["owner_request_id"]
    )

    release_operation_lock(
        lock_key=key,
        owner_request_id=request_id,
    )


def test_release_allows_new_owner():
    init_db()

    suffix = uid()

    key = strategy_lock_key(
        account_id="test-account",
        strategy_type="spot_grid",
        strategy_id=suffix,
    )

    first = "first-" + suffix
    second = "second-" + suffix

    acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=first,
        username="tester",
    )

    assert release_operation_lock(
        lock_key=key,
        owner_request_id=first,
    )

    lock = acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=second,
        username="tester",
    )

    assert (
        lock["owner_request_id"]
        == second
    )

    release_operation_lock(
        lock_key=key,
        owner_request_id=second,
    )


def test_cooldown_blocks_new_request():
    init_db()

    suffix = uid()

    key = strategy_lock_key(
        account_id="test-account",
        strategy_type="spot_grid",
        strategy_id=suffix,
    )

    first = "first-" + suffix

    acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=first,
        username="tester",
    )

    cooldown = cooldown_operation_lock(
        lock_key=key,
        owner_request_id=first,
        seconds=60,
    )

    assert cooldown is not None
    assert cooldown["state"] == "cooldown"

    with pytest.raises(
        OperationLocked
    ):
        acquire_operation_lock(
            lock_key=key,
            lock_type="strategy",
            account_id="test-account",
            action="bot_stop",
            owner_request_id="second-" + suffix,
            username="tester",
        )

    release_operation_lock(
        lock_key=key,
        owner_request_id=first,
    )


def test_identical_create_intent_has_same_key():
    payload = {
        "strategy_type": "spot_grid",
        "market": "EQTY_USDT",
        "create_params": {
            "money": "100",
            "low_price": "0.00165",
            "high_price": "0.002",
            "grid_num": 10,
        },
    }

    first_key, first_hash = (
        create_intent_lock(
            account_id="zolnode",
            gate_payload=payload,
        )
    )

    second_key, second_hash = (
        create_intent_lock(
            account_id="zolnode",
            gate_payload=payload,
        )
    )

    assert first_key == second_key
    assert first_hash == second_hash


def test_changed_create_intent_has_different_key():
    first, _ = create_intent_lock(
        account_id="zolnode",
        gate_payload={
            "market": "EQTY_USDT",
            "create_params": {
                "money": "100",
            },
        },
    )

    second, _ = create_intent_lock(
        account_id="zolnode",
        gate_payload={
            "market": "EQTY_USDT",
            "create_params": {
                "money": "101",
            },
        },
    )

    assert first != second
