from __future__ import annotations

from fastapi.testclient import (
    TestClient,
)

import pytest

from app.api import donate as donate_api
from app.db import (
    init_db,
    session_scope,
)
from app.donation_destinations import (
    bootstrap_public_destination,
)
from app.main import app
from app.models import (
    DonationAttribution,
    DonationEvent,
    DonationIntent,
    PublicDonationDestination,
)


init_db()


class ForbiddenGateClient:
    def __init__(
        self,
        *args,
        **kwargs,
    ) -> None:
        raise AssertionError(
            "Donation rate limiting must not "
            "construct GateClient"
        )


def _clean() -> None:
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

        session.query(
            PublicDonationDestination
        ).delete(
            synchronize_session=False
        )


@pytest.fixture(autouse=True)
def clean_rate_test_state(
    monkeypatch,
) -> None:
    _clean()

    donate_api.reset_donation_runtime_caches()

    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )

    yield

    donate_api.reset_donation_runtime_caches()

    _clean()


def _trust_destination() -> None:
    with session_scope() as session:
        bootstrap_public_destination(
            session,
            {
                "currency": "EQTY",
                "network": {
                    "chain": "BASE-EVM",
                    "address":
                        "0xTrustedDonationAddress",
                    "payment_id": None,
                },
            },
        )


def _set_policy(
    monkeypatch,
    *,
    action: str,
    client_limit: int,
    global_limit: int,
) -> None:
    policies = {
        key: dict(
            value
        )
        for key, value in (
            donate_api
            .PUBLIC_DONATION_RATE_POLICIES
            .items()
        )
    }

    policies[
        action
    ] = {
        "client_limit":
            client_limit,
        "global_limit":
            global_limit,
    }

    monkeypatch.setattr(
        donate_api,
        "PUBLIC_DONATION_RATE_POLICIES",
        policies,
    )


def _create(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
):
    return client.post(
        "/api/donate/intents",
        headers=headers,
        json={
            "currency": "EQTY",
            "chain": "BASE-EVM",
        },
    )


def test_create_rate_limit_bounds_database_growth_and_returns_retry_after(
    monkeypatch,
) -> None:
    _trust_destination()

    _set_policy(
        monkeypatch,
        action=(
            donate_api
            .PUBLIC_DONATION_RATE_INTENT_CREATE
        ),
        client_limit=3,
        global_limit=20,
    )

    client = TestClient(
        app
    )

    for _ in range(
        3
    ):
        response = _create(
            client
        )

        assert response.status_code == 201

    blocked = _create(
        client
    )

    assert blocked.status_code == 429

    assert blocked.json() == {
        "detail":
            "Too many donation requests"
    }

    assert int(
        blocked.headers[
            "retry-after"
        ]
    ) >= 1

    assert (
        blocked.headers[
            "cache-control"
        ]
        == "no-store"
    )

    with session_scope() as session:
        assert (
            session.query(
                DonationIntent
            ).count()
            == 3
        )


def test_forwarding_headers_do_not_bypass_client_bucket(
    monkeypatch,
) -> None:
    _trust_destination()

    _set_policy(
        monkeypatch,
        action=(
            donate_api
            .PUBLIC_DONATION_RATE_INTENT_CREATE
        ),
        client_limit=2,
        global_limit=20,
    )

    client = TestClient(
        app
    )

    first = _create(
        client,
        headers={
            "X-Forwarded-For":
                "198.51.100.10",
            "X-Real-IP":
                "198.51.100.10",
        },
    )

    second = _create(
        client,
        headers={
            "X-Forwarded-For":
                "198.51.100.11",
            "X-Real-IP":
                "198.51.100.11",
        },
    )

    third = _create(
        client,
        headers={
            "X-Forwarded-For":
                "203.0.113.77",
            "X-Real-IP":
                "203.0.113.77",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 429

    with session_scope() as session:
        assert (
            session.query(
                DonationIntent
            ).count()
            == 2
        )


def test_global_create_limit_survives_rotating_client_identity(
    monkeypatch,
) -> None:
    _trust_destination()

    _set_policy(
        monkeypatch,
        action=(
            donate_api
            .PUBLIC_DONATION_RATE_INTENT_CREATE
        ),
        client_limit=100,
        global_limit=3,
    )

    identities = iter(
        (
            "198.51.100.1",
            "198.51.100.2",
            "198.51.100.3",
            "198.51.100.4",
        )
    )

    monkeypatch.setattr(
        donate_api,
        "_request_client_identifier",
        lambda request: next(
            identities
        ),
    )

    client = TestClient(
        app
    )

    assert _create(
        client
    ).status_code == 201

    assert _create(
        client
    ).status_code == 201

    assert _create(
        client
    ).status_code == 201

    blocked = _create(
        client
    )

    assert blocked.status_code == 429

    with session_scope() as session:
        assert (
            session.query(
                DonationIntent
            ).count()
            == 3
        )

    bucket_repr = repr(
        donate_api
        ._donation_rate_buckets
    )

    assert "198.51.100." not in (
        bucket_repr
    )


def test_rate_window_expires_and_allows_new_slot(
    monkeypatch,
) -> None:
    _trust_destination()

    _set_policy(
        monkeypatch,
        action=(
            donate_api
            .PUBLIC_DONATION_RATE_INTENT_CREATE
        ),
        client_limit=1,
        global_limit=20,
    )

    now = [
        100.0
    ]

    monkeypatch.setattr(
        donate_api.time,
        "monotonic",
        lambda: now[0],
    )

    client = TestClient(
        app
    )

    first = _create(
        client
    )

    blocked = _create(
        client
    )

    assert first.status_code == 201
    assert blocked.status_code == 429

    now[0] = (
        100.0
        + (
            donate_api
            .PUBLIC_DONATION_RATE_WINDOW_SECONDS
        )
        + 1.0
    )

    after_window = _create(
        client
    )

    assert after_window.status_code == 201

    with session_scope() as session:
        assert (
            session.query(
                DonationIntent
            ).count()
            == 2
        )


def test_submit_rate_limit_runs_before_intent_lookup(
    monkeypatch,
) -> None:
    _set_policy(
        monkeypatch,
        action=(
            donate_api
            .PUBLIC_DONATION_RATE_TXID_SUBMIT
        ),
        client_limit=2,
        global_limit=20,
    )

    client = TestClient(
        app
    )

    route = (
        "/api/donate/intents/"
        "don_int_missing/"
        "txid"
    )

    payload = {
        "claim_token":
            "not-a-real-claim",
        "txid":
            "not-a-real-txid",
    }

    first = client.post(
        route,
        json=payload,
    )

    second = client.post(
        route,
        json=payload,
    )

    blocked = client.post(
        route,
        json=payload,
    )

    assert first.status_code == 404
    assert second.status_code == 404

    assert blocked.status_code == 429

    assert blocked.json() == {
        "detail":
            "Too many donation requests"
    }


def test_reconcile_rate_limit_runs_before_intent_lookup(
    monkeypatch,
) -> None:
    _set_policy(
        monkeypatch,
        action=(
            donate_api
            .PUBLIC_DONATION_RATE_RECONCILE
        ),
        client_limit=2,
        global_limit=20,
    )

    client = TestClient(
        app
    )

    route = (
        "/api/donate/intents/"
        "don_int_missing/"
        "reconcile"
    )

    first = client.post(
        route
    )

    second = client.post(
        route
    )

    blocked = client.post(
        route
    )

    assert first.status_code == 404
    assert second.status_code == 404

    assert blocked.status_code == 429

    assert blocked.json() == {
        "detail":
            "Too many donation requests"
    }
