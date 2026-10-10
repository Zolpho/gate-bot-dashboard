from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

import pytest

from app import (
    treasury_user_transfer_execution
    as execution,
)
from app.db import (
    init_db,
    session_scope,
)
from app.donation_ledger import (
    DonationLedgerInvariantError,
    materialize_internal_transfer_donation,
)
from app.models import (
    DonationAttribution,
    DonationEvent,
    DonationIntent,
)


init_db()


@pytest.fixture(autouse=True)
def clean_donation_state():
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


def _record(
    **overrides,
):
    base = {
        "request_id":
            "req-donation-one",
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
            "1.250000000000000000000001",
        "status":
            "success",
        "simulation":
            False,
        "write_performed":
            True,
        "request": {
            "donation":
                True,
        },
        "completed_at":
            datetime(
                2026,
                10,
                10,
                13,
                45,
                tzinfo=timezone.utc,
            ).isoformat(),
    }

    base.update(
        overrides
    )

    return base


def test_confirmed_eqtydao_transfer_materializes_once():
    first, first_created = (
        materialize_internal_transfer_donation(
            _record()
        )
    )

    assert first is not None
    assert first_created is True

    assert (
        first["source_type"]
        == "internal_transfer"
    )

    assert (
        first["source_key"]
        == "request:req-donation-one"
    )

    assert first["currency"] == "USDT"

    assert first["amount"] == (
        "1.250000000000000000000001"
    )

    assert first["chain_key"] == ""
    assert first["chain"] == ""
    assert first["demo"] is False

    second, second_created = (
        materialize_internal_transfer_donation(
            _record()
        )
    )

    assert second is not None
    assert second_created is False
    assert (
        second["event_id"]
        == first["event_id"]
    )

    with session_scope() as db:
        assert (
            db.query(
                DonationEvent
            ).count()
            == 1
        )


@pytest.mark.parametrize(
    "changes",
    [
        {
            "status":
                "submitted",
        },
        {
            "status":
                "failed",
        },
        {
            "destination_account_id":
                "arnold",
        },
        {
            "direction":
                "from",
        },
    ],
)
def test_nonqualifying_transfer_is_ignored(
    changes,
):
    event, created = (
        materialize_internal_transfer_donation(
            _record(
                **changes
            )
        )
    )

    assert event is None
    assert created is False

    with session_scope() as db:
        assert (
            db.query(
                DonationEvent
            ).count()
            == 0
        )


def test_success_without_explicit_donation_marker_is_ignored():
    for request_payload in (
        {},
        {
            "donation":
                False,
        },
        {
            "donation":
                "true",
        },
    ):
        event, created = (
            materialize_internal_transfer_donation(
                _record(
                    request=(
                        request_payload
                    )
                )
            )
        )

        assert event is None
        assert created is False

    with session_scope() as db:
        assert (
            db.query(
                DonationEvent
            ).count()
            == 0
        )


def test_simulation_cannot_become_real_donation():
    with pytest.raises(
        DonationLedgerInvariantError,
        match="Simulated",
    ):
        materialize_internal_transfer_donation(
            _record(
                simulation=True
            )
        )


def test_success_without_recorded_gate_write_fails_closed():
    with pytest.raises(
        DonationLedgerInvariantError,
        match="Gate write",
    ):
        materialize_internal_transfer_donation(
            _record(
                write_performed=False
            )
        )


def test_existing_success_replay_repairs_missing_donation(
    monkeypatch,
):
    calls = []

    def fake_materialize(
        record,
    ):
        calls.append(
            record["request_id"]
        )

        return {
            "status":
                "recorded",
            "created":
                True,
            "event_id":
                "don_evt_test",
            "currency":
                "USDT",
            "amount":
                "1",
            "occurred_at":
                "2026-10-10T13:45:00+00:00",
        }

    monkeypatch.setattr(
        execution,
        "_materialize_internal_donation",
        fake_materialize,
    )

    result = (
        execution
        .existing_user_transfer_result(
            _record()
        )
    )

    assert calls == [
        "req-donation-one"
    ]

    assert (
        result["status"]
        == "success"
    )

    assert (
        result["idempotent_replay"]
        is True
    )

    assert (
        result["donation"][
            "event_id"
        ]
        == "don_evt_test"
    )


def test_public_transfer_result_does_not_expose_source_key():
    result = (
        execution
        .existing_user_transfer_result(
            _record()
        )
    )

    donation = result[
        "donation"
    ]

    assert (
        donation["status"]
        == "recorded"
    )

    assert (
        "source_key"
        not in donation
    )

    assert (
        donation["event_id"]
        .startswith(
            "don_evt_"
        )
    )
