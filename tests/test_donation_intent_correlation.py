from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest
from sqlalchemy import (
    create_engine,
    select,
)
from sqlalchemy.orm import sessionmaker

from app.deposit_history import (
    upsert_deposit_rows,
)
from app.donation_ledger import (
    INTENT_EXPIRED,
    INTENT_MATCHED,
    INTENT_PENDING,
    INTENT_SUBMITTED,
    DonationLedgerInvariantError,
    create_donation_intent,
    donation_intent_claim_matches,
    reconcile_external_donation_intent,
    submit_donation_intent_txid,
)
from app.models import (
    DepositRecord,
    DonationEvent,
    DonationIntent,
)


NOW = datetime(
    2026,
    10,
    10,
    10,
    0,
    tzinfo=timezone.utc,
)

DEPOSITED = NOW + timedelta(
    minutes=5
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
    )

    DepositRecord.__table__.create(
        engine
    )

    DonationEvent.__table__.create(
        engine
    )

    DonationIntent.__table__.create(
        engine
    )

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return engine, factory()


def _intent(
    db,
    *,
    currency: str = "EQTY",
    chain_key: str = "BASEEVM",
    chain: str = "Base",
    expires_at: datetime | None = None,
):
    return create_donation_intent(
        db,
        currency=currency,
        chain_key=chain_key,
        chain=chain,
        expires_at=(
            expires_at
            or (
                NOW
                + timedelta(
                    minutes=30
                )
            )
        ),
        now=NOW,
    )


def _deposit(
    db,
    *,
    gate_id: str,
    txid: str,
    account_id: str = "eqtydao",
    currency: str = "EQTY",
    chain: str = "BASE-EVM",
    status: str = "DONE",
    amount: str = "12.345678901234567890123456",
) -> None:
    upsert_deposit_rows(
        db,
        account_id,
        [
            {
                "id": gate_id,
                "txid": txid,
                "currency": currency,
                "chain": chain,
                "amount": amount,
                "status": status,
                "timestamp": str(
                    int(
                        DEPOSITED.timestamp()
                    )
                ),
                "address":
                    "0xDonationAddress",
                "memo": "",
            }
        ],
        seen_at=DEPOSITED,
    )

    db.flush()


def _event_count(
    db,
) -> int:
    return len(
        db.scalars(
            select(
                DonationEvent
            )
        ).all()
    )


def test_txid_submission_consumes_one_time_claim() -> None:
    engine, db = _session()

    try:
        public, claim = _intent(
            db
        )

        result = (
            submit_donation_intent_txid(
                db,
                intent_id=
                    public["intent_id"],
                claim_token=claim,
                txid="0xexternal-txid",
                now=(
                    NOW
                    + timedelta(
                        minutes=1
                    )
                ),
            )
        )

        row = db.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == public["intent_id"]
            )
        )

        assert row is not None

        assert (
            row.status
            == INTENT_SUBMITTED
        )

        assert (
            row.submitted_txid
            == "0xexternal-txid"
        )

        assert (
            row.claim_token_hash
            == (
                "!consumed:"
                + row.intent_id
            )
        )

        assert (
            donation_intent_claim_matches(
                row,
                claim,
            )
            is False
        )

        assert (
            result["status"]
            == INTENT_SUBMITTED
        )

        assert (
            result["match_status"]
            == "awaiting_match"
        )

        assert (
            result["txid_submitted"]
            is True
        )

        assert (
            "submitted_txid"
            not in result
        )

        assert (
            "claim_token_hash"
            not in result
        )

        assert (
            "0xexternal-txid"
            not in repr(result)
        )

        with pytest.raises(
            DonationLedgerInvariantError,
            match="not pending",
        ):
            submit_donation_intent_txid(
                db,
                intent_id=
                    public["intent_id"],
                claim_token=claim,
                txid="0xexternal-txid",
                now=(
                    NOW
                    + timedelta(
                        minutes=2
                    )
                ),
            )

    finally:
        db.close()
        engine.dispose()


def test_expired_intent_never_accepts_txid() -> None:
    engine, db = _session()

    try:
        public, claim = _intent(
            db,
            expires_at=(
                NOW
                + timedelta(
                    minutes=1
                )
            ),
        )

        result = (
            submit_donation_intent_txid(
                db,
                intent_id=
                    public["intent_id"],
                claim_token=claim,
                txid="too-late",
                now=(
                    NOW
                    + timedelta(
                        minutes=2
                    )
                ),
            )
        )

        row = db.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == public["intent_id"]
            )
        )

        assert row is not None
        assert row.status == INTENT_EXPIRED
        assert row.submitted_txid == ""

        assert (
            row.claim_token_hash
            == (
                "!expired:"
                + row.intent_id
            )
        )

        assert (
            donation_intent_claim_matches(
                row,
                claim,
            )
            is False
        )

        assert (
            result["status"]
            == INTENT_EXPIRED
        )

        assert (
            result["txid_submitted"]
            is False
        )

        assert _event_count(db) == 0

    finally:
        db.close()
        engine.dispose()


