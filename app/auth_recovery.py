from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import SessionLocal, engine, session_scope, utcnow
from .models import DashboardAuthRecoveryCode

RECOVERY_CODE_BYTES = 16
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_HEX_LENGTH = (
    RECOVERY_CODE_BYTES
    * 2
)

_HEX = frozenset(
    string.hexdigits
)


class RecoveryCodeError(RuntimeError):
    """Raised when recovery-code state or input is invalid."""


def _normalize_username(
    username: str,
) -> str:
    normalized = str(
        username or ""
    ).strip().lower()

    if not normalized:
        raise RecoveryCodeError(
            "username cannot be empty"
        )

    if len(normalized) > 64:
        raise RecoveryCodeError(
            "username is too long"
        )

    return normalized


def _normalize_time(
    value: datetime | None,
) -> datetime:
    current = (
        value
        if value is not None
        else utcnow()
    )

    if current.tzinfo is None:
        return current.replace(
            tzinfo=UTC
        )

    return current.astimezone(
        UTC
    )


def _canonical_code(
    code: str,
) -> str:
    canonical = (
        str(
            code or ""
        )
        .replace("-", "")
        .replace(" ", "")
        .strip()
        .upper()
    )

    if (
        len(canonical)
        != RECOVERY_CODE_HEX_LENGTH
    ):
        raise RecoveryCodeError(
            "Recovery code has invalid length"
        )

    if any(
        character not in _HEX
        for character in canonical
    ):
        raise RecoveryCodeError(
            "Recovery code contains invalid characters"
        )

    return canonical


def _format_code(
    canonical: str,
) -> str:
    return "-".join(
        canonical[index:index + 4]
        for index in range(
            0,
            len(canonical),
            4,
        )
    )


def generate_recovery_code() -> str:
    canonical = secrets.token_hex(
        RECOVERY_CODE_BYTES
    ).upper()

    return _format_code(
        canonical
    )


def hash_recovery_code(
    code: str,
) -> str:
    canonical = (
        _canonical_code(
            code
        )
    )

    return hashlib.sha256(
        canonical.encode(
            "ascii"
        )
    ).hexdigest()


def _status_snapshot(
    rows: list[
        DashboardAuthRecoveryCode
    ],
) -> dict[str, Any]:
    active = [
        row
        for row in rows
        if (
            row.consumed_at is None
            and row.revoked_at is None
        )
    ]

    consumed = [
        row
        for row in rows
        if row.consumed_at
        is not None
    ]

    latest_created = max(
        (
            row.created_at
            for row in rows
            if row.created_at
            is not None
        ),
        default=None,
    )

    return {
        "has_recovery_codes":
            bool(active),
        "active_count":
            len(active),
        "consumed_count":
            len(consumed),
        "generated_at":
            (
                latest_created
                .isoformat()
                if latest_created
                else None
            ),
    }


def recovery_code_status(
    username: str,
) -> dict[str, Any]:
    normalized = (
        _normalize_username(
            username
        )
    )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthRecoveryCode
                )
                .where(
                    DashboardAuthRecoveryCode
                    .username
                    == normalized
                )
                .order_by(
                    DashboardAuthRecoveryCode
                    .created_at
                    .asc()
                )
            )
        )

    return {
        "username":
            normalized,
        **_status_snapshot(
            rows
        ),
    }


