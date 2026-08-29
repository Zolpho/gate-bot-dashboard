from __future__ import annotations

import base64
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


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


def _address() -> str:
    return (
        "0x"
        + uuid4().hex
        + uuid4().hex[:8]
    )


def _create(
    client: TestClient,
    *,
    headers: dict[str, str] = ARNOLD,
    owner_account_id: str = "arnold",
    label: str = "My Ledger",
    address: str | None = None,
):
    return client.post(
        "/api/treasury/withdrawals/recipients",
        headers=headers,
        json={
            "owner_account_id": owner_account_id,
            "address": address or _address(),
            "label": label,
        },
    )


def test_account_operator_can_create_and_list_own_recipient():
    with TestClient(app) as client:
        created = _create(
            client,
        )

        assert created.status_code == 200

        body = created.json()

        assert body["created"] is True
        assert (
            body["local_write_performed"]
            is True
        )
        assert (
            body["gate_write_performed"]
            is False
        )

        item = body["item"]

        assert (
            item["owner_account_id"]
            == "arnold"
        )

        assert item["status"] == "active"
        assert item["label"] == "My Ledger"

        assert "currency" not in item
        assert "chain" not in item
        assert "memo" not in item

        listed = client.get(
            (
                "/api/treasury/withdrawals/"
                "recipients"
                "?owner_account_id=arnold"
                "&status=active"
            ),
            headers=ARNOLD,
        )

        assert listed.status_code == 200

        listed_body = listed.json()

        assert (
            listed_body["gate_write_performed"]
            is False
        )

        ids = {
            row["recipient_id"]
            for row in listed_body["items"]
        }

        assert item["recipient_id"] in ids


def test_operator_cannot_create_recipient_for_another_account():
    with TestClient(app) as client:
        response = _create(
            client,
            owner_account_id="zolnode",
        )

        assert response.status_code == 403


def test_create_recipient_forbids_route_security_fields():
    with TestClient(app) as client:
        payload = {
            "owner_account_id": "arnold",
            "address": _address(),
            "label": "Generic address",
            "currency": "USDT",
            "chain": "ETH",
            "memo": "123",
        }

        response = client.post(
            "/api/treasury/withdrawals/recipients",
            headers=ARNOLD,
            json=payload,
        )

        assert response.status_code == 422


def test_recipient_detail_is_owner_scoped_and_audited():
    with TestClient(app) as client:
        created = _create(
            client,
        ).json()

        recipient_id = (
            created["item"]["recipient_id"]
        )

        own = client.get(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}"
            ),
            headers=ARNOLD,
        )

        assert own.status_code == 200

        body = own.json()

        assert (
            body["item"]["recipient_id"]
            == recipient_id
        )

        assert [
            event["action"]
            for event in body["events"]
        ] == [
            "created",
        ]

        assert (
            body["gate_write_performed"]
            is False
        )

        foreign = client.get(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}"
            ),
            headers=ZOLNODE,
        )

        # Opaque IDs must not disclose another user's
        # external address-book entries.
        assert foreign.status_code == 404


def test_recipient_label_can_be_renamed_but_address_cannot_be_edited():
    with TestClient(app) as client:
        created = _create(
            client,
            label="Old label",
        ).json()

        recipient = created["item"]

        recipient_id = (
            recipient["recipient_id"]
        )

        original_address = (
            recipient["address"]
        )

        renamed = client.patch(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}"
            ),
            headers=ARNOLD,
            json={
                "label": "Cold wallet",
            },
        )

        assert renamed.status_code == 200

        body = renamed.json()

        assert body["changed"] is True
        assert (
            body["local_write_performed"]
            is True
        )
        assert (
            body["gate_write_performed"]
            is False
        )
        assert (
            body["item"]["label"]
            == "Cold wallet"
        )
        assert (
            body["item"]["address"]
            == original_address
        )

        forbidden_edit = client.patch(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}"
            ),
            headers=ARNOLD,
            json={
                "label": "Unsafe edit",
                "address": _address(),
            },
        )

        assert (
            forbidden_edit.status_code
            == 422
        )

        detail = client.get(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}"
            ),
            headers=ARNOLD,
        ).json()

        assert [
            event["action"]
            for event in detail["events"]
        ] == [
            "created",
            "renamed",
        ]

        assert (
            detail["item"]["address"]
            == original_address
        )


