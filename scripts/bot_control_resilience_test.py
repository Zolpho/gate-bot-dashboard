#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any


def safety_guard() -> str:
    database_url = os.environ.get(
        "DATABASE_URL",
        "",
    )

    if (
        os.environ.get(
            "BOT_CONTROL_RESILIENCE_ALLOW"
        )
        != "YES"
    ):
        raise SystemExit(
            "REFUSED: set "
            "BOT_CONTROL_RESILIENCE_ALLOW=YES"
        )

    if not database_url:
        raise SystemExit(
            "REFUSED: DATABASE_URL must be "
            "explicitly supplied."
        )

    if "bot_control_resilience" not in database_url:
        raise SystemExit(
            "REFUSED: resilience DB name must contain "
            "'bot_control_resilience'."
        )

    if "gate_bots.db" in database_url:
        raise SystemExit(
            "REFUSED: production gate_bots.db "
            "must never be used."
        )

    return database_url


def names(
    run_id: str,
    suffix: str = "",
) -> tuple[str, str, str]:
    extra = f"-{suffix}" if suffix else ""

    return (
        f"resilience-{run_id}{extra}",
        f"resilience-account-{run_id}{extra}",
        f"resilience-{run_id}{extra}-request",
    )


def crash_payload(
    account_id: str,
) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "operation": "spot_grid_create",
        "gate_payload": {
            "strategy_type": "spot_grid",
            "market": "EQTY_USDT",
            "create_params": {
                "money": "100",
                "low_price": "0.00165",
                "high_price": "0.002",
                "grid_num": 10,
            },
            "test_only": True,
        },
    }


def cleanup(
    run_id: str,
) -> dict[str, int]:
    from sqlalchemy import delete

    from app.db import (
        init_db,
        session_scope,
    )
    from app.models import (
        BotControlOperationLock,
        BotControlRateLimitEvent,
        BotControlRequest,
    )

    init_db()

    account_pattern = (
        f"resilience-account-{run_id}%"
    )

    username_pattern = (
        f"resilience-{run_id}%"
    )

    request_pattern = (
        f"resilience-{run_id}%"
    )

    counts = {
        "locks": 0,
        "rate_events": 0,
        "requests": 0,
    }

    with session_scope() as db:
        result = db.execute(
            delete(
                BotControlOperationLock
            ).where(
                BotControlOperationLock
                .account_id.like(
                    account_pattern
                )
            )
        )

        counts["locks"] = int(
            result.rowcount or 0
        )

        result = db.execute(
            delete(
                BotControlRateLimitEvent
            ).where(
                BotControlRateLimitEvent
                .username.like(
                    username_pattern
                )
            )
        )

        counts["rate_events"] = int(
            result.rowcount or 0
        )

        result = db.execute(
            delete(
                BotControlRequest
            ).where(
                BotControlRequest
                .request_id.like(
                    request_pattern
                )
            )
        )

        counts["requests"] = int(
            result.rowcount or 0
        )

    return counts


def test_idempotency_concurrency(
    run_id: str,
    workers: int,
) -> dict[str, Any]:
    from app.bot_control_audit import (
        reserve_request,
    )

    username, account_id, request_id = names(
        run_id,
        "idem",
    )

    payload = crash_payload(
        account_id
    )

    barrier = Barrier(
        workers
    )

    def worker(
        _: int,
    ) -> dict[str, Any]:
        barrier.wait()

        record, created = reserve_request(
            request_id=request_id,
            account_id=account_id,
            username=username,
            action="spot_grid_create",
            payload=payload,
        )

        return {
            "created": created,
            "request_id": (
                record["request_id"]
            ),
        }

    with ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        results = list(
            pool.map(
                worker,
                range(workers),
            )
        )

    created_count = sum(
        1
        for item in results
        if item["created"]
    )

    assert created_count == 1, (
        "Idempotency race failed: "
        f"{created_count} reservations "
        "reported created=True"
    )

    assert {
        item["request_id"]
        for item in results
    } == {
        request_id
    }

    return {
        "workers": workers,
        "created": created_count,
        "replays": (
            workers - created_count
        ),
        "status": "PASS",
    }


