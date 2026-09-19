from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from .auth_recovery import (
    RECOVERY_CODE_COUNT,
    revoke_recovery_codes_in_session,
    rotate_recovery_codes_in_session,
)
from .auth_totp import (
    TotpEnrollmentError,
    decrypt_totp_secret,
    matching_totp_counter,
)
from .config import Settings
from .db import SessionLocal, engine, utcnow
from .models import (
    DashboardAuthChallenge,
    DashboardAuthEvent,
    DashboardAuthFactor,
    DashboardAuthSession,
)
from .security import load_dashboard_users


class MfaAdminError(RuntimeError):
    """Raised when an administrator MFA reset is invalid."""


def _username(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip().lower()

    if not normalized:
        raise MfaAdminError(
            "Dashboard username is required"
        )

    if len(normalized) > 64:
        raise MfaAdminError(
            "Dashboard username is too long"
        )

    return normalized


def _utc(
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


def _utc_iso(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    return _utc(
        value
    ).isoformat()


def _metadata_json(
    value: dict[str, Any] | None,
) -> str:
    return json.dumps(
        value or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _event_snapshot(
    row: DashboardAuthEvent,
) -> dict[str, Any]:
    try:
        metadata = json.loads(
            row.metadata_json
            or "{}"
        )
    except (
        TypeError,
        json.JSONDecodeError,
    ):
        metadata = {}

    return {
        "id":
            row.id,
        "actor_username":
            row.actor_username,
        "target_username":
            row.target_username,
        "action":
            row.action,
        "reason":
            row.reason,
        "metadata":
            metadata,
        "created_at":
            _utc_iso(
                row.created_at
            ),
    }


def _add_event(
    db,
    *,
    actor_username: str,
    target_username: str,
    action: str,
    reason: str,
    metadata: dict[str, Any] | None,
    now: datetime,
) -> DashboardAuthEvent:
    event = DashboardAuthEvent(
        actor_username=(
            actor_username
        ),
        target_username=(
            target_username
        ),
        action=action,
        reason=reason,
        metadata_json=(
            _metadata_json(
                metadata
            )
        ),
        created_at=now,
    )

    db.add(
        event
    )

    db.flush()

    return event


def complete_totp_enrollment_with_recovery(
    *,
    username: str,
    code: str,
    settings: Settings,
    now: datetime | None = None,
    recovery_count: int = RECOVERY_CODE_COUNT,
) -> dict[str, Any] | None:
    """
    Atomically confirm TOTP, rotate recovery codes and audit.

    Invalid codes return None and leave all durable state
    unchanged.
    """

    normalized = (
        _username(
            username
        )
    )

    reference = (
        _utc(
            now
        )
    )

    db = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        factor = db.get(
            DashboardAuthFactor,
            normalized,
        )

        if factor is None:
            db.rollback()

            raise TotpEnrollmentError(
                "No TOTP enrollment exists for this user"
            )

        if factor.totp_enabled:
            db.rollback()

            raise TotpEnrollmentError(
                "TOTP is already enabled for this user"
            )

        if not (
            factor
            .totp_secret_ciphertext
        ):
            db.rollback()

            raise TotpEnrollmentError(
                "TOTP enrollment has no encrypted secret"
            )

        secret = decrypt_totp_secret(
            factor
            .totp_secret_ciphertext,
            settings=settings,
        )

        counter = (
            matching_totp_counter(
                secret,
                code,
                at=reference,
            )
        )

        if counter is None:
            db.rollback()
            return None

        factor.totp_enabled = True

        factor.totp_confirmed_at = (
            reference
        )

        factor.totp_last_used_counter = (
            counter
        )

        recovery = (
            rotate_recovery_codes_in_session(
                db,
                username=normalized,
                count=recovery_count,
                now=reference,
            )
        )

        event = _add_event(
            db,
            actor_username=normalized,
            target_username=normalized,
            action=(
                "totp_enrollment_completed"
            ),
            reason=(
                "Self-service TOTP enrollment completed"
            ),
            metadata={
                "recovery_code_count":
                    recovery[
                        "active_count"
                    ],
            },
            now=reference,
        )

        result = {
            "username":
                normalized,
            "status":
                "enabled",
            "totp_confirmed_at":
                reference.isoformat(),
            "recovery_codes":
                recovery[
                    "codes"
                ],
            "recovery_code_count":
                recovery[
                    "active_count"
                ],
            "event":
                _event_snapshot(
                    event
                ),
        }

        db.commit()

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def reset_user_mfa(
    *,
    actor_username: str,
    target_username: str,
    reason: str,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Atomically reset all dashboard MFA state for one file-backed
    dashboard identity.

    Authorization of the actor belongs to the API layer. This
    service validates the target against the same user source
    used by dashboard authentication.
    """

    actor = (
        _username(
            actor_username
        )
    )

    target = (
        _username(
            target_username
        )
    )

    normalized_reason = str(
        reason or ""
    ).strip()

    if not normalized_reason:
        raise MfaAdminError(
            "Administrator MFA reset reason is required"
        )

    if len(
        normalized_reason
    ) > 1000:
        raise MfaAdminError(
            "Administrator MFA reset reason is too long"
        )

    users = load_dashboard_users(
        settings
    )

    target_user = next(
        (
            user
            for user in users
            if user.username
            == target
        ),
        None,
    )

    if target_user is None:
        raise MfaAdminError(
            "Dashboard user not found"
        )

    reference = (
        _utc(
            now
        )
    )

    db = SessionLocal()

    try:
        if engine.dialect.name == "sqlite":
            db.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        factor = db.get(
            DashboardAuthFactor,
            target,
        )

        factor_existed = (
            factor is not None
        )

        totp_was_enabled = bool(
            factor
            and factor.totp_enabled
        )

        if factor is not None:
            factor.totp_secret_ciphertext = ""
            factor.totp_enabled = False
            factor.totp_confirmed_at = None
            factor.totp_last_used_counter = None

        recovery_revoked = (
            revoke_recovery_codes_in_session(
                db,
                username=target,
                now=reference,
            )
        )

        sessions = list(
            db.scalars(
                select(
                    DashboardAuthSession
                ).where(
                    DashboardAuthSession
                    .username
                    == target,
                    DashboardAuthSession
                    .revoked_at
                    .is_(None),
                )
            )
        )

        for row in sessions:
            row.revoked_at = (
                reference
            )

        challenges = list(
            db.scalars(
                select(
                    DashboardAuthChallenge
                ).where(
                    DashboardAuthChallenge
                    .username
                    == target,
                    DashboardAuthChallenge
                    .consumed_at
                    .is_(None),
                )
            )
        )

        for row in challenges:
            row.consumed_at = (
                reference
            )

        event = _add_event(
            db,
            actor_username=actor,
            target_username=target,
            action="mfa_reset",
            reason=(
                normalized_reason
            ),
            metadata={
                "factor_existed":
                    factor_existed,
                "totp_was_enabled":
                    totp_was_enabled,
                "recovery_codes_revoked":
                    recovery_revoked,
                "sessions_revoked":
                    len(
                        sessions
                    ),
                "challenges_consumed":
                    len(
                        challenges
                    ),
                "target_enabled":
                    bool(
                        target_user.enabled
                    ),
            },
            now=reference,
        )

        db.flush()

        result = {
            "status":
                "reset",
            "target_username":
                target,
            "factor_existed":
                factor_existed,
            "totp_was_enabled":
                totp_was_enabled,
            "recovery_codes_revoked":
                recovery_revoked,
            "sessions_revoked":
                len(
                    sessions
                ),
            "challenges_consumed":
                len(
                    challenges
                ),
            "event":
                _event_snapshot(
                    event
                ),
        }

        db.commit()

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
