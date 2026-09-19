from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.auth_recovery import (
    RECOVERY_CODE_COUNT,
    consume_recovery_code,
    hash_recovery_code,
    recovery_code_status,
    revoke_recovery_codes,
    rotate_recovery_codes,
)
from app.db import (
    init_db,
    session_scope,
)
from app.models import (
    DashboardAuthRecoveryCode,
)


def test_recovery_rotation_stores_hashes_only() -> None:
    init_db()

    username = (
        "recovery-hash-user"
    )

    issued = (
        rotate_recovery_codes(
            username=username
        )
    )

    assert len(
        issued["codes"]
    ) == RECOVERY_CODE_COUNT

    assert len(
        set(
            issued["codes"]
        )
    ) == RECOVERY_CODE_COUNT

    assert (
        issued["active_count"]
        == RECOVERY_CODE_COUNT
    )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthRecoveryCode
                ).where(
                    DashboardAuthRecoveryCode
                    .username
                    == username
                )
            )
        )

    assert len(
        rows
    ) == RECOVERY_CODE_COUNT

    raw_codes = set(
        issued["codes"]
    )

    for row in rows:
        assert (
            row.code_hash
            not in raw_codes
        )

        assert len(
            row.code_hash
        ) == 64

        assert (
            row.consumed_at
            is None
        )

        assert (
            row.revoked_at
            is None
        )

    expected_hashes = {
        hash_recovery_code(
            code
        )
        for code in raw_codes
    }

    assert {
        row.code_hash
        for row in rows
    } == expected_hashes


def test_recovery_code_is_one_time() -> None:
    init_db()

    username = (
        "recovery-once-user"
    )

    issued = (
        rotate_recovery_codes(
            username=username
        )
    )

    code = issued[
        "codes"
    ][0]

    assert consume_recovery_code(
        username=username,
        code=code,
    )

    assert not consume_recovery_code(
        username=username,
        code=code,
    )

    status = recovery_code_status(
        username
    )

    assert (
        status["active_count"]
        == RECOVERY_CODE_COUNT - 1
    )

    assert (
        status["consumed_count"]
        == 1
    )


def test_recovery_code_normalization_accepts_case_and_spacing() -> None:
    init_db()

    username = (
        "recovery-normalize-user"
    )

    issued = (
        rotate_recovery_codes(
            username=username,
            count=1,
        )
    )

    code = issued[
        "codes"
    ][0]

    canonical = (
        code
        .replace("-", "")
        .lower()
    )

    spaced = " ".join(
        canonical[index:index + 4]
        for index in range(
            0,
            len(canonical),
            4,
        )
    )

    assert consume_recovery_code(
        username=username,
        code=spaced,
    )


def test_recovery_rotation_revokes_previous_active_set() -> None:
    init_db()

    username = (
        "recovery-rotate-user"
    )

    first = (
        rotate_recovery_codes(
            username=username,
            count=3,
        )
    )

    second = (
        rotate_recovery_codes(
            username=username,
            count=2,
        )
    )

    for old_code in first[
        "codes"
    ]:
        assert not consume_recovery_code(
            username=username,
            code=old_code,
        )

    for new_code in second[
        "codes"
    ]:
        assert consume_recovery_code(
            username=username,
            code=new_code,
        )


def test_revoke_recovery_codes_invalidates_remaining_codes() -> None:
    init_db()

    username = (
        "recovery-revoke-user"
    )

    issued = (
        rotate_recovery_codes(
            username=username,
            count=3,
        )
    )

    revoked = (
        revoke_recovery_codes(
            username=username
        )
    )

    assert revoked == 3

    for code in issued[
        "codes"
    ]:
        assert not consume_recovery_code(
            username=username,
            code=code,
        )

    status = recovery_code_status(
        username
    )

    assert (
        status[
            "active_count"
        ]
        == 0
    )


def test_recovery_timestamps_are_durable() -> None:
    init_db()

    username = (
        "recovery-time-user"
    )

    reference = datetime(
        2026,
        9,
        19,
        12,
        0,
        tzinfo=UTC,
    )

    issued = (
        rotate_recovery_codes(
            username=username,
            count=1,
            now=reference,
        )
    )

    assert (
        issued[
            "generated_at"
        ]
        == reference.isoformat()
    )

    assert consume_recovery_code(
        username=username,
        code=issued[
            "codes"
        ][0],
        now=reference,
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthRecoveryCode
            ).where(
                DashboardAuthRecoveryCode
                .username
                == username
            )
        )

        assert row is not None
        assert row.created_at is not None
        assert row.consumed_at is not None

        # SQLite drops tzinfo on DateTime round-trip.
        # These values are defined by the application as UTC.
        created_at = (
            row.created_at
            if row.created_at.tzinfo is not None
            else row.created_at.replace(
                tzinfo=UTC
            )
        )
        consumed_at = (
            row.consumed_at
            if row.consumed_at.tzinfo is not None
            else row.consumed_at.replace(
                tzinfo=UTC
            )
        )

        assert (
            created_at
            == reference
        )
        assert (
            consumed_at
            == reference
        )
