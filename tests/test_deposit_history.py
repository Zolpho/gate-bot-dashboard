from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.deposit_history import normalize_deposit, upsert_deposit_rows
from app.models import DepositRecord, GateAccount


def test_normalize_and_upsert_deposit_status_change() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(GateAccount(id="zolnode", name="zolnode", enabled=True, configured=True))
        session.commit()

        raw = {
            "id": "d123",
            "txid": "0xabc",
            "timestamp": "1785686400",
            "amount": "123.456789123456789",
            "currency": "EQTY",
            "address": "0xdeposit",
            "memo": "",
            "status": "TRACK",
            "chain": "BASE",
        }
        normalized = normalize_deposit("zolnode", raw)
        assert normalized["currency"] == "EQTY"
        assert str(normalized["amount"]) == "123.456789123456789"

        now = datetime.now(timezone.utc)
        assert upsert_deposit_rows(session, "zolnode", [raw], seen_at=now) == (1, 0)
        session.commit()

        raw["status"] = "DONE"
        assert upsert_deposit_rows(session, "zolnode", [raw], seen_at=now) == (0, 1)
        session.commit()

        row = session.scalar(select(DepositRecord))
        assert row is not None
        assert row.status == "DONE"
        assert row.gate_deposit_id == "d123"

def test_sync_window_accepts_naive_sqlite_datetimes() -> None:
    from types import SimpleNamespace

    from app.deposit_history import _window
    from app.models import DepositSyncState

    now = datetime(2026, 8, 2, 16, 30, tzinfo=timezone.utc)

    state = DepositSyncState(account_id="zolnode")
    # SQLite commonly returns timezone-naive datetime objects.
    state.last_reconciliation_at = datetime(2026, 8, 2, 15, 30)
    state.last_success_at = datetime(2026, 8, 2, 16, 0)

    settings = SimpleNamespace(
        deposit_initial_lookback_days=30,
        deposit_reconcile_hours=24,
        deposit_sync_overlap_seconds=3600,
    )

    start, end, full = _window(
        state,
        settings,
        now,
        full=False,
    )

    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert end == now
    assert full is False

