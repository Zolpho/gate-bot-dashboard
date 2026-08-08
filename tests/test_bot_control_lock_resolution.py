from __future__ import annotations

import uuid

from app.bot_control_lock_resolution import (
    apply_reconciliation_lock_policy,
    decide_reconciliation_lock_action,
)
from app.bot_control_locks import (
    acquire_operation_lock,
    get_operation_lock_for_request,
    strategy_lock_key,
)
from app.config import get_settings
from app.db import init_db


def test_confirmed_create_enters_cooldown():
    assert (
        decide_reconciliation_lock_action(
            action="spot_grid_create",
            outcome="confirmed_created",
        )
        == "cooldown"
    )


def test_confirmed_stop_enters_cooldown():
    assert (
        decide_reconciliation_lock_action(
            action="bot_stop",
            outcome="confirmed_stopped",
        )
        == "cooldown"
    )


def test_rejection_releases():
    assert (
        decide_reconciliation_lock_action(
            action="spot_grid_create",
            outcome="already_rejected",
        )
        == "release"
    )


def test_simulation_releases():
    assert (
        decide_reconciliation_lock_action(
            action="bot_stop",
            outcome="not_applicable",
        )
        == "release"
    )


def test_probable_create_keeps_lock():
    assert (
        decide_reconciliation_lock_action(
            action="spot_grid_create",
            outcome="probable_created",
        )
        == "keep"
    )


def test_running_stop_keeps_lock():
    assert (
        decide_reconciliation_lock_action(
            action="bot_stop",
            outcome="observed_running",
        )
        == "keep"
    )


def test_stop_in_progress_keeps_lock():
    assert (
        decide_reconciliation_lock_action(
            action="bot_stop",
            outcome="stop_in_progress",
        )
        == "keep"
    )


def test_inconclusive_keeps_lock():
    assert (
        decide_reconciliation_lock_action(
            action="spot_grid_create",
            outcome="inconclusive",
        )
        == "keep"
    )


def test_apply_rejection_removes_existing_lock():
    init_db()

    suffix = uuid.uuid4().hex
    request_id = "resolution-" + suffix

    key = strategy_lock_key(
        account_id="test-account",
        strategy_type="spot_grid",
        strategy_id=suffix,
    )

    acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=request_id,
        username="tester",
        strategy_id=suffix,
        strategy_type="spot_grid",
    )

    result = apply_reconciliation_lock_policy(
        request_record={
            "request_id": request_id,
            "account_id": "test-account",
            "action": "bot_stop",
        },
        reconciliation={
            "id": 123,
            "outcome": "already_rejected",
            "confidence": "definitive",
        },
        username="tester",
        settings=get_settings(),
    )

    assert result["decision"] == "release"

    assert (
        get_operation_lock_for_request(
            request_id
        )
        is None
    )


def test_apply_inconclusive_keeps_existing_lock():
    init_db()

    suffix = uuid.uuid4().hex
    request_id = "resolution-" + suffix

    key = strategy_lock_key(
        account_id="test-account",
        strategy_type="spot_grid",
        strategy_id=suffix,
    )

    acquire_operation_lock(
        lock_key=key,
        lock_type="strategy",
        account_id="test-account",
        action="bot_stop",
        owner_request_id=request_id,
        username="tester",
        strategy_id=suffix,
        strategy_type="spot_grid",
    )

    result = apply_reconciliation_lock_policy(
        request_record={
            "request_id": request_id,
            "account_id": "test-account",
            "action": "bot_stop",
        },
        reconciliation={
            "id": 124,
            "outcome": "observed_running",
            "confidence": "high",
        },
        username="tester",
        settings=get_settings(),
    )

    assert result["decision"] == "keep"

    assert (
        get_operation_lock_for_request(
            request_id
        )
        is not None
    )
