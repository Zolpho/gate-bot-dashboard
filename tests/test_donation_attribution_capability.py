from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import (
    donate as donate_api,
)
from app.api import (
    treasury as treasury_api,
)
from app.db import (
    init_db,
    session_scope,
)
from app.donation_ledger import (
    DonationAttributionCapabilityError,
    SOURCE_DEMO,
    SOURCE_EXTERNAL_DEPOSIT,
    demo_source_key,
    ensure_donation_event,
    external_deposit_source_key,
    set_internal_transfer_donation_attribution,
    upsert_donation_attribution,
)
from app.main import app
from app.models import (
    DonationAttribution,
    DonationEvent,
    DonationIntent,
)
from app.security import (
    DashboardUser,
)


init_db()


class ForbiddenGateClient:
    def __init__(
        self,
        *args,
        **kwargs,
    ) -> None:
        raise AssertionError(
            "Attribution must never construct GateClient"
        )


@pytest.fixture(autouse=True)
def clean_attribution_state():
    donate_api.reset_donation_runtime_caches()

    def clean() -> None:
        with session_scope() as db:
            db.query(
                DonationAttribution
            ).delete(
                synchronize_session=False
            )

            db.query(
                DonationIntent
            ).delete(
                synchronize_session=False
            )

            db.query(
                DonationEvent
            ).delete(
                synchronize_session=False
            )

    clean()

    yield

    clean()

    donate_api.reset_donation_runtime_caches()


def _matched_intent(
    *,
    expired: bool = False,
):
    now = datetime.now(
        timezone.utc
    )

    with session_scope() as db:
        event, _ = ensure_donation_event(
            db,
            source_type=(
                SOURCE_EXTERNAL_DEPOSIT
            ),
            source_key=(
                external_deposit_source_key(
                    "eqtydao",
                    "gate-attribution-test",
                )
            ),
            currency="EQTY",
            chain_key="BASEEVM",
            chain="Base",
            amount="12.5",
            occurred_at=(
                now
                - timedelta(
                    minutes=2
                )
            ),
            demo=False,
        )

        intent = DonationIntent(
            intent_id=(
                "don_int_attribution_capability"
            ),
            claim_token_hash=(
                "a" * 64
            ),
            currency="EQTY",
            chain_key="BASEEVM",
            chain="Base",
            submitted_txid="0xabc123",
            status="matched",
            matched_event_id=(
                event[
                    "event_id"
                ]
            ),
            created_at=(
                now
                - timedelta(
                    minutes=3
                )
            ),
            expires_at=(
                now
                - timedelta(
                    seconds=1
                )
                if expired
                else now
                + timedelta(
                    days=6
                )
            ),
            matched_at=(
                now
                - timedelta(
                    minutes=1
                )
            ),
            updated_at=now,
        )

        db.add(
            intent
        )

        return (
            intent.intent_id,
            event[
                "event_id"
            ],
        )


def _pending_intent():
    now = datetime.now(
        timezone.utc
    )

    with session_scope() as db:
        intent = DonationIntent(
            intent_id=(
                "don_int_attribution_pending"
            ),
            claim_token_hash=(
                "b" * 64
            ),
            currency="EQTY",
            chain_key="BASEEVM",
            chain="Base",
            submitted_txid="",
            status="pending",
            matched_event_id=None,
            created_at=now,
            expires_at=(
                now
                + timedelta(
                    minutes=20
                )
            ),
            matched_at=None,
            updated_at=now,
        )

        db.add(
            intent
        )

        return intent.intent_id


def _internal_record(
    *,
    donation: bool = True,
):
    return {
        "request_id":
            "req-attribution-internal",
        "source_account_id":
            "zolnode",
        "destination_account_id":
            "eqtydao",
        "username":
            "zolnode",
        "direction":
            "user_account_transfer",
        "currency":
            "USDT",
        "amount":
            "2.5",
        "status":
            "success",
        "simulation":
            False,
        "write_performed":
            True,
        "request": {
            "donation":
                donation,
        },
        "completed_at":
            datetime(
                2026,
                10,
                10,
                14,
                0,
                tzinfo=timezone.utc,
            ).isoformat(),
    }