def test_lock_concurrency(
    run_id: str,
    workers: int,
) -> dict[str, Any]:
    from app.bot_control_locks import (
        OperationLocked,
        acquire_operation_lock,
        strategy_lock_key,
    )

    username, account_id, _ = names(
        run_id,
        "lock",
    )

    strategy_id = (
        f"strategy-{run_id}"
    )

    lock_key = strategy_lock_key(
        account_id=account_id,
        strategy_type="spot_grid",
        strategy_id=strategy_id,
    )

    barrier = Barrier(
        workers
    )

    def worker(
        number: int,
    ) -> dict[str, Any]:
        owner = (
            f"resilience-{run_id}-"
            f"lock-owner-{number}"
        )

        barrier.wait()

        try:
            lock = acquire_operation_lock(
                lock_key=lock_key,
                lock_type="strategy",
                account_id=account_id,
                action="bot_stop",
                owner_request_id=owner,
                username=username,
                strategy_id=strategy_id,
                strategy_type="spot_grid",
                market="EQTY_USDT",
            )

            return {
                "result": "acquired",
                "owner": (
                    lock[
                        "owner_request_id"
                    ]
                ),
            }

        except OperationLocked as exc:
            return {
                "result": "blocked",
                "owner": (
                    exc.lock[
                        "owner_request_id"
                    ]
                ),
            }

    with ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        results = list(
            pool.map(
                worker,
                range(workers),
            )
        )

    acquired = [
        item
        for item in results
        if item["result"]
        == "acquired"
    ]

    blocked = [
        item
        for item in results
        if item["result"]
        == "blocked"
    ]

    assert len(acquired) == 1, (
        "Lock race failed: expected exactly "
        "one lock owner, got "
        f"{len(acquired)}"
    )

    winner = acquired[0]["owner"]

    assert len(blocked) == (
        workers - 1
    )

    assert all(
        item["owner"] == winner
        for item in blocked
    )

    return {
        "workers": workers,
        "winner": winner,
        "blocked": len(blocked),
        "status": "PASS",
    }


def test_rate_limit_concurrency(
    run_id: str,
    workers: int,
) -> dict[str, Any]:
    from sqlalchemy import (
        func,
        select,
    )

    from app.bot_control_rate_limit import (
        BotControlRateLimitExceeded,
        RateLimitPolicy,
        check_and_record_rate_limit,
    )
    from app.db import session_scope
    from app.models import (
        BotControlRateLimitEvent,
    )

    username, account_id, _ = names(
        run_id,
        "rate",
    )

    limit = min(
        5,
        workers - 1,
    )

    policy = RateLimitPolicy(
        user_limit=limit,
        user_window_seconds=600,
        account_limit=100,
        account_window_seconds=600,
    )

    barrier = Barrier(
        workers
    )

    def worker(
        _: int,
    ) -> str:
        barrier.wait()

        try:
            check_and_record_rate_limit(
                username=username,
                account_id=account_id,
                action="spot_grid_create",
                policy=policy,
            )

            return "allowed"

        except BotControlRateLimitExceeded:
            return "blocked"

    with ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        results = list(
            pool.map(
                worker,
                range(workers),
            )
        )

    allowed = results.count(
        "allowed"
    )

    blocked = results.count(
        "blocked"
    )

    with session_scope() as db:
        stored = int(
            db.scalar(
                select(
                    func.count(
                        BotControlRateLimitEvent.id
                    )
                ).where(
                    BotControlRateLimitEvent.username
                    == username
                )
            )
            or 0
        )

    assert allowed == limit, (
        "Rate limiter overshoot: "
        f"expected {limit}, got {allowed}"
    )

    assert stored == limit, (
        "Persistent rate rows mismatch: "
        f"expected {limit}, got {stored}"
    )

    assert blocked == (
        workers - limit
    )

    return {
        "workers": workers,
        "limit": limit,
        "allowed": allowed,
        "blocked": blocked,
        "stored_events": stored,
        "status": "PASS",
    }


