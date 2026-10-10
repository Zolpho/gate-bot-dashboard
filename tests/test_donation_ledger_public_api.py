from __future__ import annotations

import json
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import donate as donate_api
from app.db import (
    init_db,
    session_scope,
)
from app.donation_ledger import (
    SOURCE_DEMO,
    SOURCE_EXTERNAL_DEPOSIT,
    SOURCE_INTERNAL_TRANSFER,
    demo_source_key,
    ensure_donation_event,
    external_deposit_source_key,
    internal_transfer_source_key,
)
from app.main import app
from app.models import (
    DonationAttribution,
    DonationEvent,
    DonationIntent,
)


init_db()


class ForbiddenGateClient:
    def __init__(
        self,
        *args,
        **kwargs,
    ) -> None:
        raise AssertionError(
            "Public Donation Ledger must not construct GateClient"
        )


@pytest.fixture(autouse=True)
def clean_donation_ledger() -> None:
    def clean() -> None:
        with session_scope() as session:
            session.query(
                DonationAttribution
            ).delete(
                synchronize_session=False
            )

            session.query(
                DonationIntent
            ).delete(
                synchronize_session=False
            )

            session.query(
                DonationEvent
            ).delete(
                synchronize_session=False
            )

    clean()

    yield

    clean()


def _real_external(
    *,
    gate_id: str,
    currency: str,
    amount: str,
    occurred_at: datetime,
) -> str:
    with session_scope() as session:
        event, created = (
            ensure_donation_event(
                session,
                source_type=(
                    SOURCE_EXTERNAL_DEPOSIT
                ),
                source_key=(
                    external_deposit_source_key(
                        "eqtydao",
                        gate_id,
                    )
                ),
                currency=currency,
                chain_key="BASEEVM",
                chain="Base",
                amount=amount,
                occurred_at=occurred_at,
                demo=False,
            )
        )

        assert created is True

        return str(
            event["event_id"]
        )


def _real_internal(
    *,
    request_id: str,
    currency: str,
    amount: str,
    occurred_at: datetime,
) -> str:
    with session_scope() as session:
        event, created = (
            ensure_donation_event(
                session,
                source_type=(
                    SOURCE_INTERNAL_TRANSFER
                ),
                source_key=(
                    internal_transfer_source_key(
                        request_id
                    )
                ),
                currency=currency,
                amount=amount,
                occurred_at=occurred_at,
                demo=False,
            )
        )

        assert created is True

        return str(
            event["event_id"]
        )


def _demo(
    *,
    demo_id: str,
    currency: str,
    amount: str,
    occurred_at: datetime,
) -> str:
    with session_scope() as session:
        event, created = (
            ensure_donation_event(
                session,
                source_type=SOURCE_DEMO,
                source_key=(
                    demo_source_key(
                        demo_id
                    )
                ),
                currency=currency,
                amount=amount,
                occurred_at=occurred_at,
                demo=True,
            )
        )

        assert created is True

        return str(
            event["event_id"]
        )


def _attribute(
    *,
    event_id: str,
    display_mode: str,
    nickname: str = "",
    telegram_handle: str = "",
    x_handle: str = "",
) -> None:
    with session_scope() as session:
        session.add(
            DonationAttribution(
                event_id=event_id,
                display_mode=display_mode,
                nickname=nickname,
                telegram_handle=telegram_handle,
                x_handle=x_handle,
                updated_by=(
                    "private-audit-user"
                ),
            )
        )


def test_public_ledger_is_empty_anonymous_and_gate_independent(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )

    client = TestClient(
        app
    )

    response = client.get(
        "/api/donate/ledger"
    )

    assert response.status_code == 200

    assert (
        response.headers[
            "cache-control"
        ]
        == "no-store"
    )

    payload = response.json()

    assert payload["items"] == []

    assert payload["pagination"] == {
        "limit": 50,
        "offset": 0,
        "returned": 0,
        "total_items": 0,
        "include_demo": False,
    }

    assert payload["summary"] == {
        "real_event_count": 0,
        "demo_event_count": 0,
        "real_totals_by_currency": [],
    }


