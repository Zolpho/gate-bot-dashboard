from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    delete,
    func,
    select,
    text,
)

from .config import Settings
from .db import SessionLocal, engine, utcnow
from .models import BotControlRateLimitEvent


MUTATION_ACTIONS = {
    "spot_grid_create",
    "bot_stop",
}


@dataclass(frozen=True)
class RateLimitPolicy:
    user_limit: int
    user_window_seconds: int

    account_limit: int | None = None
    account_window_seconds: int | None = None


class BotControlRateLimitExceeded(RuntimeError):
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
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after_seconds = max(
            1,
            int(retry_after_seconds),
        )

        super().__init__(
            "Bot Control rate limit exceeded"
        )

    def detail(self) -> dict[str, Any]:
        return {
            "message": (
                "Bot Control rate limit exceeded"
            ),
            "scope": self.scope,
            "action": self.action,
            "limit": self.limit,
            "window_seconds": (
                self.window_seconds
            ),
            "retry_after_seconds": (
                self.retry_after_seconds
            ),
        }


def _bounded_limit(value: int) -> int:
    return max(
        1,
        min(int(value), 10000),
    )


def _bounded_window(value: int) -> int:
    return max(
        1,
        min(int(value), 86400),
    )


def policy_for_action(
    settings: Settings,
    action: str,
) -> RateLimitPolicy | None:
    if not settings.bot_control_rate_limit_enabled:
        return None

    if action == "spot_grid_create":
        return RateLimitPolicy(
            user_limit=_bounded_limit(
                settings
                .bot_control_create_user_limit
            ),
            user_window_seconds=_bounded_window(
                settings
                .bot_control_create_user_window_seconds
            ),
            account_limit=_bounded_limit(
                settings
                .bot_control_account_mutation_limit
            ),
            account_window_seconds=_bounded_window(
                settings
                .bot_control_account_mutation_window_seconds
            ),
        )

    if action == "bot_stop":
        return RateLimitPolicy(
            user_limit=_bounded_limit(
                settings
                .bot_control_stop_user_limit
            ),
            user_window_seconds=_bounded_window(
                settings
                .bot_control_stop_user_window_seconds
            ),
            account_limit=_bounded_limit(
                settings
                .bot_control_account_mutation_limit
            ),
            account_window_seconds=_bounded_window(
                settings
                .bot_control_account_mutation_window_seconds
            ),
        )

    if action == "reconcile":
        return RateLimitPolicy(
            user_limit=_bounded_limit(
                settings
                .bot_control_reconcile_user_limit
            ),
            user_window_seconds=_bounded_window(
                settings
                .bot_control_reconcile_user_window_seconds
            ),
        )

    if action == "lock_release":
        return RateLimitPolicy(
            user_limit=_bounded_limit(
                settings
                .bot_control_lock_release_user_limit
            ),
            user_window_seconds=_bounded_window(
                settings
                .bot_control_lock_release_user_window_seconds
            ),
        )

    return None


def _normalize_datetime(
    value: datetime,
    reference: datetime,
) -> datetime:
    if value.tzinfo is None:
        return reference.replace(
            tzinfo=None
        )

    return reference


def _retry_after(
    *,
    oldest: datetime | None,
    now: datetime,
    window_seconds: int,
) -> int:
    if oldest is None:
        return max(
            1,
            window_seconds,
        )

    reference_now = _normalize_datetime(
        oldest,
        now,
    )

    expires = (
        oldest
        + timedelta(
            seconds=window_seconds
        )
    )

    return max(
        1,
        int(
            math.ceil(
                (
                    expires
                    - reference_now
                ).total_seconds()
            )
        ),
    )


