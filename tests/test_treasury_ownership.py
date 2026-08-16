from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select

from app.db import init_db, session_scope
from app.migrations import migrate_database
from app.models import (
    TreasuryOwnershipLedgerEntry,
    TreasuryTransferRequest,
)
from app.treasury_ownership import (
    backfill_internal_transfer_credits,
    internal_transfer_credit_event_id,
    list_ownership_entries,
    ownership_balances,
)
from app.treasury_transfer_audit import (
    mark_transfer_request,
    record_simulation,
    reserve_live_transfer,
)


@pytest.fixture(
    scope="module",
    autouse=True,
)
def _initialize_database():
    init_db()


def _request_id(prefix: str) -> str:
    return (
        f"{prefix}-{uuid4().hex}"
    )


def _live_payload(
    source_account_id: str,
) -> dict:
    return {
        "operation": "subaccount_to_main",
        "source_account_id": (
            source_account_id
        ),
        "destination_account_id": "zolnode",
        "gate_payload": {
            "currency": "USDT",
            "direction": "from",
        },
    }


def test_success_creates_exactly_one_credit() -> None:
    account_id = (
        "owner-" + uuid4().hex[:12]
    )

    request_id = _request_id(
        "ownership-success"
    )

    reserve_live_transfer(
        request_id=request_id,
        source_account_id=account_id,
        destination_account_id="zolnode",
        username="ownership-test",
        currency="USDT",
        amount=Decimal("3.25"),
        payload=_live_payload(account_id),
    )

    first = mark_transfer_request(
        request_id,
        status="success",
        response={
            "status": "SUCCESS",
            "tx_id": "ownership-test-tx",
        },
        gate_transfer_id="ownership-test-tx",
        write_performed=True,
        completed=True,
    )

    assert first["status"] == "success"

    # Idempotent repeated status persistence must not create
    # a second economic ownership credit.
    mark_transfer_request(
        request_id,
        status="success",
        response={
            "status": "SUCCESS",
            "tx_id": "ownership-test-tx",
        },
        gate_transfer_id="ownership-test-tx",
        write_performed=True,
        completed=True,
    )

    entries = list_ownership_entries(
        account_ids={account_id}
    )

    matching = [
        item
        for item in entries
        if item["source_request_id"]
        == request_id
    ]

    assert len(matching) == 1

    entry = matching[0]

    assert (
        entry["event_id"]
        == internal_transfer_credit_event_id(
            request_id
        )
    )

    assert (
        entry["entry_type"]
        == "internal_transfer_credit"
    )

    assert entry["owner_account_id"] == account_id
    assert entry["custody_account_id"] == "zolnode"
    assert entry["currency"] == "USDT"
    assert entry["delta_amount"] == "3.25"


def test_simulation_never_creates_credit() -> None:
    account_id = (
        "simowner-" + uuid4().hex[:10]
    )

    request_id = _request_id(
        "ownership-simulation"
    )

    record_simulation(
        request_id=request_id,
        source_account_id=account_id,
        destination_account_id="zolnode",
        username="ownership-test",
        currency="USDT",
        amount=Decimal("9"),
        payload={
            "operation": "subaccount_to_main",
        },
        response={
            "simulation": True,
        },
    )

    backfill_internal_transfer_credits()

    entries = list_ownership_entries(
        account_ids={account_id}
    )

    assert not any(
        item["source_request_id"]
        == request_id
        for item in entries
    )


