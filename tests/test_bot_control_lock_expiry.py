from __future__ import annotations

from datetime import timedelta
import uuid

from sqlalchemy import select

from app.bot_control_locks import (
    acquire_operation_lock,
    cooldown_operation_lock,
    get_operation_lock,
    get_operation_lock_for_request,
    list_operation_locks,
    strategy_lock_key,
)
from app.db import (
    init_db,
    session_scope,
    utcnow,
)
from app.models import (
    BotControlOperationLock,
)


def make_expired_cooldown():
    init_db()

    suffix = uuid.uuid4().hex

    lock_key = strategy_lock_key(
        account_id="expiry-test",
        strategy_type="spot_grid",
        strategy_id=suffix,
    )

    request_id = (
        "expiry-request-" + suffix
    )

    acquire_operation_lock(
        lock_key=lock_key,
        lock_type="strategy",
        account_id="expiry-test",
        action="bot_stop",
        owner_request_id=request_id,
        username="expiry-tester",
        strategy_id=suffix,
        strategy_type="spot_grid",
        market="EQTY_USDT",
    )

    cooldown_operation_lock(
        lock_key=lock_key,
        owner_request_id=request_id,
        seconds=300,
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.lock_key
                == lock_key
            )
        )

        assert row is not None

        row.cooldown_until = (
            utcnow()
            - timedelta(seconds=1)
        )

        db.flush()

    return (
        lock_key,
        request_id,
    )


def test_get_prunes_expired_cooldown():
    lock_key, _ = (
        make_expired_cooldown()
    )

    assert (
        get_operation_lock(
            lock_key
        )
        is None
    )


def test_request_lookup_prunes_expired_cooldown():
    _, request_id = (
        make_expired_cooldown()
    )

    assert (
        get_operation_lock_for_request(
            request_id
        )
        is None
    )


def test_list_prunes_expired_cooldown():
    lock_key, _ = (
        make_expired_cooldown()
    )

    rows = list_operation_locks(
        account_ids={
            "expiry-test"
        }
    )

    assert all(
        row["lock_key"]
        != lock_key
        for row in rows
    )
