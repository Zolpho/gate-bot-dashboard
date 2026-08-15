from __future__ import annotations

import threading
import time
from uuid import uuid4

from app.db import engine, init_db
from app.treasury_withdrawal_destinations import (
    approve_destination,
    create_candidate_destination,
)


def test_sqlite_runtime_is_wal_with_long_busy_timeout():
    init_db()

    with engine.connect() as conn:
        journal_mode = conn.exec_driver_sql(
            "PRAGMA journal_mode"
        ).scalar()

        busy_timeout = conn.exec_driver_sql(
            "PRAGMA busy_timeout"
        ).scalar()

        synchronous = conn.exec_driver_sql(
            "PRAGMA synchronous"
        ).scalar()

        foreign_keys = conn.exec_driver_sql(
            "PRAGMA foreign_keys"
        ).scalar()

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) >= 30_000

    # FULL
    assert int(synchronous) == 2

    assert int(foreign_keys) == 1


def test_destination_approval_waits_for_short_sqlite_writer():
    init_db()

    address = (
        "0x"
        + uuid4().hex
        + uuid4().hex[:8]
    )

    created = create_candidate_destination(
        owner_account_id="arnold",
        currency="USDT",
        chain="ARBEVM",
        address=address,
        memo="",
        label="SQLite lock regression",
        username="arnold",
    )

    destination_id = (
        created["item"]["destination_id"]
    )

    lock_acquired = threading.Event()
    errors: list[BaseException] = []

    def hold_writer() -> None:
        raw = engine.raw_connection()

        try:
            cursor = raw.cursor()

            try:
                cursor.execute(
                    "BEGIN IMMEDIATE"
                )

                lock_acquired.set()

                # Long enough to prove the approval really
                # waits, but short enough for a fast test.
                time.sleep(0.50)

                raw.commit()

            finally:
                cursor.close()

        except BaseException as exc:
            errors.append(exc)
            lock_acquired.set()

        finally:
            raw.close()

    thread = threading.Thread(
        target=hold_writer,
        daemon=True,
    )

    thread.start()

    assert lock_acquired.wait(timeout=3)

    assert errors == []

    started = time.monotonic()

    approved = approve_destination(
        destination_id=destination_id,
        username="rootadmin",
        reason=(
            "SQLite contention regression test "
            "for Treasury destination approval."
        ),
    )

    elapsed = time.monotonic() - started

    thread.join(timeout=3)

    assert not thread.is_alive()
    assert errors == []

    assert approved["changed"] is True

    assert (
        approved["item"]["status"]
        == "approved"
    )

    # It should have waited for our intentionally held
    # writer instead of immediately throwing SQLITE_BUSY.
    assert elapsed >= 0.30

    # It certainly should not need anything close to the
    # configured 30-second safety timeout.
    assert elapsed < 5
