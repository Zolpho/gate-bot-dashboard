from __future__ import annotations

import uuid

import pytest

from app.bot_control_audit import (
    IdempotencyConflict,
    find_matching_request,
    mark_request,
    reserve_request,
)
from app.db import init_db


def new_request_id() -> str:
    return "test-" + uuid.uuid4().hex


def test_request_reservation_is_idempotent() -> None:
    init_db()

    rid = new_request_id()

    payload = {
        "account_id": "zolnode",
        "operation": "spot_grid_create",
        "gate_payload": {
            "market": "EQTY_USDT",
            "create_params": {
                "money": "100",
            },
        },
    }

    first, created = reserve_request(
        request_id=rid,
        account_id="zolnode",
        username="zolnode",
        action="spot_grid_create",
        payload=payload,
    )

    assert created is True
    assert first["status"] == "reserved"

    second, created = reserve_request(
        request_id=rid,
        account_id="zolnode",
        username="zolnode",
        action="spot_grid_create",
        payload=payload,
    )

    assert created is False
    assert second["request_id"] == rid


def test_request_id_cannot_change_payload() -> None:
    init_db()

    rid = new_request_id()

    reserve_request(
        request_id=rid,
        account_id="zolnode",
        username="zolnode",
        action="spot_grid_create",
        payload={"money": "100"},
    )

    with pytest.raises(
        IdempotencyConflict,
    ):
        reserve_request(
            request_id=rid,
            account_id="zolnode",
            username="zolnode",
            action="spot_grid_create",
            payload={"money": "200"},
        )


def test_completed_request_is_persisted() -> None:
    init_db()

    rid = new_request_id()

    reserve_request(
        request_id=rid,
        account_id="zolnode",
        username="zolnode",
        action="spot_grid_create",
        payload={"money": "100"},
    )

    mark_request(
        rid,
        status="succeeded",
        response={
            "status": "submitted",
            "strategy": {
                "strategy_id": "123456",
            },
        },
        strategy_id="123456",
        gate_status_code=200,
        completed=True,
    )

    record = find_matching_request(
        request_id=rid,
        account_id="zolnode",
        username="zolnode",
        action="spot_grid_create",
        payload={"money": "100"},
    )

    assert record is not None
    assert record["status"] == "succeeded"
    assert record["strategy_id"] == "123456"