def test_combined_concurrency(
    run_id: str,
    workers: int,
) -> dict[str, Any]:
    from app.bot_control_audit import (
        mark_request,
        reserve_request,
    )
    from app.bot_control_locks import (
        OperationLocked,
        acquire_operation_lock,
        create_intent_lock,
    )
    from app.bot_control_rate_limit import (
        BotControlRateLimitExceeded,
        RateLimitPolicy,
        check_and_record_rate_limit,
    )

    username, account_id, _ = names(
        run_id,
        "combined",
    )

    payload = crash_payload(
        account_id
    )

    gate_payload = (
        payload["gate_payload"]
    )

    lock_key, intent_hash = (
        create_intent_lock(
            account_id=account_id,
            gate_payload=gate_payload,
        )
    )

    account_limit = min(
        6,
        workers - 1,
    )

    policy = RateLimitPolicy(
        user_limit=100,
        user_window_seconds=600,
        account_limit=account_limit,
        account_window_seconds=600,
    )

    barrier = Barrier(
        workers
    )

    def worker(
        number: int,
    ) -> dict[str, Any]:
        request_id = (
            f"resilience-{run_id}-"
            f"combined-{number}"
        )

        barrier.wait()

        try:
            check_and_record_rate_limit(
                username=username,
                account_id=account_id,
                action="spot_grid_create",
                policy=policy,
            )

        except BotControlRateLimitExceeded:
            return {
                "result": "rate_blocked",
                "request_id": request_id,
            }

        record, created = reserve_request(
            request_id=request_id,
            account_id=account_id,
            username=username,
            action="spot_grid_create",
            payload=payload,
        )

        assert created is True

        try:
            acquire_operation_lock(
                lock_key=lock_key,
                lock_type="create_intent",
                account_id=account_id,
                action="spot_grid_create",
                owner_request_id=request_id,
                username=username,
                strategy_type="spot_grid",
                market="EQTY_USDT",
                intent_hash=intent_hash,
            )

            mark_request(
                request_id,
                status="submitting",
            )

            return {
                "result": "lock_owner",
                "request_id": (
                    record["request_id"]
                ),
            }

        except OperationLocked:
            mark_request(
                request_id,
                status="blocked",
                error=(
                    "Synthetic concurrency "
                    "lock collision"
                ),
                completed=True,
            )

            return {
                "result": "lock_blocked",
                "request_id": request_id,
            }

    with ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        results = list(
            pool.map(
                worker,
                range(workers),
            )
        )

    rate_blocked = sum(
        item["result"] == "rate_blocked"
        for item in results
    )

    lock_owner = sum(
        item["result"] == "lock_owner"
        for item in results
    )

    lock_blocked = sum(
        item["result"] == "lock_blocked"
        for item in results
    )

    assert lock_owner == 1

    assert (
        lock_owner + lock_blocked
        == account_limit
    )

    assert rate_blocked == (
        workers - account_limit
    )

    return {
        "workers": workers,
        "account_limit": account_limit,
        "lock_owner": lock_owner,
        "lock_blocked": lock_blocked,
        "rate_blocked": rate_blocked,
        "status": "PASS",
    }


