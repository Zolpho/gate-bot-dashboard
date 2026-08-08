from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app.bot_control_rate_limit import (
    BotControlRateLimitExceeded,
    RateLimitPolicy,
    check_and_record_rate_limit,
)
from app.db import init_db, session_scope
from app.models import BotControlRateLimitEvent


def unique(prefix: str) -> str:
    return (
        prefix
        + "-"
        + uuid.uuid4().hex
    )


def clear_events() -> None:
    with session_scope() as db:
        db.execute(
            delete(
                BotControlRateLimitEvent
            )
        )


def test_user_limit_blocks_next_request():
    init_db()
    clear_events()

    username = unique("user")
    account = unique("account")

    policy = RateLimitPolicy(
        user_limit=2,
        user_window_seconds=600,
        account_limit=100,
        account_window_seconds=600,
    )

    first = check_and_record_rate_limit(
        username=username,
        account_id=account,
        action="spot_grid_create",
        policy=policy,
    )

    second = check_and_record_rate_limit(
        username=username,
        account_id=account,
        action="spot_grid_create",
        policy=policy,
    )

    assert first["allowed"] is True
    assert second["user_count"] == 2

    with pytest.raises(
        BotControlRateLimitExceeded
    ) as exc:
        check_and_record_rate_limit(
            username=username,
            account_id=account,
            action="spot_grid_create",
            policy=policy,
        )

    assert exc.value.scope == "user"
    assert exc.value.retry_after_seconds > 0


def test_account_limit_combines_create_and_stop():
    init_db()
    clear_events()

    account = unique("account")

    policy = RateLimitPolicy(
        user_limit=100,
        user_window_seconds=600,
        account_limit=2,
        account_window_seconds=600,
    )

    check_and_record_rate_limit(
        username=unique("one"),
        account_id=account,
        action="spot_grid_create",
        policy=policy,
    )

    check_and_record_rate_limit(
        username=unique("two"),
        account_id=account,
        action="bot_stop",
        policy=policy,
    )

    with pytest.raises(
        BotControlRateLimitExceeded
    ) as exc:
        check_and_record_rate_limit(
            username=unique("three"),
            account_id=account,
            action="spot_grid_create",
            policy=policy,
        )

    assert exc.value.scope == "account"


def test_different_accounts_do_not_share_account_limit():
    init_db()
    clear_events()

    policy = RateLimitPolicy(
        user_limit=100,
        user_window_seconds=600,
        account_limit=1,
        account_window_seconds=600,
    )

    check_and_record_rate_limit(
        username=unique("one"),
        account_id=unique("account-a"),
        action="spot_grid_create",
        policy=policy,
    )

    result = check_and_record_rate_limit(
        username=unique("two"),
        account_id=unique("account-b"),
        action="spot_grid_create",
        policy=policy,
    )

    assert result["allowed"] is True


def test_reconcile_policy_can_be_user_only():
    init_db()
    clear_events()

    policy = RateLimitPolicy(
        user_limit=1,
        user_window_seconds=600,
    )

    username = unique("user")
    account = unique("account")

    check_and_record_rate_limit(
        username=username,
        account_id=account,
        action="reconcile",
        policy=policy,
    )

    with pytest.raises(
        BotControlRateLimitExceeded
    ) as exc:
        check_and_record_rate_limit(
            username=username,
            account_id=account,
            action="reconcile",
            policy=policy,
        )

    assert exc.value.scope == "user"


def test_blocked_attempt_is_not_recorded():
    init_db()
    clear_events()

    username = unique("user")
    account = unique("account")

    policy = RateLimitPolicy(
        user_limit=1,
        user_window_seconds=600,
    )

    check_and_record_rate_limit(
        username=username,
        account_id=account,
        action="reconcile",
        policy=policy,
    )

    for _ in range(2):
        with pytest.raises(
            BotControlRateLimitExceeded
        ):
            check_and_record_rate_limit(
                username=username,
                account_id=account,
                action="reconcile",
                policy=policy,
            )

    with session_scope() as db:
        rows = db.query(
            BotControlRateLimitEvent
        ).filter(
            BotControlRateLimitEvent.username
            == username
        ).all()

        assert len(rows) == 1