def test_public_matched_intent_sets_self_declared_telegram_and_x(
    monkeypatch,
):
    monkeypatch.setattr(
        donate_api,
        "GateClient",
        ForbiddenGateClient,
    )

    intent_id, event_id = (
        _matched_intent()
    )

    client = TestClient(
        app
    )

    response = client.post(
        (
            "/api/donate/intents/"
            + intent_id
            + "/attribution"
        ),
        json={
            "display_mode":
                "telegram_x",
            "telegram_handle":
                "Donor_Telegram",
            "x_handle":
                "@Donor_X",
        },
    )

    assert response.status_code == 200

    assert response.headers[
        "cache-control"
    ] == "no-store"

    assert response.json() == {
        "event_id":
            event_id,
        "attribution": {
            "display_mode":
                "telegram_x",
            "nickname":
                "",
            "telegram_handle":
                "@Donor_Telegram",
            "x_handle":
                "@Donor_X",
        },
    }

    assert (
        "verified"
        not in response.text.lower()
    )

    ledger = client.get(
        "/api/donate/ledger"
    )

    assert ledger.status_code == 200

    item = ledger.json()[
        "items"
    ][0]

    assert (
        item["event_id"]
        == event_id
    )

    assert item[
        "attribution"
    ] == {
        "display_mode":
            "telegram_x",
        "nickname":
            "",
        "telegram_handle":
            "@Donor_Telegram",
        "x_handle":
            "@Donor_X",
    }


def test_public_anonymous_is_default_and_clears_stale_identity():
    intent_id, event_id = (
        _matched_intent()
    )

    client = TestClient(
        app
    )

    first = client.post(
        (
            "/api/donate/intents/"
            + intent_id
            + "/attribution"
        ),
        json={
            "display_mode":
                "nickname",
            "nickname":
                "Visible donor",
        },
    )

    assert first.status_code == 200

    anonymous = client.post(
        (
            "/api/donate/intents/"
            + intent_id
            + "/attribution"
        ),
        # Empty body deliberately exercises the
        # anonymous default.
        json={},
    )

    assert anonymous.status_code == 200

    assert anonymous.json() == {
        "event_id":
            event_id,
        "attribution": {
            "display_mode":
                "anonymous",
            "nickname":
                "",
            "telegram_handle":
                "",
            "x_handle":
                "",
        },
    }

    with session_scope() as db:
        row = db.query(
            DonationAttribution
        ).one()

        assert (
            row.display_mode
            == "anonymous"
        )

        assert row.nickname == ""
        assert row.telegram_handle == ""
        assert row.x_handle == ""

        # Capability identity itself is not persisted.
        assert (
            row.updated_by
            == "public-intent"
        )

        assert (
            intent_id
            not in row.updated_by
        )


def test_public_unmatched_intent_cannot_set_attribution():
    intent_id = (
        _pending_intent()
    )

    response = TestClient(
        app
    ).post(
        (
            "/api/donate/intents/"
            + intent_id
            + "/attribution"
        ),
        json={
            "display_mode":
                "telegram",
            "telegram_handle":
                "@donor",
        },
    )

    assert response.status_code == 409

    with session_scope() as db:
        assert (
            db.query(
                DonationAttribution
            ).count()
            == 0
        )


def test_public_expired_matched_capability_cannot_change_attribution():
    intent_id, _ = (
        _matched_intent(
            expired=True
        )
    )

    response = TestClient(
        app
    ).post(
        (
            "/api/donate/intents/"
            + intent_id
            + "/attribution"
        ),
        json={
            "display_mode":
                "x",
            "x_handle":
                "@too_late",
        },
    )

    assert response.status_code == 409

    with session_scope() as db:
        assert (
            db.query(
                DonationAttribution
            ).count()
            == 0
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "display_mode":
                "future-mode",
        },
        {
            "display_mode":
                "telegram",
            "telegram_handle":
                "@bad handle",
        },
        {
            "display_mode":
                "x",
            "x_handle":
                "@bad-hyphen",
        },
        {
            "display_mode":
                "nickname",
            "nickname":
                "bad\nnickname",
        },
    ],
)
def test_public_invalid_attribution_is_rejected(
    payload,
):
    intent_id, _ = (
        _matched_intent()
    )

    response = TestClient(
        app
    ).post(
        (
            "/api/donate/intents/"
            + intent_id
            + "/attribution"
        ),
        json=payload,
    )

    assert response.status_code == 400

    with session_scope() as db:
        assert (
            db.query(
                DonationAttribution
            ).count()
            == 0
        )