def rotate_recovery_codes_in_session(
    db: Session,
    *,
    username: str,
    count: int = RECOVERY_CODE_COUNT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Replace the active recovery-code set inside an existing
    caller-owned transaction.

    This function flushes but never commits.
    """

    normalized = (
        _normalize_username(
            username
        )
    )

    requested_count = int(
        count
    )

    if (
        requested_count < 1
        or requested_count > 20
    ):
        raise RecoveryCodeError(
            "Recovery code count must be between 1 and 20"
        )

    reference = (
        _normalize_time(
            now
        )
    )

    raw_codes: list[str] = []
    hashes: set[str] = set()

    while len(
        raw_codes
    ) < requested_count:
        candidate = (
            generate_recovery_code()
        )

        digest = (
            hash_recovery_code(
                candidate
            )
        )

        if digest in hashes:
            continue

        hashes.add(
            digest
        )

        raw_codes.append(
            candidate
        )

    batch_id = secrets.token_hex(
        16
    )

    existing = list(
        db.scalars(
            select(
                DashboardAuthRecoveryCode
            ).where(
                DashboardAuthRecoveryCode
                .username
                == normalized,
                DashboardAuthRecoveryCode
                .consumed_at
                .is_(None),
                DashboardAuthRecoveryCode
                .revoked_at
                .is_(None),
            )
        )
    )

    for row in existing:
        row.revoked_at = (
            reference
        )

    for code in raw_codes:
        db.add(
            DashboardAuthRecoveryCode(
                username=(
                    normalized
                ),
                batch_id=batch_id,
                code_hash=(
                    hash_recovery_code(
                        code
                    )
                ),
                created_at=(
                    reference
                ),
            )
        )

    db.flush()

    return {
        "username":
            normalized,
        "codes":
            raw_codes,
        "active_count":
            len(
                raw_codes
            ),
        "generated_at":
            reference.isoformat(),
    }


def rotate_recovery_codes(
    *,
    username: str,
    count: int = RECOVERY_CODE_COUNT,
    now: datetime | None = None,
) -> dict[str, Any]:
    db = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        result = (
            rotate_recovery_codes_in_session(
                db,
                username=username,
                count=count,
                now=now,
            )
        )

        db.commit()

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def consume_recovery_code(
    *,
    username: str,
    code: str,
    now: datetime | None = None,
) -> bool:
    normalized = (
        _normalize_username(
            username
        )
    )

    try:
        digest = (
            hash_recovery_code(
                code
            )
        )
    except RecoveryCodeError:
        return False

    reference = (
        _normalize_time(
            now
        )
    )

    db = SessionLocal()

    try:
        # Serialize lookup + consume so the same one-time code
        # cannot succeed twice under concurrent requests.
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        row = db.scalar(
            select(
                DashboardAuthRecoveryCode
            ).where(
                DashboardAuthRecoveryCode
                .username
                == normalized,
                DashboardAuthRecoveryCode
                .code_hash
                == digest,
                DashboardAuthRecoveryCode
                .consumed_at
                .is_(None),
                DashboardAuthRecoveryCode
                .revoked_at
                .is_(None),
            )
        )

        if row is None:
            db.rollback()
            return False

        row.consumed_at = (
            reference
        )

        db.commit()

        return True

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def revoke_recovery_codes_in_session(
    db: Session,
    *,
    username: str,
    now: datetime | None = None,
) -> int:
    """
    Revoke all currently active recovery codes inside an
    existing caller-owned transaction.

    This function flushes but never commits.
    """

    normalized = (
        _normalize_username(
            username
        )
    )

    reference = (
        _normalize_time(
            now
        )
    )

    rows = list(
        db.scalars(
            select(
                DashboardAuthRecoveryCode
            ).where(
                DashboardAuthRecoveryCode
                .username
                == normalized,
                DashboardAuthRecoveryCode
                .consumed_at
                .is_(None),
                DashboardAuthRecoveryCode
                .revoked_at
                .is_(None),
            )
        )
    )

    for row in rows:
        row.revoked_at = (
            reference
        )

    db.flush()

    return len(
        rows
    )


def revoke_recovery_codes(
    *,
    username: str,
    now: datetime | None = None,
) -> int:
    db = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        count = (
            revoke_recovery_codes_in_session(
                db,
                username=username,
                now=now,
            )
        )

        db.commit()

        return count

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

def consume_recovery_code_in_session(
    db: Session,
    *,
    username: str,
    code: str,
    now: datetime | None = None,
) -> bool:
    """
    Consume one recovery code inside a caller-owned transaction.

    The caller owns serialization, commit and rollback.
    """

    normalized = (
        _normalize_username(
            username
        )
    )

    try:
        digest = (
            hash_recovery_code(
                code
            )
        )
    except RecoveryCodeError:
        return False

    reference = (
        _normalize_time(
            now
        )
    )

    row = db.scalar(
        select(
            DashboardAuthRecoveryCode
        ).where(
            DashboardAuthRecoveryCode
            .username
            == normalized,
            DashboardAuthRecoveryCode
            .code_hash
            == digest,
            DashboardAuthRecoveryCode
            .consumed_at
            .is_(None),
            DashboardAuthRecoveryCode
            .revoked_at
            .is_(None),
        )
    )

    if row is None:
        return False

    row.consumed_at = (
        reference
    )

    db.flush()

    return True
