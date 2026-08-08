from __future__ import annotations

import uuid

from sqlalchemy import (
    delete,
    select,
)

from app.bot_control_audit import (
    get_request,
    reserve_request,
)
from app.bot_control_locks import (
    acquire_operation_lock,
    create_intent_lock,
    get_operation_lock_for_request,
)
from app.bot_control_recovery import (
    recover_stale_bot_control_requests,
)
from app.db import (
    init_db,
    session_scope,
)
from app.models import (
    BotControlOperationLock,
    BotControlRequest,
)


def identity(
    suffix: str,
) -> tuple[str, str, str]:
    token = uuid.uuid4().hex

    return (
        f"recovery-user-{token}",
        f"recovery-account-{token}",
        f"recovery-{suffix}-{token}",
    )


def payload(
    account_id: str,
) -> dict:
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


def set_status(
    request_id: str,
    status: str,
) -> None:
    with session_scope() as db:
        row = db.scalar(
            select(
                BotControlRequest
            ).where(
                BotControlRequest.request_id
                == request_id
            )
        )

        assert row is not None

        row.status = status
        db.flush()


def cleanup(
    request_id: str,
) -> None:
    with session_scope() as db:
        db.execute(
            delete(
                BotControlOperationLock
            ).where(
                BotControlOperationLock
                .owner_request_id
                == request_id
            )
        )

        db.execute(
            delete(
                BotControlRequest
            ).where(
                BotControlRequest
                .request_id
                == request_id
            )
        )


def test_submitting_request_becomes_uncertain_and_lock_survives():
    init_db()

    username, account_id, request_id = (
        identity("submitting")
    )

    try:
        body = payload(
            account_id
        )

        _, created = reserve_request(
            request_id=request_id,
            account_id=account_id,
            username=username,
            action="spot_grid_create",
            payload=body,
        )

        assert created is True

        lock_key, intent_hash = (
            create_intent_lock(
                account_id=account_id,
                gate_payload=body[
                    "gate_payload"
                ],
            )
        )

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

        set_status(
            request_id,
            "submitting",
        )

        result = (
            recover_stale_bot_control_requests()
        )

        record = get_request(
            request_id
        )

        lock = (
            get_operation_lock_for_request(
                request_id
            )
        )

        assert record is not None
        assert record["status"] == "uncertain"
        assert record["completed_at"] is not None

        assert (
            "Automatic retry was NOT performed"
            in record["error"]
        )

        assert lock is not None
        assert lock["state"] == "held"
        assert (
            lock["owner_request_id"]
            == request_id
        )

        item = next(
            item
            for item in result["items"]
            if item["request_id"]
            == request_id
        )

        assert (
            item["previous_status"]
            == "submitting"
        )

        assert (
            item["new_status"]
            == "uncertain"
        )

        assert (
            item["automatic_retry"]
            is False
        )

        assert (
            item[
                "automatic_lock_release"
            ]
            is False
        )

    finally:
        cleanup(
            request_id
        )


def test_reserved_request_without_lock_becomes_uncertain():
    init_db()

    username, account_id, request_id = (
        identity("reserved")
    )

    try:
        body = payload(
            account_id
        )

        _, created = reserve_request(
            request_id=request_id,
            account_id=account_id,
            username=username,
            action="spot_grid_create",
            payload=body,
        )

        assert created is True

        result = (
            recover_stale_bot_control_requests()
        )

        record = get_request(
            request_id
        )

        assert record is not None
        assert record["status"] == "uncertain"

        item = next(
            item
            for item in result["items"]
            if item["request_id"]
            == request_id
        )

        assert (
            item["previous_status"]
            == "reserved"
        )

        assert (
            item["operation_lock"]
            is None
        )

    finally:
        cleanup(
            request_id
        )


def test_recovery_is_idempotent():
    init_db()

    username, account_id, request_id = (
        identity("idempotent")
    )

    try:
        body = payload(
            account_id
        )

        reserve_request(
            request_id=request_id,
            account_id=account_id,
            username=username,
            action="spot_grid_create",
            payload=body,
        )

        first = (
            recover_stale_bot_control_requests()
        )

        second = (
            recover_stale_bot_control_requests()
        )

        assert any(
            item["request_id"]
            == request_id
            for item in first["items"]
        )

        assert not any(
            item["request_id"]
            == request_id
            for item in second["items"]
        )

        assert (
            get_request(
                request_id
            )["status"]
            == "uncertain"
        )

    finally:
        cleanup(
            request_id
        )


def test_disabled_recovery_does_nothing():
    init_db()

    username, account_id, request_id = (
        identity("disabled")
    )

    try:
        body = payload(
            account_id
        )

        reserve_request(
            request_id=request_id,
            account_id=account_id,
            username=username,
            action="spot_grid_create",
            payload=body,
        )

        result = (
            recover_stale_bot_control_requests(
                enabled=False
            )
        )

        assert result["enabled"] is False
        assert result["recovered"] == 0

        assert (
            get_request(
                request_id
            )["status"]
            == "reserved"
        )

    finally:
        cleanup(
            request_id
        )
