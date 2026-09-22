from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .auth_state import hash_opaque_token
from .db import session_scope, utcnow
from .models import (
    DashboardAuthEvent,
    DashboardAuthSession,
)


class AuthSessionManagementError(
    RuntimeError
):
    """Raised when durable session management cannot proceed."""


def _as_utc(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=UTC
        )

    return value.astimezone(
        UTC
    )


def _now(
    value: datetime | None,
) -> datetime:
    return _as_utc(
        value
        if value is not None
        else utcnow()
    )


def _normalize_username(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip().lower()

    if (
        not normalized
        or len(normalized) > 64
    ):
        raise AuthSessionManagementError(
            "Invalid dashboard username"
        )

    return normalized


def _utc_iso(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    return _as_utc(
        value
    ).isoformat()


def _is_active(
    row: DashboardAuthSession,
    *,
    reference: datetime,
) -> bool:
    return bool(
        row.revoked_at is None
        and _as_utc(
            row.expires_at
        )
        > reference
    )


def _public_session(
    row: DashboardAuthSession,
    *,
    current_token_hash: str,
) -> dict[str, Any]:
    return {
        "id":
            row.id,
        "auth_method":
            row.auth_method,
        "mfa_completed":
            bool(
                row.mfa_completed
            ),
        "created_at":
            _utc_iso(
                row.created_at
            ),
        "expires_at":
            _utc_iso(
                row.expires_at
            ),
        "last_seen_at":
            _utc_iso(
                row.last_seen_at
            ),
        "current":
            hmac.compare_digest(
                row.token_hash,
                current_token_hash,
            ),
    }


def _add_revocation_event(
    db,
    *,
    username: str,
    row: DashboardAuthSession,
    current: bool,
    reason: str,
    now: datetime,
) -> None:
    metadata = {
        "session_id":
            row.id,
        "auth_method":
            row.auth_method,
        "mfa_completed":
            bool(
                row.mfa_completed
            ),
        "current_session":
            bool(
                current
            ),
        "source":
            "security_active_sessions",
    }

    db.add(
        DashboardAuthEvent(
            actor_username=username,
            target_username=username,
            action="session_revoked",
            reason=reason,
            metadata_json=json.dumps(
                metadata,
                sort_keys=True,
                separators=(",", ":"),
            ),
            created_at=now,
        )
    )


def list_active_auth_sessions(
    *,
    username: str,
    current_token: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    normalized_username = (
        _normalize_username(
            username
        )
    )

    current_token_hash = (
        hash_opaque_token(
            current_token
        )
    )

    reference = _now(
        now
    )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthSession
                )
                .where(
                    DashboardAuthSession
                    .username
                    == normalized_username
                )
                .order_by(
                    DashboardAuthSession
                    .created_at
                    .desc(),
                    DashboardAuthSession
                    .id
                    .desc(),
                )
            )
        )

        active = [
            row
            for row in rows
            if _is_active(
                row,
                reference=reference,
            )
        ]

        return [
            _public_session(
                row,
                current_token_hash=(
                    current_token_hash
                ),
            )
            for row in active
        ]


def revoke_active_auth_session_by_id(
    *,
    username: str,
    session_id: int,
    current_token: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    normalized_username = (
        _normalize_username(
            username
        )
    )

    try:
        normalized_session_id = int(
            session_id
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise AuthSessionManagementError(
            "Invalid session id"
        ) from exc

    if normalized_session_id <= 0:
        return None

    current_token_hash = (
        hash_opaque_token(
            current_token
        )
    )

    reference = _now(
        now
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                DashboardAuthSession
            ).where(
                DashboardAuthSession.id
                == normalized_session_id,
                DashboardAuthSession
                .username
                == normalized_username,
            )
        )

        if (
            row is None
            or not _is_active(
                row,
                reference=reference,
            )
        ):
            return None

        current = (
            hmac.compare_digest(
                row.token_hash,
                current_token_hash,
            )
        )

        snapshot = _public_session(
            row,
            current_token_hash=(
                current_token_hash
            ),
        )

        row.revoked_at = reference

        _add_revocation_event(
            db,
            username=normalized_username,
            row=row,
            current=current,
            reason=(
                "User revoked an active "
                "dashboard session."
            ),
            now=reference,
        )

        snapshot[
            "revoked_at"
        ] = _utc_iso(
            reference
        )

        return snapshot


def revoke_other_auth_sessions(
    *,
    username: str,
    current_token: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_username = (
        _normalize_username(
            username
        )
    )

    current_token_hash = (
        hash_opaque_token(
            current_token
        )
    )

    reference = _now(
        now
    )

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    DashboardAuthSession
                )
                .where(
                    DashboardAuthSession
                    .username
                    == normalized_username
                )
                .order_by(
                    DashboardAuthSession
                    .id
                )
            )
        )

        active = [
            row
            for row in rows
            if _is_active(
                row,
                reference=reference,
            )
        ]

        current_row = next(
            (
                row
                for row in active
                if hmac.compare_digest(
                    row.token_hash,
                    current_token_hash,
                )
            ),
            None,
        )

        if current_row is None:
            raise AuthSessionManagementError(
                "Current Bearer session "
                "is not active"
            )

        revoked_ids: list[int] = []

        for row in active:
            if row.id == current_row.id:
                continue

            row.revoked_at = reference

            revoked_ids.append(
                row.id
            )

            _add_revocation_event(
                db,
                username=(
                    normalized_username
                ),
                row=row,
                current=False,
                reason=(
                    "User revoked all other "
                    "active dashboard sessions."
                ),
                now=reference,
            )

        return {
            "current_session_id":
                current_row.id,
            "revoked_count":
                len(
                    revoked_ids
                ),
            "revoked_session_ids":
                revoked_ids,
        }