def test_exact_done_eqtydao_deposit_matches() -> None:
    engine, db = _session()

    try:
        public, claim = _intent(
            db
        )

        txid = "0xone-exact-match"

        # Same txid but wrong Wallet account.
        _deposit(
            db,
            gate_id="wrong-account",
            txid=txid,
            account_id="zolnode",
        )

        # Same txid but not DONE.
        _deposit(
            db,
            gate_id="not-done",
            txid=txid,
            status="PENDING",
        )

        # Same txid but wrong currency.
        _deposit(
            db,
            gate_id="wrong-currency",
            txid=txid,
            currency="USDT",
        )

        # Same txid but wrong network.
        _deposit(
            db,
            gate_id="wrong-chain",
            txid=txid,
            chain="ETH",
        )

        # The only exact candidate.
        _deposit(
            db,
            gate_id="exact-deposit",
            txid=txid,
            chain="BASE-EVM",
        )

        submit_donation_intent_txid(
            db,
            intent_id=
                public["intent_id"],
            claim_token=claim,
            txid=txid,
            now=(
                NOW
                + timedelta(
                    minutes=6
                )
            ),
        )

        result = (
            reconcile_external_donation_intent(
                db,
                intent_id=
                    public["intent_id"],
                now=(
                    NOW
                    + timedelta(
                        minutes=7
                    )
                ),
            )
        )

        intent = db.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == public["intent_id"]
            )
        )

        events = db.scalars(
            select(
                DonationEvent
            )
        ).all()

        assert intent is not None

        assert (
            intent.status
            == INTENT_MATCHED
        )

        assert (
            result["status"]
            == INTENT_MATCHED
        )

        assert (
            result["match_status"]
            == "matched"
        )

        assert len(events) == 1

        event = events[0]

        assert (
            intent.matched_event_id
            == event.event_id
        )

        assert (
            event.source_type
            == "external_deposit"
        )

        assert (
            event.source_key
            == "eqtydao:exact-deposit"
        )

        assert event.currency == "EQTY"

        assert (
            event.chain_key
            == "BASEEVM"
        )

        assert (
            event.chain
            == "BASE-EVM"
        )

        assert (
            str(event.amount)
            == "12.345678901234567890123456"
        )

        # Correlation secrets/identifiers do not leak through
        # the safe intent result.
        assert txid not in repr(result)

        assert (
            "exact-deposit"
            not in repr(result)
        )

    finally:
        db.close()
        engine.dispose()


def test_ambiguous_done_match_fails_closed() -> None:
    engine, db = _session()

    try:
        public, claim = _intent(
            db
        )

        txid = "ambiguous-txid"

        _deposit(
            db,
            gate_id="duplicate-a",
            txid=txid,
        )

        _deposit(
            db,
            gate_id="duplicate-b",
            txid=txid,
        )

        submit_donation_intent_txid(
            db,
            intent_id=
                public["intent_id"],
            claim_token=claim,
            txid=txid,
            now=(
                NOW
                + timedelta(
                    minutes=6
                )
            ),
        )

        with pytest.raises(
            DonationLedgerInvariantError,
            match="ambiguous",
        ):
            reconcile_external_donation_intent(
                db,
                intent_id=
                    public["intent_id"],
                now=(
                    NOW
                    + timedelta(
                        minutes=7
                    )
                ),
            )

        intent = db.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == public["intent_id"]
            )
        )

        assert intent is not None

        assert (
            intent.status
            == INTENT_SUBMITTED
        )

        assert (
            intent.matched_event_id
            is None
        )

        assert _event_count(db) == 0

    finally:
        db.close()
        engine.dispose()


def test_same_txid_cannot_be_claimed_by_two_intents() -> None:
    engine, db = _session()

    try:
        first, first_claim = _intent(
            db
        )

        second, second_claim = _intent(
            db
        )

        submit_donation_intent_txid(
            db,
            intent_id=
                first["intent_id"],
            claim_token=first_claim,
            txid="shared-txid",
            now=(
                NOW
                + timedelta(
                    minutes=1
                )
            ),
        )

        with pytest.raises(
            DonationLedgerInvariantError,
            match="another intent",
        ):
            submit_donation_intent_txid(
                db,
                intent_id=
                    second["intent_id"],
                claim_token=
                    second_claim,
                txid="shared-txid",
                now=(
                    NOW
                    + timedelta(
                        minutes=2
                    )
                ),
            )

        second_row = db.scalar(
            select(
                DonationIntent
            ).where(
                DonationIntent.intent_id
                == second["intent_id"]
            )
        )

        assert second_row is not None

        assert (
            second_row.status
            == INTENT_PENDING
        )

        assert (
            second_row.submitted_txid
            == ""
        )

        assert (
            second_row.claim_token_hash
            != ""
        )

    finally:
        db.close()
        engine.dispose()


