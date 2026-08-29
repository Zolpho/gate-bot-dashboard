from __future__ import annotations

import base64
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.db import session_scope
from app.main import app
from app.migrations import migrate_database
from app.models import (
    TreasuryWithdrawalDestination,
)
from app.treasury_withdrawal_destinations import (
    TreasuryWithdrawalDestinationError,
    create_candidate_destination_from_recipient,
    list_destination_events,
)
from app.treasury_withdrawal_recipients import (
    create_recipient,
)


def _auth(
    username: str,
    password: str,
) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    return {
        "Authorization": f"Basic {token}",
    }


ARNOLD = _auth(
    "arnold",
    "arnold-test-password",
)

ZOLNODE = _auth(
    "zolnode",
    "zolnode-test-password",
)

ROOT = _auth(
    "rootadmin",
    "rootadmin-test-password",
)


def _candidate(
    *,
    address: str | None = None,
    chain: str = "ARBEVM",
    memo: str = "",
) -> dict[str, str]:
    return {
        "owner_account_id": "arnold",
        "currency": "USDT",
        "chain": chain,
        "address": (
            address
            or (
                "0x"
                + uuid4().hex
                + uuid4().hex[:8]
            )
        ),
        "memo": memo,
        "label": "Arnold test wallet",
    }


def test_destination_tables_migrate_on_existing_sqlite(
    tmp_path,
) -> None:
    path = tmp_path / "destination-migration.db"
    engine = create_engine(
        f"sqlite:///{path}"
    )

    migrate_database(engine)

    tables = set(
        inspect(engine).get_table_names()
    )

    assert (
        "treasury_withdrawal_destinations"
        in tables
    )

    assert (
        "treasury_withdrawal_destination_events"
        in tables
    )


def test_account_operator_can_create_and_list_own_candidate():
    with TestClient(app) as client:
        response = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=_candidate(),
        )

        assert response.status_code == 200

        body = response.json()

        assert body["created"] is True
        assert (
            body["local_write_performed"]
            is True
        )
        assert (
            body["gate_write_performed"]
            is False
        )
        assert body["item"]["status"] == "candidate"
        assert (
            body["item"]["owner_account_id"]
            == "arnold"
        )

        listed = client.get(
            (
                "/api/treasury/withdrawals/"
                "destinations"
                "?owner_account_id=arnold"
            ),
            headers=ARNOLD,
        )

        assert listed.status_code == 200

        ids = {
            item["destination_id"]
            for item in listed.json()["items"]
        }

        assert body["item"]["destination_id"] in ids

        forbidden = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json={
                **_candidate(),
                "owner_account_id": "zolnode",
            },
        )

        assert forbidden.status_code == 403


def test_account_operator_cannot_approve_destination():
    with TestClient(app) as client:
        created = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=_candidate(),
        ).json()

        destination_id = (
            created["item"]["destination_id"]
        )

        response = client.post(
            (
                "/api/treasury/withdrawals/"
                f"destinations/{destination_id}/approve"
            ),
            headers=ARNOLD,
            json={
                "confirmation": (
                    "APPROVE WITHDRAWAL DESTINATION "
                    + destination_id
                ),
                "reason": (
                    "Arnold should not be able to "
                    "self-approve this destination."
                ),
            },
        )

        assert response.status_code == 403


def test_super_admin_approval_requires_confirmation_and_is_audited():
    with TestClient(app) as client:
        created = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=_candidate(),
        ).json()

        destination_id = (
            created["item"]["destination_id"]
        )

        wrong = client.post(
            (
                "/api/treasury/withdrawals/"
                f"destinations/{destination_id}/approve"
            ),
            headers=ROOT,
            json={
                "confirmation": "APPROVE",
                "reason": (
                    "Testing exact administrative "
                    "confirmation enforcement."
                ),
            },
        )

        assert wrong.status_code == 400

        approved = client.post(
            (
                "/api/treasury/withdrawals/"
                f"destinations/{destination_id}/approve"
            ),
            headers=ROOT,
            json={
                "confirmation": (
                    "APPROVE WITHDRAWAL DESTINATION "
                    + destination_id
                ),
                "reason": (
                    "Verified manually by the Treasury "
                    "administrator for this test."
                ),
            },
        )

        assert approved.status_code == 200

        body = approved.json()

        assert body["item"]["status"] == "approved"
        assert (
            body["item"]["approved_by"]
            == "rootadmin"
        )
        assert (
            body["item"]["verification_method"]
            == "manual_admin_approval"
        )
        assert (
            body["gate_write_performed"]
            is False
        )

        detail = client.get(
            (
                "/api/treasury/withdrawals/"
                f"destinations/{destination_id}"
            ),
            headers=ARNOLD,
        )

        assert detail.status_code == 200

        actions = [
            event["action"]
            for event in detail.json()["events"]
        ]

        assert actions == [
            "created",
            "approved",
        ]


