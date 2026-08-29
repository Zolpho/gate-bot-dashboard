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


def _address() -> str:
    return (
        "0x"
        + uuid4().hex
        + uuid4().hex[:8]
    )


def _recipient(
    client: TestClient,
    *,
    headers: dict[str, str] = ARNOLD,
    owner_account_id: str = "arnold",
):
    response = client.post(
        "/api/treasury/withdrawals/recipients",
        headers=headers,
        json={
            "owner_account_id": owner_account_id,
            "address": _address(),
            "label": "Recipient wallet",
        },
    )

    assert response.status_code == 200

    return response.json()["item"]


def _route(
    client: TestClient,
    recipient_id: str,
    *,
    headers: dict[str, str] = ARNOLD,
    currency: str = "USDT",
    chain: str = "ETH",
    memo: str = "",
):
    return client.post(
        (
            "/api/treasury/withdrawals/"
            f"recipients/{recipient_id}/destinations"
        ),
        headers=headers,
        json={
            "currency": currency,
            "chain": chain,
            "memo": memo,
        },
    )


def test_owner_can_create_destination_route_from_active_recipient():
    with TestClient(app) as client:
        recipient = _recipient(
            client
        )

        response = _route(
            client,
            recipient["recipient_id"],
        )

        assert response.status_code == 200

        body = response.json()

        assert body["created"] is True
        assert body["linked"] is True

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
            item["recipient_id"]
            == recipient["recipient_id"]
        )

        assert (
            item["owner_account_id"]
            == "arnold"
        )

        assert item["currency"] == "USDT"
        assert item["chain"] == "ETH"
        assert item["memo"] == ""
        assert item["status"] == "candidate"

        assert item["source"] == "recipient"

        # Address is derived solely from the stored recipient.
        assert (
            item["address"]
            == recipient["address"]
        )


def test_recipient_route_request_forbids_raw_address_and_owner():
    with TestClient(app) as client:
        recipient = _recipient(
            client
        )

        response = client.post(
            (
                "/api/treasury/withdrawals/"
                f"recipients/"
                f"{recipient['recipient_id']}/"
                "destinations"
            ),
            headers=ARNOLD,
            json={
                "currency": "USDT",
                "chain": "ETH",
                "memo": "",
                "address": _address(),
                "owner_account_id": "arnold",
            },
        )

        assert response.status_code == 422


def test_foreign_recipient_route_is_hidden_as_not_found():
    with TestClient(app) as client:
        recipient = _recipient(
            client,
            headers=ARNOLD,
            owner_account_id="arnold",
        )

        response = _route(
            client,
            recipient["recipient_id"],
            headers=ZOLNODE,
        )

        assert response.status_code == 404


def test_archived_recipient_cannot_create_destination_route():
    with TestClient(app) as client:
        recipient = _recipient(
            client
        )

        archived = client.post(
            (
                "/api/treasury/withdrawals/"
                f"recipients/"
                f"{recipient['recipient_id']}/"
                "archive"
            ),
            headers=ARNOLD,
            json={},
        )

        assert archived.status_code == 200

        response = _route(
            client,
            recipient["recipient_id"],
        )

        assert response.status_code == 409

        detail = response.json()["detail"]

        assert (
            detail["local_write_performed"]
            is False
        )

        assert (
            detail["gate_write_performed"]
            is False
        )


def test_recipient_route_identity_remains_asset_chain_and_memo_scoped():
    with TestClient(app) as client:
        recipient = _recipient(
            client
        )

        recipient_id = (
            recipient["recipient_id"]
        )

        eth = _route(
            client,
            recipient_id,
            currency="USDT",
            chain="ETH",
            memo="",
        )

        arb = _route(
            client,
            recipient_id,
            currency="USDT",
            chain="ARBEVM",
            memo="",
        )

        memo = _route(
            client,
            recipient_id,
            currency="USDT",
            chain="ETH",
            memo="12345",
        )

        repeat = _route(
            client,
            recipient_id,
            currency="USDT",
            chain="ETH",
            memo="",
        )

        assert eth.status_code == 200
        assert arb.status_code == 200
        assert memo.status_code == 200
        assert repeat.status_code == 200

        ids = {
            eth.json()["item"]["destination_id"],
            arb.json()["item"]["destination_id"],
            memo.json()["item"]["destination_id"],
        }

        assert len(ids) == 3

        repeat_body = repeat.json()

        assert repeat_body["created"] is False
        assert repeat_body["linked"] is False

        assert (
            repeat_body["local_write_performed"]
            is False
        )

        assert (
            repeat_body["item"]["destination_id"]
            == eth.json()["item"]["destination_id"]
        )

        assert (
            repeat_body["gate_write_performed"]
            is False
        )


def test_recipient_route_api_has_no_delete_route():
    delete_routes = []

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
            and "destinations" in path
            and "DELETE" in set(
                getattr(
                    route,
                    "methods",
                    set(),
                )
                or set()
            )
        ):
            delete_routes.append(
                path
            )

    assert delete_routes == []