def test_public_ledger_projects_only_allowlisted_fields_and_attribution(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )

    newer = datetime(
        2026,
        10,
        10,
        10,
        0,
        tzinfo=timezone.utc,
    )

    older = newer - timedelta(
        minutes=10
    )

    external_id = _real_external(
        gate_id="private-gate-id",
        currency="EQTY",
        amount=(
            "1.234567890123456789012345"
        ),
        occurred_at=newer,
    )

    internal_id = _real_internal(
        request_id="private-request-id",
        currency="USDT",
        amount="4.500000000000000000000001",
        occurred_at=older,
    )

    _attribute(
        event_id=external_id,
        display_mode="telegram_x",
        telegram_handle="@donor",
        x_handle="@donor_x",
    )

    # Even if stale/private display fields exist, anonymous
    # mode must publish none of them.
    _attribute(
        event_id=internal_id,
        display_mode="anonymous",
        nickname="do-not-publish",
        telegram_handle="@hidden",
        x_handle="@hidden_x",
    )

    client = TestClient(
        app
    )

    response = client.get(
        "/api/donate/ledger"
    )

    assert response.status_code == 200

    payload = response.json()

    assert [
        item["event_id"]
        for item in payload["items"]
    ] == [
        external_id,
        internal_id,
    ]

    external = payload[
        "items"
    ][0]

    assert set(
        external
    ) == {
        "event_id",
        "source_type",
        "currency",
        "chain",
        "amount",
        "occurred_at",
        "demo",
        "attribution",
    }

    assert external["source_type"] == (
        "external_deposit"
    )

    assert external["currency"] == "EQTY"
    assert external["chain"] == "Base"

    assert external["amount"] == (
        "1.234567890123456789012345"
    )

    assert external["demo"] is False

    assert external[
        "attribution"
    ] == {
        "display_mode": "telegram_x",
        "nickname": "",
        "telegram_handle": "@donor",
        "x_handle": "@donor_x",
    }

    internal = payload[
        "items"
    ][1]

    assert internal[
        "attribution"
    ] == {
        "display_mode": "anonymous",
        "nickname": "",
        "telegram_handle": "",
        "x_handle": "",
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
    )

    for forbidden in (
        "source_key",
        "gate_deposit_id",
        "claim_token_hash",
        "submitted_txid",
        "matched_event_id",
        "updated_by",
        "account_id",
        "username",
        "address",
        "memo",
        "private-gate-id",
        "private-request-id",
        "private-audit-user",
        "do-not-publish",
        "@hidden",
        "@hidden_x",
    ):
        assert forbidden not in serialized


def test_demo_visibility_is_opt_in_and_real_totals_exclude_demo(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )

    now = datetime(
        2026,
        10,
        10,
        11,
        0,
        tzinfo=timezone.utc,
    )

    _real_external(
        gate_id="one",
        currency="USDT",
        amount="0.1",
        occurred_at=now,
    )

    _real_internal(
        request_id="two",
        currency="USDT",
        amount="0.2",
        occurred_at=(
            now
            - timedelta(
                seconds=1
            )
        ),
    )

    demo_id = _demo(
        demo_id="three",
        currency="USDT",
        amount="999999",
        occurred_at=(
            now
            + timedelta(
                seconds=1
            )
        ),
    )

    client = TestClient(
        app
    )

    normal = client.get(
        "/api/donate/ledger"
    )

    assert normal.status_code == 200

    normal_payload = normal.json()

    assert len(
        normal_payload[
            "items"
        ]
    ) == 2

    assert all(
        item["demo"] is False
        for item in normal_payload[
            "items"
        ]
    )

    assert normal_payload[
        "summary"
    ] == {
        "real_event_count": 2,
        "demo_event_count": 1,
        "real_totals_by_currency": [
            {
                "currency": "USDT",
                "amount": "0.3",
            }
        ],
    }

    including_demo = client.get(
        "/api/donate/ledger",
        params={
            "include_demo": "true",
        },
    )

    assert (
        including_demo.status_code
        == 200
    )

    all_payload = (
        including_demo.json()
    )

    assert len(
        all_payload["items"]
    ) == 3

    assert all_payload[
        "items"
    ][0]["event_id"] == demo_id

    assert all_payload[
        "items"
    ][0]["demo"] is True

    # Demo never contributes to real totals.
    assert all_payload[
        "summary"
    ] == normal_payload[
        "summary"
    ]