def test_revoked_destination_is_terminal():
    payload = _candidate()

    with TestClient(app) as client:
        created = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=payload,
        ).json()

        destination_id = (
            created["item"]["destination_id"]
        )

        approved = client.post(
            (
                "/api/treasury/withdrawals/"
                f"destinations/{destination_id}/approve"
            ),
            headers=ROOT,
            json={
                "confirmation": (
                    "APPROVE WITHDRAWAL DESTINATION "
                    + destination_id
                ),
                "reason": (
                    "Approve before testing the "
                    "revocation security lifecycle."
                ),
            },
        )

        assert approved.status_code == 200

        revoked = client.post(
            (
                "/api/treasury/withdrawals/"
                f"destinations/{destination_id}/revoke"
            ),
            headers=ROOT,
            json={
                "confirmation": (
                    "REVOKE WITHDRAWAL DESTINATION "
                    + destination_id
                ),
                "reason": (
                    "Destination revoked deliberately "
                    "for terminal-state testing."
                ),
            },
        )

        assert revoked.status_code == 200
        assert (
            revoked.json()["item"]["status"]
            == "revoked"
        )
        assert (
            revoked.json()["gate_write_performed"]
            is False
        )

        recreated = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=payload,
        )

        assert recreated.status_code == 409


def test_destination_identity_is_chain_and_memo_scoped():
    address = (
        "0x"
        + uuid4().hex
        + uuid4().hex[:8]
    )

    with TestClient(app) as client:
        first = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=_candidate(
                address=address,
                chain="ARBEVM",
                memo="",
            ),
        )

        second = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=_candidate(
                address=address,
                chain="ETH",
                memo="",
            ),
        )

        third = client.post(
            "/api/treasury/withdrawals/destinations",
            headers=ARNOLD,
            json=_candidate(
                address=address,
                chain="ARBEVM",
                memo="12345",
            ),
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 200

        ids = {
            first.json()["item"]["destination_id"],
            second.json()["item"]["destination_id"],
            third.json()["item"]["destination_id"],
        }

        assert len(ids) == 3

def test_destination_recipient_bridge_migrates_populated_legacy_sqlite(
    tmp_path,
) -> None:
    path = (
        tmp_path
        / "destination-recipient-bridge.db"
    )

    engine = create_engine(
        f"sqlite:///{path}"
    )

    destination_id = (
        "wd_" + uuid4().hex
    )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE treasury_withdrawal_destinations (
                id INTEGER NOT NULL PRIMARY KEY,
                destination_id VARCHAR(128) NOT NULL,
                owner_account_id VARCHAR(64) NOT NULL,
                currency VARCHAR(32) NOT NULL,
                chain VARCHAR(64) NOT NULL,
                address TEXT NOT NULL,
                memo TEXT NOT NULL,
                label VARCHAR(128) NOT NULL,
                status VARCHAR(32) NOT NULL,
                source VARCHAR(64) NOT NULL,
                verification_method VARCHAR(64) NOT NULL,
                created_by VARCHAR(64) NOT NULL,
                approved_by VARCHAR(64) NOT NULL,
                approved_at DATETIME,
                revoked_by VARCHAR(64) NOT NULL,
                revoked_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE (destination_id),
                UNIQUE (
                    owner_account_id,
                    currency,
                    chain,
                    address,
                    memo
                )
            )
            """
        )

        connection.exec_driver_sql(
            """
            INSERT INTO treasury_withdrawal_destinations
            (
                id,
                destination_id,
                owner_account_id,
                currency,
                chain,
                address,
                memo,
                label,
                status,
                source,
                verification_method,
                created_by,
                approved_by,
                approved_at,
                revoked_by,
                revoked_at,
                created_at,
                updated_at
            )
            VALUES
            (
                1,
                ?,
                'arnold',
                'USDT',
                'ETH',
                ?,
                '',
                'Legacy wallet',
                'approved',
                'manual',
                'manual_admin_approval',
                'arnold',
                'rootadmin',
                '2026-08-01T00:00:00+00:00',
                '',
                NULL,
                '2026-08-01T00:00:00+00:00',
                '2026-08-01T00:00:00+00:00'
            )
            """,
            (
                destination_id,
                (
                    "0x"
                    + uuid4().hex
                    + uuid4().hex[:8]
                ),
            ),
        )

    migrate_database(
        engine
    )

    columns = {
        item["name"]
        for item in inspect(
            engine
        ).get_columns(
            "treasury_withdrawal_destinations"
        )
    }

    assert "recipient_id" in columns

    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            """
            SELECT
                destination_id,
                status,
                recipient_id
            FROM treasury_withdrawal_destinations
            """
        ).one()

        assert row[0] == destination_id
        assert row[1] == "approved"
        assert row[2] is None

    # Migration must be idempotent.
    migrate_database(
        engine
    )

    with engine.connect() as connection:
        count = connection.exec_driver_sql(
            """
            SELECT COUNT(*)
            FROM treasury_withdrawal_destinations
            """
        ).scalar_one()

        assert count == 1


def _mixed_case_evm_address() -> str:
    payload = (
        "a"
        + uuid4().hex
        + uuid4().hex[:7]
    )

    assert len(payload) == 40

    result = []

    upper = True

    for char in payload:
        if char in "abcdef":
            result.append(
                (
                    char.upper()
                    if upper
                    else char
                )
            )
            upper = not upper
        else:
            result.append(
                char
            )

    return (
        "0x"
        + "".join(result)
    )


def test_recipient_bridge_links_case_variant_legacy_route_without_duplicate():
    recipient_address = (
        _mixed_case_evm_address()
    )

    recipient = create_recipient(
        owner_account_id="arnold",
        address=recipient_address,
        label="Legacy EVM wallet",
        username="arnold",
    )["item"]

    destination_id = (
        "wd_" + uuid4().hex
    )

    legacy_address = (
        recipient_address.lower()
    )

    with session_scope() as db:
        db.add(
            TreasuryWithdrawalDestination(
                destination_id=destination_id,
                owner_account_id="arnold",
                recipient_id=None,
                currency="USDT",
                chain="ETH",
                address=legacy_address,
                memo="",
                label="Legacy route",
                status="approved",
                source="manual",
                verification_method=(
                    "manual_admin_approval"
                ),
                created_by="arnold",
                approved_by="rootadmin",
            )
        )

    result = (
        create_candidate_destination_from_recipient(
            recipient_id=(
                recipient["recipient_id"]
            ),
            currency="USDT",
            chain="ETH",
            memo="",
            username="arnold",
        )
    )

    assert result["created"] is False
    assert result["linked"] is True

    item = result["item"]

    assert (
        item["destination_id"]
        == destination_id
    )

    assert item["status"] == "approved"

    assert (
        item["recipient_id"]
        == recipient["recipient_id"]
    )

    # Existing immutable route address is retained.
    assert (
        item["address"]
        == legacy_address
    )

    events = list_destination_events(
        destination_id
    )

    assert [
        event["action"]
        for event in events
    ] == [
        "recipient_linked",
    ]


def test_recipient_bridge_fails_closed_on_multiple_logical_legacy_routes():
    recipient_address = (
        _mixed_case_evm_address()
    )

    recipient = create_recipient(
        owner_account_id="arnold",
        address=recipient_address,
        label="Ambiguous legacy wallet",
        username="arnold",
    )["item"]

    lower = (
        recipient_address.lower()
    )

    upper = (
        "0x"
        + recipient_address[2:].upper()
    )

    assert lower != upper

    with session_scope() as db:
        for address in (
            lower,
            upper,
        ):
            db.add(
                TreasuryWithdrawalDestination(
                    destination_id=(
                        "wd_" + uuid4().hex
                    ),
                    owner_account_id="arnold",
                    recipient_id=None,
                    currency="USDT",
                    chain="ARBEVM",
                    address=address,
                    memo="",
                    label="Legacy duplicate",
                    status="candidate",
                    source="manual",
                    verification_method="unverified",
                    created_by="arnold",
                )
            )

    with pytest.raises(
        TreasuryWithdrawalDestinationError,
        match=(
            "Multiple logically equivalent "
            "withdrawal destinations"
        ),
    ):
        create_candidate_destination_from_recipient(
            recipient_id=(
                recipient["recipient_id"]
            ),
            currency="USDT",
            chain="ARBEVM",
            memo="",
            username="arnold",
        )


def test_recipient_bridge_preserves_revoked_destination_terminal_state():
    recipient_address = (
        _mixed_case_evm_address()
    )

    recipient = create_recipient(
        owner_account_id="arnold",
        address=recipient_address,
        label="Revoked legacy wallet",
        username="arnold",
    )["item"]

    with session_scope() as db:
        db.add(
            TreasuryWithdrawalDestination(
                destination_id=(
                    "wd_" + uuid4().hex
                ),
                owner_account_id="arnold",
                recipient_id=None,
                currency="USDT",
                chain="ETH",
                address=recipient_address,
                memo="",
                label="Revoked legacy route",
                status="revoked",
                source="manual",
                verification_method="unverified",
                created_by="arnold",
                revoked_by="rootadmin",
            )
        )

    with pytest.raises(
        TreasuryWithdrawalDestinationError,
        match=(
            "was revoked and cannot be "
            "recreated automatically"
        ),
    ):
        create_candidate_destination_from_recipient(
            recipient_id=(
                recipient["recipient_id"]
            ),
            currency="USDT",
            chain="ETH",
            memo="",
            username="arnold",
        )