def scenario_concurrency(
    run_id: str,
    workers: int,
) -> None:
    from app.db import init_db

    if workers < 6:
        raise SystemExit(
            "--workers must be at least 6"
        )

    init_db()

    cleanup(
        run_id
    )

    try:
        result = {
            "scenario": "concurrency",
            "run_id": run_id,
            "idempotency": (
                test_idempotency_concurrency(
                    run_id,
                    workers,
                )
            ),
            "locking": (
                test_lock_concurrency(
                    run_id,
                    workers,
                )
            ),
            "rate_limiting": (
                test_rate_limit_concurrency(
                    run_id,
                    workers,
                )
            ),
            "combined": (
                test_combined_concurrency(
                    run_id,
                    workers,
                )
            ),
            "overall": "PASS",
        }

        print(
            json.dumps(
                result,
                indent=2,
                sort_keys=True,
            )
        )

    finally:
        cleanup(
            run_id
        )


def scenario_seed(
    run_id: str,
) -> None:
    from app.bot_control_audit import (
        get_request,
        mark_request,
        reserve_request,
    )
    from app.bot_control_locks import (
        acquire_operation_lock,
        create_intent_lock,
        get_operation_lock,
    )
    from app.bot_control_rate_limit import (
        RateLimitPolicy,
        check_and_record_rate_limit,
    )
    from app.db import init_db

    init_db()

    cleanup(
        run_id
    )

    username, account_id, request_id = names(
        run_id,
        "crash",
    )

    payload = crash_payload(
        account_id
    )

    gate_payload = (
        payload["gate_payload"]
    )

    policy = RateLimitPolicy(
        user_limit=1,
        user_window_seconds=3600,
        account_limit=1,
        account_window_seconds=3600,
    )

    rate = check_and_record_rate_limit(
        username=username,
        account_id=account_id,
        action="spot_grid_create",
        policy=policy,
    )

    record, created = reserve_request(
        request_id=request_id,
        account_id=account_id,
        username=username,
        action="spot_grid_create",
        payload=payload,
    )

    assert created is True

    lock_key, intent_hash = (
        create_intent_lock(
            account_id=account_id,
            gate_payload=gate_payload,
        )
    )

    lock = acquire_operation_lock(
        lock_key=lock_key,
        lock_type="create_intent",
        account_id=account_id,
        action="spot_grid_create",
        owner_request_id=request_id,
        username=username,
        strategy_type="spot_grid",
        market="EQTY_USDT",
        intent_hash=intent_hash,
    )

    # This represents the dangerous crash window:
    # durable request + durable lock exist and the app
    # has entered "submitting", but this synthetic test
    # never sends anything to Gate.
    mark_request(
        request_id,
        status="submitting",
        error=(
            "Synthetic crash-test state only. "
            "No Gate request was sent."
        ),
    )

    record = get_request(
        request_id
    )

    print(
        json.dumps(
            {
                "scenario": "seed",
                "run_id": run_id,
                "request_id": request_id,
                "request_status": (
                    record["status"]
                ),
                "lock_key": lock_key,
                "lock_state": (
                    lock["state"]
                ),
                "rate_event": rate,
                "gate_write_performed": False,
                "safe_to_kill_container": True,
            },
            indent=2,
            sort_keys=True,
        )
    )