@pytest.mark.parametrize(
    "status",
    [
        "failed",
        "rejected",
        "pending",
        "uncertain",
        "attention",
    ],
)
def test_non_success_status_has_no_credit(
    status: str,
) -> None:
    account_id = (
        "nostatus-" + uuid4().hex[:10]
    )

    request_id = _request_id(
        f"ownership-{status}"
    )

    reserve_live_transfer(
        request_id=request_id,
        source_account_id=account_id,
        destination_account_id="zolnode",
        username="ownership-test",
        currency="USDT",
        amount=Decimal("2"),
        payload=_live_payload(account_id),
    )

    mark_transfer_request(
        request_id,
        status=status,
        write_performed=True,
        completed=(
            status
            in {"failed", "rejected"}
        ),
    )

    entries = list_ownership_entries(
        account_ids={account_id}
    )

    assert not any(
        item["source_request_id"]
        == request_id
        for item in entries
    )


def test_balance_aggregates_by_owner() -> None:
    account_id = (
        "aggregate-" + uuid4().hex[:10]
    )

    for amount in (
        Decimal("1.25"),
        Decimal("2.75"),
    ):
        request_id = _request_id(
            "ownership-aggregate"
        )

        reserve_live_transfer(
            request_id=request_id,
            source_account_id=account_id,
            destination_account_id="zolnode",
            username="ownership-test",
            currency="USDT",
            amount=amount,
            payload=_live_payload(account_id),
        )

        mark_transfer_request(
            request_id,
            status="success",
            response={
                "status": "SUCCESS",
            },
            write_performed=True,
            completed=True,
        )

    balances = ownership_balances(
        account_ids={account_id}
    )

    assert balances == [
        {
            "owner_account_id": account_id,
            "custody_account_id": "zolnode",
            "currency": "USDT",
            "main_held_amount": "4",
        }
    ]


def test_runtime_backfill_repairs_missing_credit() -> None:
    account_id = (
        "repair-" + uuid4().hex[:10]
    )

    request_id = _request_id(
        "ownership-repair"
    )

    reserve_live_transfer(
        request_id=request_id,
        source_account_id=account_id,
        destination_account_id="zolnode",
        username="ownership-test",
        currency="USDT",
        amount=Decimal("5"),
        payload=_live_payload(account_id),
    )

    mark_transfer_request(
        request_id,
        status="success",
        response={
            "status": "SUCCESS",
        },
        write_performed=True,
        completed=True,
    )

    # Synthetic corruption/legacy state for repair testing.
    # Application code itself exposes no ledger delete API.
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryOwnershipLedgerEntry
            ).where(
                TreasuryOwnershipLedgerEntry
                .source_request_id
                == request_id
            )
        )

        assert row is not None
        db.delete(row)

    first = backfill_internal_transfer_credits()
    second = backfill_internal_transfer_credits()

    assert first["created"] >= 1
    assert second["created"] == 0

    entries = list_ownership_entries(
        account_ids={account_id}
    )

    matching = [
        item
        for item in entries
        if item["source_request_id"]
        == request_id
    ]

    assert len(matching) == 1
    assert matching[0]["delta_amount"] == "5"


def test_migration_backfills_existing_success(
    tmp_path,
) -> None:
    db_path = (
        tmp_path
        / "treasury-ownership.db"
    )

    engine = create_engine(
        f"sqlite:///{db_path}"
    )

    # Reproduce a pre-ledger database containing one
    # definitive successful internal transfer.
    TreasuryTransferRequest.__table__.create(
        engine
    )

    request_id = _request_id(
        "ownership-migration"
    )

    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            TreasuryTransferRequest
            .__table__
            .insert()
            .values(
                request_id=request_id,
                source_account_id="arnold",
                destination_account_id="zolnode",
                username="arnold",
                direction="from",
                currency="USDT",
                amount=Decimal("1"),
                status="success",
                request_hash="x" * 64,
                request_json=(
                    '{"destination_account_id":"zolnode",'
                    '"operation":"subaccount_to_main",'
                    '"source_account_id":"arnold"}'
                ),
                response_json=(
                    '{"status":"SUCCESS"}'
                ),
                client_order_id=(
                    "ownership-migration-client"
                ),
                gate_transfer_id="12345",
                gate_label="",
                error="",
                simulation=False,
                write_performed=True,
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
        )

    migrate_database(engine)

    with engine.connect() as connection:
        rows = connection.execute(
            TreasuryOwnershipLedgerEntry
            .__table__
            .select()
        ).mappings().all()

    assert len(rows) == 1

    row = rows[0]

    assert (
        row["event_id"]
        == internal_transfer_credit_event_id(
            request_id
        )
    )

    assert row["owner_account_id"] == "arnold"
    assert row["custody_account_id"] == "zolnode"
    assert row["currency"] == "USDT"
    assert Decimal(row["delta_amount"]) == Decimal("1")

    # Running the migration again must remain idempotent.
    migrate_database(engine)

    with engine.connect() as connection:
        rows_again = connection.execute(
            TreasuryOwnershipLedgerEntry
            .__table__
            .select()
        ).mappings().all()

    assert len(rows_again) == 1

    engine.dispose()


