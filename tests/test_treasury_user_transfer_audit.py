from decimal import Decimal
from uuid import uuid4

from app import treasury_transfer_audit as audit
from app.db import init_db
from app.treasury_transfer import gate_client_order_id

# These tests exercise the real Treasury audit persistence layer.
# Ensure the configured pytest database schema exists independently of
# test execution order.
init_db()


def test_user_transfer_success_does_not_create_ownership_credit(
    monkeypatch,
):
    request_id = (
        "user-audit-no-ownership-"
        + uuid4().hex
    )

    ownership_calls = []

    monkeypatch.setattr(
        audit,
        "ensure_internal_transfer_credit_for_row",
        lambda _db, row: ownership_calls.append(
            row.request_id
        ),
    )

    record, created = (
        audit.reserve_user_account_transfer(
            request_id=request_id,
            source_account_id="arnold",
            destination_account_id="eqtydao",
            username="arnold-user",
            currency="USDT",
            amount=Decimal("1"),
            payload={
                "operation": "user_account_transfer",
                "transfer_path": (
                    "subaccount_to_subaccount"
                ),
            },
            client_order_id="",
        )
    )

    assert created is True
    assert record["direction"] == (
        "user_account_transfer"
    )

    audit.mark_transfer_request(
        request_id,
        status="success",
        response={"tx_id": "123"},
        gate_transfer_id="123",
        write_performed=True,
        completed=True,
    )

    assert ownership_calls == []


def test_existing_sub_to_main_success_still_creates_ownership_credit(
    monkeypatch,
):
    request_id = (
        "legacy-audit-ownership-"
        + uuid4().hex
    )

    ownership_calls = []

    monkeypatch.setattr(
        audit,
        "ensure_internal_transfer_credit_for_row",
        lambda _db, row: ownership_calls.append(
            row.request_id
        ),
    )

    record, created = audit.reserve_live_transfer(
        request_id=request_id,
        source_account_id="arnold",
        destination_account_id="zolnode",
        username="admin",
        currency="USDT",
        amount=Decimal("1"),
        payload={
            "operation": "subaccount_to_main",
        },
    )

    assert created is True
    assert record["direction"] == "from"

    audit.mark_transfer_request(
        request_id,
        status="success",
        response={"tx_id": "456"},
        gate_transfer_id="456",
        write_performed=True,
        completed=True,
    )

    assert ownership_calls == [request_id]


def test_sub_to_sub_reservation_has_no_fake_client_order_id():
    request_id = (
        "user-audit-sub-sub-"
        + uuid4().hex
    )

    record, created = (
        audit.reserve_user_account_transfer(
            request_id=request_id,
            source_account_id="arnold",
            destination_account_id="eqtydao",
            username="arnold-user",
            currency="USDT",
            amount=Decimal("1"),
            payload={
                "operation": "user_account_transfer",
                "transfer_path": (
                    "subaccount_to_subaccount"
                ),
            },
            client_order_id="",
        )
    )

    assert created is True
    assert record["client_order_id"] is None


def test_main_sub_reservation_keeps_sent_client_order_id():
    request_id = (
        "user-audit-main-sub-"
        + uuid4().hex
    )

    client_order_id = gate_client_order_id(
        request_id
    )

    record, created = (
        audit.reserve_user_account_transfer(
            request_id=request_id,
            source_account_id="zolnode",
            destination_account_id="arnold",
            username="main-user",
            currency="USDT",
            amount=Decimal("1"),
            payload={
                "operation": "user_account_transfer",
                "transfer_path": (
                    "main_to_subaccount"
                ),
            },
            client_order_id=client_order_id,
        )
    )

    assert created is True
    assert (
        record["client_order_id"]
        == client_order_id
    )
