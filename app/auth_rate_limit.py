from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text

from .auth_state import hash_opaque_token
from .config import Settings
from .db import SessionLocal, engine, utcnow
from .models import DashboardAuthRateLimitEvent

PASSWORD_LOGIN = "password_login"
MFA_LOGIN = "mfa_login"

AUTH_RATE_ACTIONS = {
    PASSWORD_LOGIN,
    MFA_LOGIN,
}


@dataclass(frozen=True)
class AuthRateLimitPolicy:
    user_limit: int
    user_window_seconds: int
    challenge_limit: int | None = None
    challenge_window_seconds: int | None = None


class AuthRateLimitExceeded(RuntimeError):
    def __init__(
        self,
        *,
        scope: str,
        action: str,
        limit: int,
        window_seconds: int,
        retry_after_seconds: int,
    ) -> None:
        self.scope = scope
        self.action = action
        self.limit = int(
            limit
        )
        self.window_seconds = int(
            window_seconds
        )
        self.retry_after_seconds = max(
            1,
            int(
                retry_after_seconds
            ),
        )

        super().__init__(
            "Authentication rate limit exceeded"
        )

    def detail(
        self,
    ) -> dict[str, Any]:
        return {
            "message":
                "Authentication rate limit exceeded",
            "scope":
                self.scope,
            "action":
                self.action,
            "limit":
                self.limit,
            "window_seconds":
                self.window_seconds,
            "retry_after_seconds":
                self.retry_after_seconds,
        }