def test_unrelated_historical_deposit_is_never_backfilled() -> None:
    engine, db = _session()

    try:
        _deposit(
            db,
            gate_id="historical-existing",
            txid="historical-txid",
        )

        public, claim = _intent(
            db
        )

        submit_donation_intent_txid(
            db,
            intent_id=
                public["intent_id"],
            claim_token=claim,
            txid="new-not-yet-seen-txid",
            now=(
                NOW
                + timedelta(
                    minutes=1
                )
            ),
        )

        result = (
            reconcile_external_donation_intent(
                db,
                intent_id=
                    public["intent_id"],
                now=(
                    NOW
                    + timedelta(
                        minutes=2
                    )
                ),
            )
        )

        assert (
            result["status"]
            == INTENT_SUBMITTED
        )

        assert (
            result["match_status"]
            == "not_found"
        )

        assert _event_count(db) == 0

    finally:
        db.close()
        engine.dispose()


def test_matched_reconciliation_is_idempotent() -> None:
    engine, db = _session()

    try:
        public, claim = _intent(
            db
        )

        _deposit(
            db,
            gate_id="idempotent-deposit",
            txid="idempotent-txid",
        )

        submit_donation_intent_txid(
            db,
            intent_id=
                public["intent_id"],
            claim_token=claim,
            txid="idempotent-txid",
            now=(
                NOW
                + timedelta(
                    minutes=6
                )
            ),
        )

        first = (
            reconcile_external_donation_intent(
                db,
                intent_id=
                    public["intent_id"],
                now=(
                    NOW
                    + timedelta(
                        minutes=7
                    )
                ),
            )
        )

        second = (
            reconcile_external_donation_intent(
                db,
                intent_id=
                    public["intent_id"],
                now=(
                    NOW
                    + timedelta(
                        minutes=8
                    )
                ),
            )
        )

        assert (
            first["matched_event_id"]
            == second["matched_event_id"]
        )

        assert (
            first["match_status"]
            == "matched"
        )

        assert (
            second["match_status"]
            == "matched"
        )

        assert _event_count(db) == 1

    finally:
        db.close()
        engine.dispose()



def test_multiple_consumed_claims_remain_unique() -> None:
    engine, db = _session()

    try:
        first, first_claim = _intent(
            db
        )

        second, second_claim = _intent(
            db
        )

        submit_donation_intent_txid(
            db,
            intent_id=
                first["intent_id"],
            claim_token=first_claim,
            txid="first-independent-txid",
            now=(
                NOW
                + timedelta(
                    minutes=1
                )
            ),
        )

        # This is the lifecycle case that a shared empty-string
        # tombstone cannot support under the schema's UNIQUE
        # claim_token_hash constraint.
        submit_donation_intent_txid(
            db,
            intent_id=
                second["intent_id"],
            claim_token=second_claim,
            txid="second-independent-txid",
            now=(
                NOW
                + timedelta(
                    minutes=2
                )
            ),
        )

        db.flush()

        rows = db.scalars(
            select(
                DonationIntent
            )
        ).all()

        by_id = {
            row.intent_id: row
            for row in rows
        }

        first_row = by_id[
            first["intent_id"]
        ]

        second_row = by_id[
            second["intent_id"]
        ]

        assert (
            first_row.status
            == INTENT_SUBMITTED
        )

        assert (
            second_row.status
            == INTENT_SUBMITTED
        )

        assert (
            first_row.claim_token_hash
            == (
                "!consumed:"
                + first_row.intent_id
            )
        )

        assert (
            second_row.claim_token_hash
            == (
                "!consumed:"
                + second_row.intent_id
            )
        )

        assert (
            first_row.claim_token_hash
            != second_row.claim_token_hash
        )

        assert len(
            first_row.claim_token_hash
        ) <= 64

        assert len(
            second_row.claim_token_hash
        ) <= 64

        assert (
            donation_intent_claim_matches(
                first_row,
                first_claim,
            )
            is False
        )

        assert (
            donation_intent_claim_matches(
                second_row,
                second_claim,
            )
            is False
        )

    finally:
        db.close()
        engine.dispose()