def test_internal_confirmed_explicit_donation_can_be_attributed():
    result = (
        set_internal_transfer_donation_attribution(
            _internal_record(),
            display_mode="telegram",
            telegram_handle="zolnode",
            updated_by="dashboard:zolnode",
        )
    )

    assert result[
        "event_id"
    ].startswith(
        "don_evt_"
    )

    assert result[
        "attribution"
    ] == {
        "display_mode":
            "telegram",
        "nickname":
            "",
        "telegram_handle":
            "@zolnode",
        "x_handle":
            "",
    }

    with session_scope() as db:
        assert (
            db.query(
                DonationEvent
            ).count()
            == 1
        )

        row = db.query(
            DonationAttribution
        ).one()

        assert (
            row.updated_by
            == "dashboard:zolnode"
        )


def test_internal_ordinary_transfer_cannot_receive_donation_attribution():
    with pytest.raises(
        DonationAttributionCapabilityError,
        match=(
            "confirmed explicit donation"
        ),
    ):
        set_internal_transfer_donation_attribution(
            _internal_record(
                donation=False
            ),
            display_mode="nickname",
            nickname="Should not publish",
            updated_by="dashboard:zolnode",
        )

    with session_scope() as db:
        assert (
            db.query(
                DonationEvent
            ).count()
            == 0
        )

        assert (
            db.query(
                DonationAttribution
            ).count()
            == 0
        )