def test_recipient_rename_hides_foreign_recipient_existence():
    with TestClient(app) as client:
        created = _create(
            client,
        ).json()

        recipient_id = (
            created["item"]["recipient_id"]
        )

        response = client.patch(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}"
            ),
            headers=ZOLNODE,
            json={
                "label": "Not mine",
            },
        )

        assert response.status_code == 404


def test_recipient_archive_and_restore_are_local_audited_actions():
    with TestClient(app) as client:
        created = _create(
            client,
            label="Temporary wallet",
        ).json()

        recipient_id = (
            created["item"]["recipient_id"]
        )

        archived = client.post(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}/archive"
            ),
            headers=ARNOLD,
            json={
                "reason": (
                    "Hide this address from normal "
                    "withdrawal recipient selection."
                ),
            },
        )

        assert archived.status_code == 200

        archived_body = archived.json()

        assert (
            archived_body["item"]["status"]
            == "archived"
        )
        assert (
            archived_body["local_write_performed"]
            is True
        )
        assert (
            archived_body["gate_write_performed"]
            is False
        )

        active = client.get(
            (
                "/api/treasury/withdrawals/"
                "recipients"
                "?owner_account_id=arnold"
                "&status=active"
            ),
            headers=ARNOLD,
        ).json()

        assert recipient_id not in {
            item["recipient_id"]
            for item in active["items"]
        }

        archived_list = client.get(
            (
                "/api/treasury/withdrawals/"
                "recipients"
                "?owner_account_id=arnold"
                "&status=archived"
            ),
            headers=ARNOLD,
        ).json()

        assert recipient_id in {
            item["recipient_id"]
            for item in archived_list["items"]
        }

        restored = client.post(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}/restore"
            ),
            headers=ARNOLD,
            json={
                "reason": (
                    "Return this address to normal "
                    "recipient selection."
                ),
            },
        )

        assert restored.status_code == 200

        restored_body = restored.json()

        assert (
            restored_body["item"]["status"]
            == "active"
        )
        assert (
            restored_body["local_write_performed"]
            is True
        )
        assert (
            restored_body["gate_write_performed"]
            is False
        )

        detail = client.get(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}"
            ),
            headers=ARNOLD,
        ).json()

        assert [
            event["action"]
            for event in detail["events"]
        ] == [
            "created",
            "archived",
            "restored",
        ]


def test_recipient_archive_hides_foreign_recipient_existence():
    with TestClient(app) as client:
        created = _create(
            client,
        ).json()

        recipient_id = (
            created["item"]["recipient_id"]
        )

        response = client.post(
            (
                "/api/treasury/withdrawals/"
                f"recipients/{recipient_id}/archive"
            ),
            headers=ZOLNODE,
            json={},
        )

        assert response.status_code == 404


def test_super_admin_can_list_all_recipients():
    with TestClient(app) as client:
        arnold = _create(
            client,
            owner_account_id="arnold",
            headers=ARNOLD,
            label="Arnold wallet",
        ).json()["item"]

        zolnode = _create(
            client,
            owner_account_id="zolnode",
            headers=ZOLNODE,
            label="Zolnode wallet",
        ).json()["item"]

        response = client.get(
            "/api/treasury/withdrawals/recipients",
            headers=ROOT,
        )

        assert response.status_code == 200

        body = response.json()

        ids = {
            item["recipient_id"]
            for item in body["items"]
        }

        assert arnold["recipient_id"] in ids
        assert zolnode["recipient_id"] in ids

        assert (
            body["gate_write_performed"]
            is False
        )


def test_recipient_api_has_no_delete_route():
    recipient_delete_routes = []

    for route in app.routes:
        path = getattr(
            route,
            "path",
            "",
        )

        if (
            path.startswith(
                "/api/treasury/withdrawals/"
                "recipients"
            )
            and "DELETE" in set(
                getattr(
                    route,
                    "methods",
                    set(),
                )
                or set()
            )
        ):
            recipient_delete_routes.append(
                path
            )

    assert recipient_delete_routes == []
