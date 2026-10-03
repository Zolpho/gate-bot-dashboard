from __future__ import annotations

from sqlalchemy import delete

from app.db import (
    Base,
    SessionLocal,
    engine,
)
from app.donation_destinations import (
    BLOCKED_STATUS,
    TRUSTED_STATUS,
    verify_or_pin_public_destination,
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


def test_public_donation_table_is_created() -> None:
    _reset()

    assert (
        PublicDonationDestination
        .__tablename__
        == "public_donation_destinations"
    )


def test_first_observation_establishes_trust() -> None:
    _reset()

    with SessionLocal() as session:
        decision = (
            verify_or_pin_public_destination(
                session,
                _detail(),
            )
        )

        session.commit()

        row = session.get(
            PublicDonationDestination,
            decision.destination_id,
        )

        assert decision.state == "first_seen"
        assert row is not None
        assert row.currency == "USDT"
        assert row.chain_key == "BASE"
        assert row.address == "0xAbCdEf"
        assert row.memo == ""
        assert row.status == TRUSTED_STATUS


def test_identical_observation_remains_verified() -> None:
    _reset()

    with SessionLocal() as session:
        first = (
            verify_or_pin_public_destination(
                session,
                _detail(),
            )
        )
        session.commit()

    with SessionLocal() as session:
        second = (
            verify_or_pin_public_destination(
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

    assert first.destination_id == second.destination_id
    assert second.state == "verified"
    assert len(rows) == 1
    assert rows[0].status == TRUSTED_STATUS


def test_address_change_blocks_without_replacing_pin() -> None:
    _reset()

    with SessionLocal() as session:
        verify_or_pin_public_destination(
            session,
            _detail(
                address="0x1111",
            ),
        )
        session.commit()

    with SessionLocal() as session:
        decision = (
            verify_or_pin_public_destination(
                session,
                _detail(
                    address="0x2222",
                ),
            )
        )
        session.commit()

        row = session.scalar(
            session.query(
                PublicDonationDestination
            ).statement
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
        verify_or_pin_public_destination(
            session,
            _detail(
                memo="111",
            ),
        )
        session.commit()

    with SessionLocal() as session:
        decision = (
            verify_or_pin_public_destination(
                session,
                _detail(
                    memo="222",
                ),
            )
        )
        session.commit()

        row = session.scalar(
            session.query(
                PublicDonationDestination
            ).statement
        )

        assert decision.state == "blocked"
        assert row is not None
        assert row.memo == "111"
        assert row.observed_memo == "222"


def test_blocked_destination_never_auto_recovers() -> None:
    _reset()

    with SessionLocal() as session:
        verify_or_pin_public_destination(
            session,
            _detail(
                address="0x1111",
            ),
        )
        session.commit()

    with SessionLocal() as session:
        verify_or_pin_public_destination(
            session,
            _detail(
                address="0x2222",
            ),
        )
        session.commit()

    with SessionLocal() as session:
        decision = (
            verify_or_pin_public_destination(
                session,
                _detail(
                    address="0x1111",
                ),
            )
        )
        session.commit()

        row = session.scalar(
            session.query(
                PublicDonationDestination
            ).statement
        )

        assert decision.state == "blocked"
        assert row is not None
        assert row.status == BLOCKED_STATUS
