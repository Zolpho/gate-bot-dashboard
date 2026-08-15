from __future__ import annotations

import base64
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.main import app
from app.migrations import migrate_database


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
