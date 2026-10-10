from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

import pytest
from fastapi.testclient import (
    TestClient,
)
from sqlalchemy import (
    select,
)

from app.api import donate as donate_api
from app.db import (
    init_db,
    session_scope,
)
from app.deposit_history import (
    upsert_deposit_rows,
)
from app.donation_destinations import (
    bootstrap_public_destination,
)
from app.main import app
from app.models import (
    DepositRecord,
    DonationAttribution,
    DonationEvent,
    DonationIntent,
    GateAccount,
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
            "Public DonationIntent routes "
            "must not construct GateClient"
        )


@pytest.fixture(autouse=True)
def clean_public_intent_state() -> None:
    donate_api.reset_donation_runtime_caches()

    created_test_account = False

    def clean_donation_state() -> None:
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
                DepositRecord
            ).delete(
                synchronize_session=False
            )

            session.query(
                PublicDonationDestination
            ).delete(
                synchronize_session=False
            )

    clean_donation_state()

    with session_scope() as session:
        account = session.get(
            GateAccount,
            "eqtydao",
        )

        if account is None:
            session.add(
                GateAccount(
                    id="eqtydao",
                    name="EQTYDAO",
                    account_type="main",
                    gate_uid="",
                    enabled=True,
                    configured=True,
                    sync_status="test",
                    bot_count=0,
                )
            )

            created_test_account = True

    yield

    donate_api.reset_donation_runtime_caches()

    clean_donation_state()

    if created_test_account:
        with session_scope() as session:
            account = session.get(
                GateAccount,
                "eqtydao",
            )

            if account is not None:
                session.delete(
                    account
                )


@pytest.fixture
def no_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )


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