def check_and_record_rate_limit(
    *,
    username: str,
    account_id: str,
    action: str,
    policy: RateLimitPolicy,
) -> dict[str, Any]:
    now = utcnow()

    user_since = (
        now
        - timedelta(
            seconds=(
                policy.user_window_seconds
            )
        )
    )

    account_since = None

    if policy.account_window_seconds:
        account_since = (
            now
            - timedelta(
                seconds=(
                    policy
                    .account_window_seconds
                )
            )
        )

    session = SessionLocal()

    try:
        # SQLite's BEGIN IMMEDIATE serializes the
        # count+insert sequence so concurrent requests
        # cannot both pass the same remaining slot.
        if engine.dialect.name == "sqlite":
            session.execute(
                text("BEGIN IMMEDIATE")
            )

        # Keep the table small. Config windows are capped
        # at one day, so anything older than two days can
        # never affect a decision.
        session.execute(
            delete(
                BotControlRateLimitEvent
            ).where(
                BotControlRateLimitEvent.created_at
                < (
                    now
                    - timedelta(days=2)
                )
            )
        )

        user_filter = (
            BotControlRateLimitEvent.username
            == username,
            BotControlRateLimitEvent.action
            == action,
            BotControlRateLimitEvent.created_at
            >= user_since,
        )

        user_count = int(
            session.scalar(
                select(
                    func.count(
                        BotControlRateLimitEvent.id
                    )
                ).where(
                    *user_filter
                )
            )
            or 0
        )

        if user_count >= policy.user_limit:
            oldest = session.scalar(
                select(
                    BotControlRateLimitEvent.created_at
                )
                .where(
                    *user_filter
                )
                .order_by(
                    BotControlRateLimitEvent
                    .created_at.asc()
                )
                .limit(1)
            )

            retry_after = _retry_after(
                oldest=oldest,
                now=now,
                window_seconds=(
                    policy.user_window_seconds
                ),
            )

            session.rollback()

            raise BotControlRateLimitExceeded(
                scope="user",
                action=action,
                limit=policy.user_limit,
                window_seconds=(
                    policy.user_window_seconds
                ),
                retry_after_seconds=(
                    retry_after
                ),
            )

        account_count = None

        if (
            action in MUTATION_ACTIONS
            and policy.account_limit
            is not None
            and policy.account_window_seconds
            is not None
            and account_since
            is not None
        ):
            account_filter = (
                BotControlRateLimitEvent.account_id
                == account_id,
                BotControlRateLimitEvent.action.in_(
                    sorted(
                        MUTATION_ACTIONS
                    )
                ),
                BotControlRateLimitEvent.created_at
                >= account_since,
            )

            account_count = int(
                session.scalar(
                    select(
                        func.count(
                            BotControlRateLimitEvent.id
                        )
                    ).where(
                        *account_filter
                    )
                )
                or 0
            )

            if (
                account_count
                >= policy.account_limit
            ):
                oldest = session.scalar(
                    select(
                        BotControlRateLimitEvent
                        .created_at
                    )
                    .where(
                        *account_filter
                    )
                    .order_by(
                        BotControlRateLimitEvent
                        .created_at.asc()
                    )
                    .limit(1)
                )

                retry_after = _retry_after(
                    oldest=oldest,
                    now=now,
                    window_seconds=(
                        policy
                        .account_window_seconds
                    ),
                )

                session.rollback()

                raise (
                    BotControlRateLimitExceeded(
                        scope="account",
                        action=action,
                        limit=(
                            policy
                            .account_limit
                        ),
                        window_seconds=(
                            policy
                            .account_window_seconds
                        ),
                        retry_after_seconds=(
                            retry_after
                        ),
                    )
                )

        row = BotControlRateLimitEvent(
            username=username,
            account_id=account_id,
            action=action,
            created_at=now,
        )

        session.add(row)
        session.commit()

        return {
            "allowed": True,
            "username": username,
            "account_id": account_id,
            "action": action,
            "user_count": (
                user_count + 1
            ),
            "user_limit": (
                policy.user_limit
            ),
            "account_count": (
                (
                    account_count + 1
                )
                if account_count
                is not None
                else None
            ),
            "account_limit": (
                policy.account_limit
            ),
        }

    except BotControlRateLimitExceeded:
        raise

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def enforce_rate_limit(
    *,
    settings: Settings,
    username: str,
    account_id: str,
    action: str,
) -> dict[str, Any] | None:
    policy = policy_for_action(
        settings,
        action,
    )

    if policy is None:
        return None

    return check_and_record_rate_limit(
        username=username,
        account_id=account_id,
        action=action,
        policy=policy,
    )