def test_public_ledger_pagination_is_newest_first_and_stable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )

    base = datetime(
        2026,
        10,
        10,
        12,
        0,
        tzinfo=timezone.utc,
    )

    oldest = _real_internal(
        request_id="oldest",
        currency="EQTY",
        amount="1",
        occurred_at=base,
    )

    middle = _real_internal(
        request_id="middle",
        currency="EQTY",
        amount="2",
        occurred_at=(
            base
            + timedelta(
                seconds=1
            )
        ),
    )

    newest = _real_internal(
        request_id="newest",
        currency="EQTY",
        amount="3",
        occurred_at=(
            base
            + timedelta(
                seconds=2
            )
        ),
    )

    client = TestClient(
        app
    )

    page = client.get(
        "/api/donate/ledger",
        params={
            "limit": 1,
            "offset": 1,
        },
    )

    assert page.status_code == 200

    payload = page.json()

    assert [
        item["event_id"]
        for item in payload[
            "items"
        ]
    ] == [
        middle
    ]

    assert payload[
        "pagination"
    ] == {
        "limit": 1,
        "offset": 1,
        "returned": 1,
        "total_items": 3,
        "include_demo": False,
    }

    complete = client.get(
        "/api/donate/ledger",
        params={
            "limit": 3,
        },
    ).json()

    assert [
        item["event_id"]
        for item in complete[
            "items"
        ]
    ] == [
        newest,
        middle,
        oldest,
    ]


def test_incomplete_or_unknown_attribution_fails_closed_to_anonymous(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )

    now = datetime.now(
        timezone.utc
    )

    first = _real_internal(
        request_id="bad-attribution-one",
        currency="EQTY",
        amount="1",
        occurred_at=now,
    )

    second = _real_internal(
        request_id="bad-attribution-two",
        currency="EQTY",
        amount="2",
        occurred_at=(
            now
            - timedelta(
                seconds=1
            )
        ),
    )

    _attribute(
        event_id=first,
        display_mode="telegram_x",
        telegram_handle="@telegram_only",
        x_handle="",
    )

    _attribute(
        event_id=second,
        display_mode="future_unknown_mode",
        nickname="private-name",
        telegram_handle="@private",
        x_handle="@private_x",
    )

    client = TestClient(
        app
    )

    response = client.get(
        "/api/donate/ledger"
    )

    assert response.status_code == 200

    for item in response.json()[
        "items"
    ]:
        assert item[
            "attribution"
        ] == {
            "display_mode": "anonymous",
            "nickname": "",
            "telegram_handle": "",
            "x_handle": "",
        }


def test_public_ledger_route_is_get_only_static_and_validated() -> None:
    client = TestClient(
        app
    )

    openapi = client.get(
        "/openapi.json"
    )

    assert openapi.status_code == 200

    paths = openapi.json()[
        "paths"
    ]

    assert (
        "/api/donate/ledger"
        in paths
    )

    assert set(
        paths[
            "/api/donate/ledger"
        ]
    ) == {
        "get"
    }

    assert client.post(
        "/api/donate/ledger"
    ).status_code == 405

    assert client.get(
        "/api/donate/ledger",
        params={
            "limit": 0,
        },
    ).status_code == 422

    assert client.get(
        "/api/donate/ledger",
        params={
            "limit": 101,
        },
    ).status_code == 422

    assert client.get(
        "/api/donate/ledger",
        params={
            "offset": 10001,
        },
    ).status_code == 422