def _create_intent(
    client: TestClient,
) -> tuple[
    dict,
    str,
]:
    _trust_destination()

    response = client.post(
        "/api/donate/intents",
        json={
            "currency": "eqty",
            "chain": "BASE-EVM",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert set(
        body
    ) == {
        "intent",
        "claim_token",
    }

    return (
        body["intent"],
        body["claim_token"],
    )


def _deposit(
    *,
    txid: str,
    gate_id: str = "gate-deposit-1",
    amount: str = (
        "12.345678901234567890123456"
    ),
) -> None:
    now = datetime.now(
        timezone.utc
    )

    with session_scope() as session:
        upsert_deposit_rows(
            session,
            "eqtydao",
            [
                {
                    "id": gate_id,
                    "txid": txid,
                    "currency": "EQTY",
                    "chain": "BASE-EVM",
                    "amount": amount,
                    "status": "DONE",
                    "timestamp": str(
                        int(
                            now.timestamp()
                        )
                    ),
                    "address":
                        "0xTrustedDonationAddress",
                    "memo": "",
                }
            ],
            seen_at=now,
        )


def test_create_intent_returns_claim_once_and_never_calls_gate(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    _trust_destination()

    response = client.post(
        "/api/donate/intents",
        json={
            "currency": "eqty",
            "chain": "BASE-EVM",
        },
    )

    assert response.status_code == 201
    assert (
        response.headers["cache-control"]
        == "no-store"
    )

    body = response.json()

    claim = body[
        "claim_token"
    ]

    intent = body[
        "intent"
    ]

    assert claim
    assert intent["status"] == "pending"

    assert (
        intent["match_status"]
        == "pending"
    )

    assert (
        intent["txid_submitted"]
        is False
    )

    assert (
        intent["matched_event_id"]
        is None
    )

    assert "claim_token_hash" not in intent
    assert "submitted_txid" not in intent

    with session_scope() as session:
        row = session.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == intent["intent_id"]
            )
        )

        assert row is not None

        assert (
            row.claim_token_hash
            != claim
        )

        assert claim not in (
            row.claim_token_hash,
            row.intent_id,
            row.submitted_txid,
        )


def test_create_intent_requires_existing_trusted_destination(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    response = client.post(
        "/api/donate/intents",
        json={
            "currency": "EQTY",
            "chain": "BASE-EVM",
        },
    )

    assert response.status_code == 503

    assert response.json() == {
        "detail": (
            "Donation destination "
            "temporarily unavailable"
        )
    }

    with session_scope() as session:
        assert (
            session.query(
                DonationIntent
            ).count()
            == 0
        )


def test_create_intent_rejects_unknown_body_fields(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    _trust_destination()

    response = client.post(
        "/api/donate/intents",
        json={
            "currency": "EQTY",
            "chain": "BASE-EVM",
            "account_id": "zolnode",
        },
    )

    assert response.status_code == 422

    with session_scope() as session:
        assert (
            session.query(
                DonationIntent
            ).count()
            == 0
        )


def test_invalid_claim_is_forbidden_and_intent_stays_pending(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    intent, _ = _create_intent(
        client
    )

    response = client.post(
        (
            "/api/donate/intents/"
            + intent["intent_id"]
            + "/txid"
        ),
        json={
            "claim_token":
                "definitely-not-the-claim",
            "txid": "invalid-claim-txid",
        },
    )

    assert response.status_code == 403

    assert response.json() == {
        "detail":
            "Invalid donation claim token"
    }

    with session_scope() as session:
        row = session.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == intent["intent_id"]
            )
        )

        assert row is not None
        assert row.status == "pending"
        assert row.submitted_txid == ""

        assert not (
            row.claim_token_hash
            .startswith(
                "!consumed:"
            )
        )


def test_submit_without_local_deposit_persists_binding_without_leak(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    intent, claim = _create_intent(
        client
    )

    txid = "not-yet-local-txid"

    response = client.post(
        (
            "/api/donate/intents/"
            + intent["intent_id"]
            + "/txid"
        ),
        json={
            "claim_token": claim,
            "txid": txid,
        },
    )

    assert response.status_code == 200
    assert (
        response.headers["cache-control"]
        == "no-store"
    )

    body = response.json()
    public = body["intent"]

    assert public["status"] == "submitted"

    assert (
        public["match_status"]
        == "not_found"
    )

    assert (
        public["txid_submitted"]
        is True
    )

    assert txid not in repr(
        body
    )

    assert claim not in repr(
        body
    )

    assert "claim_token_hash" not in repr(
        body
    )

    with session_scope() as session:
        row = session.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == intent["intent_id"]
            )
        )

        assert row is not None

        assert row.status == "submitted"

        assert (
            row.submitted_txid
            == txid
        )

        assert (
            row.claim_token_hash
            == (
                "!consumed:"
                + row.intent_id
            )
        )

        assert (
            session.query(
                DonationEvent
            ).count()
            == 0
        )


def test_submit_immediately_matches_exact_local_done_deposit(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    intent, claim = _create_intent(
        client
    )

    txid = "already-local-donation"

    _deposit(
        txid=txid,
        gate_id="exact-http-deposit",
    )

    response = client.post(
        (
            "/api/donate/intents/"
            + intent["intent_id"]
            + "/txid"
        ),
        json={
            "claim_token": claim,
            "txid": txid,
        },
    )

    assert response.status_code == 200

    body = response.json()
    public = body["intent"]

    assert public["status"] == "matched"

    assert (
        public["match_status"]
        == "matched"
    )

    assert (
        public["matched_event_id"]
    )

    assert txid not in repr(
        body
    )

    assert claim not in repr(
        body
    )

    with session_scope() as session:
        event = session.scalar(
            select(
                DonationEvent
            )
        )

        assert event is not None

        assert (
            event.source_key
            == "eqtydao:exact-http-deposit"
        )

        assert (
            str(
                event.amount
            )
            == (
                "12.345678901234567890123456"
            )
        )


def test_reconcile_matches_after_deposit_history_arrives_and_is_idempotent(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    intent, claim = _create_intent(
        client
    )

    txid = "delayed-local-donation"

    submitted = client.post(
        (
            "/api/donate/intents/"
            + intent["intent_id"]
            + "/txid"
        ),
        json={
            "claim_token": claim,
            "txid": txid,
        },
    )

    assert submitted.status_code == 200

    assert (
        submitted.json()[
            "intent"
        ][
            "match_status"
        ]
        == "not_found"
    )

    _deposit(
        txid=txid,
        gate_id="delayed-http-deposit",
    )

    route = (
        "/api/donate/intents/"
        + intent["intent_id"]
        + "/reconcile"
    )

    first = client.post(
        route
    )

    second = client.post(
        route
    )

    assert first.status_code == 200
    assert second.status_code == 200

    first_intent = first.json()[
        "intent"
    ]

    second_intent = second.json()[
        "intent"
    ]

    assert first_intent["status"] == "matched"

    assert (
        first_intent["match_status"]
        == "matched"
    )

    assert (
        first_intent["matched_event_id"]
        == second_intent[
            "matched_event_id"
        ]
    )

    with session_scope() as session:
        assert (
            session.query(
                DonationEvent
            ).count()
            == 1
        )


def test_reconcile_pending_intent_fails_closed_without_mutation(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    intent, _ = _create_intent(
        client
    )

    response = client.post(
        (
            "/api/donate/intents/"
            + intent["intent_id"]
            + "/reconcile"
        )
    )

    assert response.status_code == 409

    assert response.json() == {
        "detail":
            "Donation intent cannot be updated"
    }

    with session_scope() as session:
        row = session.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == intent["intent_id"]
            )
        )

        assert row is not None
        assert row.status == "pending"
        assert row.submitted_txid == ""

        assert (
            session.query(
                DonationEvent
            ).count()
            == 0
        )


def test_submit_extends_reconciliation_window_after_claim_consumption(
    no_gate,
) -> None:
    client = TestClient(
        app
    )

    intent, claim = _create_intent(
        client
    )

    original_expiry = (
        datetime.fromisoformat(
            intent[
                "expires_at"
            ]
        )
    )

    txid = (
        "slow-finality-match-window"
    )

    response = client.post(
        (
            "/api/donate/intents/"
            + intent["intent_id"]
            + "/txid"
        ),
        json={
            "claim_token": claim,
            "txid": txid,
        },
    )

    assert response.status_code == 200

    public = response.json()[
        "intent"
    ]

    assert public["status"] == "submitted"

    assert (
        public["match_status"]
        == "not_found"
    )

    extended_expiry = (
        datetime.fromisoformat(
            public[
                "expires_at"
            ]
        )
    )

    extension_seconds = (
        extended_expiry
        - original_expiry
    ).total_seconds()

    # Original claim lifetime is 30 minutes.
    # Submitted correlation lifetime is 7 days.
    # Keep broad non-flaky bounds around that delta.
    assert (
        extension_seconds
        > 6 * 24 * 60 * 60
    )

    assert (
        extension_seconds
        < 8 * 24 * 60 * 60
    )

    assert claim not in repr(
        response.json()
    )

    assert txid not in repr(
        response.json()
    )