def test_ownership_api_is_account_scoped() -> None:
    from app.api.treasury import (
        treasury_ownership_balances,
        treasury_ownership_ledger,
    )
    from app.security import DashboardUser

    owner_a = (
        "scope-a-" + uuid4().hex[:10]
    )
    owner_b = (
        "scope-b-" + uuid4().hex[:10]
    )

    for owner in (owner_a, owner_b):
        request_id = _request_id(
            "ownership-scope"
        )

        reserve_live_transfer(
            request_id=request_id,
            source_account_id=owner,
            destination_account_id="zolnode",
            username="ownership-test",
            currency="USDT",
            amount=Decimal("1"),
            payload=_live_payload(owner),
        )

        mark_transfer_request(
            request_id,
            status="success",
            response={
                "status": "SUCCESS",
            },
            write_performed=True,
            completed=True,
        )

    user = DashboardUser(
        username="scope-user",
        role="account_operator",
        account_ids=(owner_a,),
    )

    balances = treasury_ownership_balances(
        user=user,
    )

    ledger = treasury_ownership_ledger(
        user=user,
        limit=200,
    )

    assert balances["items"]
    assert ledger["items"]

    assert {
        item["owner_account_id"]
        for item in balances["items"]
    } == {owner_a}

    assert {
        item["owner_account_id"]
        for item in ledger["items"]
    } == {owner_a}


def test_ownership_api_super_admin_can_see_all() -> None:
    from app.api.treasury import (
        treasury_ownership_ledger,
    )
    from app.security import DashboardUser

    owner = (
        "scope-admin-" + uuid4().hex[:10]
    )

    request_id = _request_id(
        "ownership-admin"
    )

    reserve_live_transfer(
        request_id=request_id,
        source_account_id=owner,
        destination_account_id="zolnode",
        username="ownership-test",
        currency="USDT",
        amount=Decimal("2"),
        payload=_live_payload(owner),
    )

    mark_transfer_request(
        request_id,
        status="success",
        response={
            "status": "SUCCESS",
        },
        write_performed=True,
        completed=True,
    )

    user = DashboardUser(
        username="scope-admin",
        role="super_admin",
        account_ids=(),
    )

    ledger = treasury_ownership_ledger(
        user=user,
        limit=500,
    )

    assert any(
        item["owner_account_id"] == owner
        and item["source_request_id"]
        == request_id
        for item in ledger["items"]
    )