@pytest.mark.asyncio
async def test_internal_route_requires_source_access_and_original_user(
    monkeypatch,
):
    record = (
        _internal_record()
    )

    monkeypatch.setattr(
        treasury_api,
        "get_transfer_request",
        lambda request_id: record,
    )

    called = []

    def forbidden_service(
        *args,
        **kwargs,
    ):
        called.append(
            True
        )

        raise AssertionError(
            "service must not be reached"
        )

    monkeypatch.setattr(
        treasury_api,
        "set_internal_transfer_donation_attribution",
        forbidden_service,
    )

    request = (
        treasury_api
        .TreasuryDonationAttributionRequest()
    )

    super_admin_without_source = (
        DashboardUser(
            username="rootadmin",
            role="super_admin",
            account_ids=(),
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .set_treasury_user_transfer_donation_attribution(
                request_id=(
                    record[
                        "request_id"
                    ]
                ),
                request=request,
                user=(
                    super_admin_without_source
                ),
            )
        )

    assert (
        exc_info.value.status_code
        == 403
    )

    other_user_same_source = (
        DashboardUser(
            username="other",
            role="account_operator",
            account_ids=(
                "zolnode",
            ),
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await (
            treasury_api
            .set_treasury_user_transfer_donation_attribution(
                request_id=(
                    record[
                        "request_id"
                    ]
                ),
                request=request,
                user=(
                    other_user_same_source
                ),
            )
        )

    assert (
        exc_info.value.status_code
        == 403
    )

    assert called == []


@pytest.mark.asyncio
async def test_internal_route_is_local_only_and_returns_safe_projection(
    monkeypatch,
):
    record = (
        _internal_record()
    )

    monkeypatch.setattr(
        treasury_api,
        "get_transfer_request",
        lambda request_id: record,
    )

    def fake_service(
        source_record,
        **kwargs,
    ):
        assert (
            source_record
            is record
        )

        assert (
            kwargs[
                "updated_by"
            ]
            == "dashboard:zolnode"
        )

        return {
            "event_id":
                "don_evt_safe",
            "attribution": {
                "display_mode":
                    "x",
                "nickname":
                    "",
                "telegram_handle":
                    "",
                "x_handle":
                    "@zolnode_x",
            },
        }

    monkeypatch.setattr(
        treasury_api,
        "set_internal_transfer_donation_attribution",
        fake_service,
    )

    user = DashboardUser(
        username="zolnode",
        role="account_operator",
        account_ids=(
            "zolnode",
        ),
    )

    request = (
        treasury_api
        .TreasuryDonationAttributionRequest(
            display_mode="x",
            x_handle="zolnode_x",
        )
    )

    result = await (
        treasury_api
        .set_treasury_user_transfer_donation_attribution(
            request_id=(
                record[
                    "request_id"
                ]
            ),
            request=request,
            user=user,
        )
    )

    assert result == {
        "phase":
            "USER_ACCOUNT_TRANSFER",
        "status":
            "attribution_updated",
        "request_id":
            "req-attribution-internal",
        "event_id":
            "don_evt_safe",
        "attribution": {
            "display_mode":
                "x",
            "nickname":
                "",
            "telegram_handle":
                "",
            "x_handle":
                "@zolnode_x",
        },
        "gate_read_performed":
            False,
        "gate_write_performed":
            False,
    }


def test_demo_ledger_can_be_anonymous_or_self_declared_without_real_totals():
    now = datetime.now(
        timezone.utc
    )

    with session_scope() as db:
        event, _ = ensure_donation_event(
            db,
            source_type=SOURCE_DEMO,
            source_key=(
                demo_source_key(
                    "attribution-demo"
                )
            ),
            currency="USDT",
            amount="999",
            occurred_at=now,
            demo=True,
        )

        first = (
            upsert_donation_attribution(
                db,
                event_id=(
                    event[
                        "event_id"
                    ]
                ),
                display_mode="x",
                x_handle="demo_donor",
                updated_by="test-demo",
            )
        )

        assert first[
            "attribution"
        ][
            "x_handle"
        ] == "@demo_donor"

    client = TestClient(
        app
    )

    normal = client.get(
        "/api/donate/ledger"
    ).json()

    assert normal[
        "items"
    ] == []

    assert normal[
        "summary"
    ][
        "real_totals_by_currency"
    ] == []

    including_demo = client.get(
        "/api/donate/ledger",
        params={
            "include_demo":
                "true",
        },
    ).json()

    assert len(
        including_demo[
            "items"
        ]
    ) == 1

    demo = including_demo[
        "items"
    ][0]

    assert demo[
        "demo"
    ] is True

    assert demo[
        "attribution"
    ] == {
        "display_mode":
            "x",
        "nickname":
            "",
        "telegram_handle":
            "",
        "x_handle":
            "@demo_donor",
    }

    assert including_demo[
        "summary"
    ][
        "real_totals_by_currency"
    ] == []

    with session_scope() as db:
        anonymous = (
            upsert_donation_attribution(
                db,
                event_id=(
                    event[
                        "event_id"
                    ]
                ),
                # Default is deliberately anonymous.
                updated_by="test-demo",
            )
        )

        assert anonymous[
            "attribution"
        ] == {
            "display_mode":
                "anonymous",
            "nickname":
                "",
            "telegram_handle":
                "",
            "x_handle":
                "",
        }


def test_attribution_routes_are_exposed_with_expected_methods():
    openapi = TestClient(
        app
    ).get(
        "/openapi.json"
    )

    assert openapi.status_code == 200

    paths = openapi.json()[
        "paths"
    ]

    public_path = (
        "/api/donate/intents/"
        "{intent_id}/attribution"
    )

    internal_path = (
        "/api/treasury/user-transfers/"
        "{request_id}/donation-attribution"
    )

    assert public_path in paths
    assert internal_path in paths

    assert set(
        paths[
            public_path
        ]
    ) == {
        "post"
    }

    assert set(
        paths[
            internal_path
        ]
    ) == {
        "post"
    }