def hash_rate_limit_subject(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip().lower()

    if not normalized:
        normalized = "<empty>"

    return hashlib.sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()


def _policy_for_action(
    settings: Settings,
    action: str,
) -> AuthRateLimitPolicy:
    if action == PASSWORD_LOGIN:
        return AuthRateLimitPolicy(
            user_limit=(
                settings
                .dashboard_auth_password_attempt_limit
            ),
            user_window_seconds=(
                settings
                .dashboard_auth_password_attempt_window_seconds
            ),
        )

    if action == MFA_LOGIN:
        return AuthRateLimitPolicy(
            user_limit=(
                settings
                .dashboard_auth_mfa_user_attempt_limit
            ),
            user_window_seconds=(
                settings
                .dashboard_auth_mfa_attempt_window_seconds
            ),
            challenge_limit=(
                settings
                .dashboard_auth_mfa_challenge_attempt_limit
            ),
            challenge_window_seconds=(
                settings
                .dashboard_auth_mfa_attempt_window_seconds
            ),
        )

    raise ValueError(
        f"Unknown authentication rate-limit action: {action}"
    )


def _normalize_now(
    oldest: datetime,
    now: datetime,
) -> datetime:
    if oldest.tzinfo is None:
        return now.replace(
            tzinfo=None
        )

    return now


def _retry_after(
    *,
    oldest: datetime | None,
    now: datetime,
    window_seconds: int,
) -> int:
    if oldest is None:
        return max(
            1,
            int(
                window_seconds
            ),
        )

    reference_now = (
        _normalize_now(
            oldest,
            now,
        )
    )

    expires_at = (
        oldest
        + timedelta(
            seconds=(
                window_seconds
            )
        )
    )

    return max(
        1,
        int(
            math.ceil(
                (
                    expires_at
                    - reference_now
                ).total_seconds()
            )
        ),
    )


def _count(
    session,
    *filters,
) -> int:
    return int(
        session.scalar(
            select(
                func.count(
                    DashboardAuthRateLimitEvent.id
                )
            ).where(
                *filters
            )
        )
        or 0
    )


def _oldest(
    session,
    *filters,
) -> datetime | None:
    return session.scalar(
        select(
            DashboardAuthRateLimitEvent
            .created_at
        )
        .where(
            *filters
        )
        .order_by(
            DashboardAuthRateLimitEvent
            .created_at
            .asc()
        )
        .limit(1)
    )


def _raise_if_full(
    session,
    *,
    filters: tuple,
    count: int,
    scope: str,
    action: str,
    limit: int,
    window_seconds: int,
    now: datetime,
) -> None:
    if count < limit:
        return

    oldest = _oldest(
        session,
        *filters,
    )

    retry_after = _retry_after(
        oldest=oldest,
        now=now,
        window_seconds=(
            window_seconds
        ),
    )

    raise AuthRateLimitExceeded(
        scope=scope,
        action=action,
        limit=limit,
        window_seconds=(
            window_seconds
        ),
        retry_after_seconds=(
            retry_after
        ),
    )


def enforce_auth_rate_limit(
    *,
    settings: Settings,
    username: str,
    action: str,
    client_identifier: str | None = None,
    challenge_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Reserve one persistent authentication-attempt slot.

    Every attempt consumes a slot, including a successful one.
    That prevents repeated valid-password challenge creation from
    becoming an MFA brute-force bypass.

    Raw identifiers and challenge tokens are never persisted.
    """

    if not (
        settings
        .dashboard_auth_rate_limit_enabled
    ):
        return None

    normalized_action = str(
        action or ""
    ).strip()

    if normalized_action not in AUTH_RATE_ACTIONS:
        raise ValueError(
            "Unknown authentication rate-limit action"
        )

    policy = _policy_for_action(
        settings,
        normalized_action,
    )

    username_hash = (
        hash_rate_limit_subject(
            username
        )
    )

    client_hash = ""

    if (
        client_identifier
        is not None
        and str(
            client_identifier
        ).strip()
    ):
        client_hash = (
            hash_rate_limit_subject(
                client_identifier
            )
        )

    challenge_hash = ""

    if normalized_action == MFA_LOGIN:
        if not challenge_token:
            raise ValueError(
                "MFA authentication attempts require a challenge token"
            )

        challenge_hash = (
            hash_opaque_token(
                challenge_token
            )
        )

    reference = (
        now
        if now is not None
        else utcnow()
    )

    user_since = (
        reference
        - timedelta(
            seconds=(
                policy
                .user_window_seconds
            )
        )
    )

    client_since = (
        reference
        - timedelta(
            seconds=(
                settings
                .dashboard_auth_client_attempt_window_seconds
            )
        )
    )

    challenge_since = None

    if (
        policy
        .challenge_window_seconds
        is not None
    ):
        challenge_since = (
            reference
            - timedelta(
                seconds=(
                    policy
                    .challenge_window_seconds
                )
            )
        )

    session = SessionLocal()

    try:
        # Same durable serialization strategy already used by
        # Treasury/Trading rate limiters in this project.
        if engine.dialect.name == "sqlite":
            session.execute(
                text(
                    "BEGIN IMMEDIATE"
                )
            )

        session.execute(
            delete(
                DashboardAuthRateLimitEvent
            ).where(
                DashboardAuthRateLimitEvent
                .created_at
                < (
                    reference
                    - timedelta(days=2)
                )
            )
        )

        user_filter = (
            DashboardAuthRateLimitEvent
            .username_hash
            == username_hash,
            DashboardAuthRateLimitEvent
            .action
            == normalized_action,
            DashboardAuthRateLimitEvent
            .created_at
            >= user_since,
        )

        user_count = _count(
            session,
            *user_filter,
        )

        _raise_if_full(
            session,
            filters=user_filter,
            count=user_count,
            scope="username",
            action=normalized_action,
            limit=(
                policy.user_limit
            ),
            window_seconds=(
                policy
                .user_window_seconds
            ),
            now=reference,
        )

        client_count = None

        if client_hash:
            client_filter = (
                DashboardAuthRateLimitEvent
                .client_hash
                == client_hash,
                DashboardAuthRateLimitEvent
                .created_at
                >= client_since,
            )

            client_count = _count(
                session,
                *client_filter,
            )

            _raise_if_full(
                session,
                filters=client_filter,
                count=client_count,
                scope="client",
                action=normalized_action,
                limit=(
                    settings
                    .dashboard_auth_client_attempt_limit
                ),
                window_seconds=(
                    settings
                    .dashboard_auth_client_attempt_window_seconds
                ),
                now=reference,
            )

        challenge_count = None

        if (
            challenge_hash
            and policy.challenge_limit
            is not None
            and challenge_since
            is not None
        ):
            challenge_filter = (
                DashboardAuthRateLimitEvent
                .challenge_hash
                == challenge_hash,
                DashboardAuthRateLimitEvent
                .action
                == normalized_action,
                DashboardAuthRateLimitEvent
                .created_at
                >= challenge_since,
            )

            challenge_count = _count(
                session,
                *challenge_filter,
            )

            _raise_if_full(
                session,
                filters=challenge_filter,
                count=challenge_count,
                scope="challenge",
                action=normalized_action,
                limit=(
                    policy
                    .challenge_limit
                ),
                window_seconds=(
                    policy
                    .challenge_window_seconds
                    or policy
                    .user_window_seconds
                ),
                now=reference,
            )

        session.add(
            DashboardAuthRateLimitEvent(
                action=(
                    normalized_action
                ),
                username_hash=(
                    username_hash
                ),
                client_hash=(
                    client_hash
                ),
                challenge_hash=(
                    challenge_hash
                ),
                created_at=(
                    reference
                ),
            )
        )

        session.commit()

        return {
            "action":
                normalized_action,
            "username_count":
                user_count + 1,
            "username_limit":
                policy.user_limit,
            "client_count":
                (
                    client_count + 1
                    if client_count
                    is not None
                    else None
                ),
            "client_limit":
                (
                    settings
                    .dashboard_auth_client_attempt_limit
                    if client_hash
                    else None
                ),
            "challenge_count":
                (
                    challenge_count + 1
                    if challenge_count
                    is not None
                    else None
                ),
            "challenge_limit":
                (
                    policy.challenge_limit
                    if challenge_hash
                    else None
                ),
        }

    except AuthRateLimitExceeded:
        session.rollback()
        raise

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()