def test_ownership_api_custodian_can_see_held_funds() -> None:
    from app.api.treasury import (
        treasury_ownership_balances,
        treasury_ownership_ledger,
    )
    from app.security import DashboardUser

    owner_a = (
        "custody-a-" + uuid4().hex[:10]
    )
    owner_b = (
        "custody-b-" + uuid4().hex[:10]
    )

    request_ids = set()

    for owner in (owner_a, owner_b):
        request_id = _request_id(
            "custody-scope"
        )
        request_ids.add(request_id)

        reserve_live_transfer(
            request_id=request_id,
            source_account_id=owner,
            destination_account_id="zolnode",
            username="ownership-test",
            currency="USDT",
            amount=Decimal("1"),
            payload=_live_payload(owner),
        )

        mark_transfer_request(
            request_id,
            status="success",
            response={
                "status": "SUCCESS",
            },
            write_performed=True,
            completed=True,
        )

    # The custodian must see funds it physically holds,
    # even though another account is the economic owner.
    custodian_user = DashboardUser(
        username="zolnode-user",
        role="account_operator",
        account_ids=("zolnode",),
    )

    balances = treasury_ownership_balances(
        user=custodian_user,
    )

    ledger = treasury_ownership_ledger(
        user=custodian_user,
        limit=500,
    )

    balance_owners = {
        item["owner_account_id"]
        for item in balances["items"]
    }

    assert owner_a in balance_owners
    assert owner_b in balance_owners

    ledger_request_ids = {
        item["source_request_id"]
        for item in ledger["items"]
    }

    assert request_ids.issubset(
        ledger_request_ids
    )

    # An unrelated account must still see none
    # of these ownership records.
    unrelated_user = DashboardUser(
        username="unrelated-user",
        role="account_operator",
        account_ids=(
            "unrelated-" + uuid4().hex[:10],
        ),
    )

    unrelated_balances = (
        treasury_ownership_balances(
            user=unrelated_user,
        )
    )

    unrelated_ledger = (
        treasury_ownership_ledger(
            user=unrelated_user,
            limit=500,
        )
    )

    assert owner_a not in {
        item["owner_account_id"]
        for item in unrelated_balances["items"]
    }

    assert owner_b not in {
        item["owner_account_id"]
        for item in unrelated_balances["items"]
    }

    assert request_ids.isdisjoint(
        {
            item["source_request_id"]
            for item in unrelated_ledger["items"]
        }
    )


def test_transfer_request_detail_is_readable_by_custodian() -> None:
    from fastapi import HTTPException

    from app.api.treasury import (
        treasury_transfer_request_detail,
    )
    from app.security import DashboardUser

    owner = (
        "detail-owner-" + uuid4().hex[:10]
    )

    request_id = _request_id(
        "detail-custody"
    )

    reserve_live_transfer(
        request_id=request_id,
        source_account_id=owner,
        destination_account_id="zolnode",
        username="ownership-test",
        currency="USDT",
        amount=Decimal("1"),
        payload=_live_payload(owner),
    )

    mark_transfer_request(
        request_id,
        status="success",
        response={
            "status": "SUCCESS",
        },
        write_performed=True,
        completed=True,
    )

    owner_user = DashboardUser(
        username="owner-user",
        role="account_operator",
        account_ids=(owner,),
    )

    custodian_user = DashboardUser(
        username="custodian-user",
        role="account_operator",
        account_ids=("zolnode",),
    )

    unrelated_user = DashboardUser(
        username="unrelated-user",
        role="account_operator",
        account_ids=(
            "unrelated-" + uuid4().hex[:10],
        ),
    )

    super_admin = DashboardUser(
        username="scope-admin",
        role="super_admin",
        account_ids=(),
    )

    owner_result = (
        treasury_transfer_request_detail(
            request_id=request_id,
            user=owner_user,
        )
    )

    custodian_result = (
        treasury_transfer_request_detail(
            request_id=request_id,
            user=custodian_user,
        )
    )

    admin_result = (
        treasury_transfer_request_detail(
            request_id=request_id,
            user=super_admin,
        )
    )

    assert (
        owner_result["item"]["request_id"]
        == request_id
    )

    assert (
        custodian_result["item"]["request_id"]
        == request_id
    )

    assert (
        admin_result["item"]["request_id"]
        == request_id
    )

    with pytest.raises(HTTPException) as error:
        treasury_transfer_request_detail(
            request_id=request_id,
            user=unrelated_user,
        )

    assert error.value.status_code == 403
