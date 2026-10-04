from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.db import (
    Base,
    SessionLocal,
    engine,
)
from app.donation_destinations import (
    BLOCKED_STATUS,
    TRUSTED_STATUS,
    DonationDestinationBootstrapError,
    bootstrap_public_destination,
    has_trusted_public_destination,
    verify_public_destination,
)
from app.models import (
    PublicDonationDestination,
)


def _detail(
    *,
    address: str = "0xAbCdEf",
    memo: str | None = None,
    chain: str = "BASE",
) -> dict:
    return {
        "currency": "USDT",
        "network": {
            "chain": chain,
            "name": "Base",
            "address": address,
            "payment_id": memo,
            "deposit_enabled": True,
        },
    }


def _reset() -> None:
    Base.metadata.create_all(
        bind=engine
    )

    with SessionLocal() as session:
        session.execute(
            delete(
                PublicDonationDestination
            )
        )

        session.commit()


def _single_row() -> PublicDonationDestination:
    with SessionLocal() as session:
        row = session.query(
            PublicDonationDestination
        ).one()

        session.expunge(
            row
        )

        return row


def test_public_donation_table_is_created() -> None:
    _reset()

    assert (
        PublicDonationDestination
        .__tablename__
        == "public_donation_destinations"
    )


def test_missing_trust_fails_closed_without_inserting() -> None:
    _reset()

    with SessionLocal() as session:
        decision = (
            verify_public_destination(
                session,
                _detail(),
            )
        )

        session.commit()

        rows = list(
            session.query(
                PublicDonationDestination
            )
        )

    assert decision.state == "untrusted"
    assert decision.destination_id is None
    assert rows == []


def test_missing_trust_is_not_considered_trusted() -> None:
    _reset()

    with SessionLocal() as session:
        assert not has_trusted_public_destination(
            session,
            currency="USDT",
            chain="BASE",
        )


def test_operator_bootstrap_establishes_trust() -> None:
    _reset()

    with SessionLocal() as session:
        decision = (
            bootstrap_public_destination(
                session,
                _detail(),
            )
        )

        session.commit()

        row = session.get(
            PublicDonationDestination,
            decision.destination_id,
        )

        assert decision.state == "bootstrapped"
        assert row is not None
        assert row.currency == "USDT"
        assert row.chain_key == "BASE"
        assert row.address == "0xAbCdEf"
        assert row.memo == ""
        assert row.status == TRUSTED_STATUS


def test_bootstrap_makes_precheck_trusted() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(),
        )

        session.commit()

    with SessionLocal() as session:
        assert has_trusted_public_destination(
            session,
            currency="usdt",
            chain="base",
        )


def test_identical_bootstrap_rerun_is_idempotent() -> None:
    _reset()

    with SessionLocal() as session:
        first = (
            bootstrap_public_destination(
                session,
                _detail(),
            )
        )

        session.commit()

        row = session.get(
            PublicDonationDestination,
            first.destination_id,
        )

        assert row is not None

        first_published_at = (
            row.first_published_at
        )

        updated_at = row.updated_at

    with SessionLocal() as session:
        second = (
            bootstrap_public_destination(
                session,
                _detail(
                    address="0xabcdef",
                ),
            )
        )

        session.commit()

        rows = list(
            session.query(
                PublicDonationDestination
            )
        )

    assert (
        second.destination_id
        == first.destination_id
    )

    assert (
        second.state
        == "already_trusted"
    )

    assert len(rows) == 1

    assert (
        rows[0].first_published_at
        == first_published_at
    )

    assert (
        rows[0].updated_at
        == updated_at
    )


def test_bootstrap_mismatch_refuses_without_mutation() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(
                address="0x1111",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        with pytest.raises(
            DonationDestinationBootstrapError
        ):
            bootstrap_public_destination(
                session,
                _detail(
                    address="0x2222",
                ),
            )

        session.rollback()

    row = _single_row()

    assert row.status == TRUSTED_STATUS
    assert row.address == "0x1111"
    assert row.observed_address == ""
    assert row.blocked_at is None


def test_identical_observation_remains_verified() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(),
        )

        session.commit()

    with SessionLocal() as session:
        decision = (
            verify_public_destination(
                session,
                _detail(
                    address="0xabcdef",
                ),
            )
        )

        session.commit()

        row = session.get(
            PublicDonationDestination,
            decision.destination_id,
        )

    assert decision.state == "verified"
    assert row is not None
    assert row.status == TRUSTED_STATUS


def test_address_change_blocks_without_replacing_trust() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(
                address="0x1111",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        decision = (
            verify_public_destination(
                session,
                _detail(
                    address="0x2222",
                ),
            )
        )

        session.commit()

        row = session.get(
            PublicDonationDestination,
            decision.destination_id,
        )

        assert decision.state == "blocked"
        assert row is not None
        assert row.status == BLOCKED_STATUS
        assert row.address == "0x1111"
        assert row.observed_address == "0x2222"
        assert row.blocked_at is not None


def test_memo_change_blocks_destination() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(
                memo="111",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        decision = (
            verify_public_destination(
                session,
                _detail(
                    memo="222",
                ),
            )
        )

        session.commit()

        row = session.get(
            PublicDonationDestination,
            decision.destination_id,
        )

        assert row is not None
        assert row.memo == "111"
        assert row.observed_memo == "222"
        assert row.status == BLOCKED_STATUS


def test_blocked_destination_never_auto_recovers() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(
                address="0x1111",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        verify_public_destination(
            session,
            _detail(
                address="0x2222",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        decision = (
            verify_public_destination(
                session,
                _detail(
                    address="0x1111",
                ),
            )
        )

        session.commit()

        row = session.get(
            PublicDonationDestination,
            decision.destination_id,
        )

        assert decision.state == "blocked"
        assert row is not None
        assert row.status == BLOCKED_STATUS


def test_blocked_destination_fails_precheck() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(
                address="0x1111",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        verify_public_destination(
            session,
            _detail(
                address="0x2222",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        assert not has_trusted_public_destination(
            session,
            currency="USDT",
            chain="BASE",
        )


def test_bootstrap_cannot_replace_blocked_row() -> None:
    _reset()

    with SessionLocal() as session:
        bootstrap_public_destination(
            session,
            _detail(
                address="0x1111",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        verify_public_destination(
            session,
            _detail(
                address="0x2222",
            ),
        )

        session.commit()

    with SessionLocal() as session:
        with pytest.raises(
            DonationDestinationBootstrapError
        ):
            bootstrap_public_destination(
                session,
                _detail(
                    address="0x1111",
                ),
            )

        session.rollback()

    row = _single_row()

    assert row.status == BLOCKED_STATUS
    assert row.address == "0x1111"