def scenario_verify(
    run_id: str,
) -> None:
    from sqlalchemy import (
        func,
        select,
    )

    from app.bot_control_audit import (
        get_request,
        reserve_request,
    )
    from app.bot_control_locks import (
        OperationLocked,
        acquire_operation_lock,
        create_intent_lock,
        get_operation_lock,
    )
    from app.bot_control_rate_limit import (
        BotControlRateLimitExceeded,
        RateLimitPolicy,
        check_and_record_rate_limit,
    )
    from app.db import (
        init_db,
        session_scope,
    )
    from app.models import (
        BotControlRateLimitEvent,
    )

    init_db()

    username, account_id, request_id = names(
        run_id,
        "crash",
    )

    payload = crash_payload(
        account_id
    )

    gate_payload = (
        payload["gate_payload"]
    )

    lock_key, intent_hash = (
        create_intent_lock(
            account_id=account_id,
            gate_payload=gate_payload,
        )
    )

    record = get_request(
        request_id
    )

    assert record is not None, (
        "Request disappeared after restart"
    )

    lock = get_operation_lock(
        lock_key
    )

    assert lock is not None, (
        "Operation lock disappeared after restart"
    )

    assert (
        lock["owner_request_id"]
        == request_id
    )

    assert lock["state"] == "held"

    with session_scope() as db:
        rate_count = int(
            db.scalar(
                select(
                    func.count(
                        BotControlRateLimitEvent.id
                    )
                ).where(
                    BotControlRateLimitEvent.username
                    == username,
                    BotControlRateLimitEvent.account_id
                    == account_id,
                    BotControlRateLimitEvent.action
                    == "spot_grid_create",
                )
            )
            or 0
        )

    assert rate_count == 1, (
        "Rate-limit event did not survive restart"
    )

    # Same request_id must remain an idempotent replay.
    replay, created = reserve_request(
        request_id=request_id,
        account_id=account_id,
        username=username,
        action="spot_grid_create",
        payload=payload,
    )

    assert created is False
    assert (
        replay["request_id"]
        == request_id
    )

    # A different request must not bypass the
    # surviving operation lock.
    competing_owner = (
        f"resilience-{run_id}-"
        "post-crash-competitor"
    )

    lock_blocked = False

    try:
        acquire_operation_lock(
            lock_key=lock_key,
            lock_type="create_intent",
            account_id=account_id,
            action="spot_grid_create",
            owner_request_id=(
                competing_owner
            ),
            username=username,
            strategy_type="spot_grid",
            market="EQTY_USDT",
            intent_hash=intent_hash,
        )

    except OperationLocked as exc:
        lock_blocked = True

        assert (
            exc.lock[
                "owner_request_id"
            ]
            == request_id
        )

    assert lock_blocked is True

    # Persistent rate limiter must also remember the
    # pre-crash request.
    policy = RateLimitPolicy(
        user_limit=1,
        user_window_seconds=3600,
        account_limit=1,
        account_window_seconds=3600,
    )

    rate_blocked = False
    retry_after = None

    try:
        check_and_record_rate_limit(
            username=username,
            account_id=account_id,
            action="spot_grid_create",
            policy=policy,
        )

    except BotControlRateLimitExceeded as exc:
        rate_blocked = True
        retry_after = (
            exc.retry_after_seconds
        )

    assert rate_blocked is True

    print(
        json.dumps(
            {
                "scenario": "verify",
                "run_id": run_id,
                "request_persisted": True,
                "request_status": (
                    record["status"]
                ),
                "idempotent_replay": True,
                "lock_persisted": True,
                "competing_operation_blocked": True,
                "rate_event_count": rate_count,
                "rate_limit_persisted": True,
                "retry_after_seconds": retry_after,
                "gate_write_performed": False,
                "durability": "PASS",
                "automatic_crash_classification": (
                    "NOT_PRESENT"
                    if record["status"]
                    == "submitting"
                    else record["status"]
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    database_url = safety_guard()

    parser = argparse.ArgumentParser(
        description=(
            "Safe Bot Control concurrency and "
            "crash-recovery test harness"
        )
    )

    parser.add_argument(
        "scenario",
        choices=(
            "concurrency",
            "seed",
            "verify",
            "cleanup",
        ),
    )

    parser.add_argument(
        "--run-id",
        required=True,
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=12,
    )

    args = parser.parse_args()

    print(
        f"Using isolated DB: {database_url}",
        file=sys.stderr,
    )

    if args.scenario == "concurrency":
        scenario_concurrency(
            args.run_id,
            args.workers,
        )

    elif args.scenario == "seed":
        scenario_seed(
            args.run_id
        )

    elif args.scenario == "verify":
        scenario_verify(
            args.run_id
        )

    elif args.scenario == "cleanup":
        result = cleanup(
            args.run_id
        )

        print(
            json.dumps(
                {
                    "scenario": "cleanup",
                    "run_id": args.run_id,
                    "deleted": result,
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
