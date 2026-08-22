from __future__ import annotations

import math
from datetime import (
    datetime,
    timedelta,
)
from typing import Any

from sqlalchemy import (
    delete,
    func,
    select,
    text,
)

from .config import Settings
from .db import (
    SessionLocal,
    engine,
    utcnow,
)
from .models import (
    TradingRateLimitEvent,
)


TRADING_LIMIT_ORDER_EXECUTE = (
    "limit_order_execute"
)

TRADING_ORDER_CANCEL = (
    "order_cancel"
)


class TradingRateLimitExceeded(
    RuntimeError
):
    def __init__(
        self,
        *,
        scope: str,
        limit: int,
        window_seconds: int,
        retry_after_seconds: int,
        action: str = TRADING_LIMIT_ORDER_EXECUTE,
    ) -> None:
        self.scope = scope
        self.action = action
        self.limit = limit
        self.window_seconds = (
            window_seconds
        )
        self.retry_after_seconds = max(
            1,
            int(retry_after_seconds),
        )

        super().__init__(
            "Trading rate limit exceeded"
        )

    def detail(
        self,
    ) -> dict[str, Any]:
        return {
            "message": (
                "Trading rate limit exceeded"
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
            "gate_write_performed": False,
            "write_performed": False,
        }


def _bounded_limit(
    value: int,
) -> int:
    return max(
        1,
        min(
            int(value),
            10000,
        ),
    )


def _bounded_window(
    value: int,
) -> int:
    return max(
        1,
        min(
            int(value),
            86400,
        ),
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
            window_seconds,
        )

    reference_now = (
        _normalize_now(
            oldest,
            now,
        )
    )

    expiry = (
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
                    expiry
                    - reference_now
                ).total_seconds()
            )
        ),
    )


def enforce_trading_rate_limit(
    *,
    settings: Settings,
    username: str,
    account_id: str,
    action: str = TRADING_LIMIT_ORDER_EXECUTE,
    user_limit_override: int | None = None,
    user_window_override: int | None = None,
    account_limit_override: int | None = None,
    account_window_override: int | None = None,
) -> dict[str, Any] | None:
    if not (
        settings
        .trading_rate_limit_enabled
    ):
        return None

    normalized_action = (
        action.strip()
    )

    if not normalized_action:
        raise ValueError(
            "action cannot be empty"
        )

    user_limit = _bounded_limit(
        (
            user_limit_override
            if user_limit_override is not None
            else settings
            .trading_limit_order_user_limit
        )
    )

    user_window = _bounded_window(
        (
            user_window_override
            if user_window_override is not None
            else settings
            .trading_limit_order_user_window_seconds
        )
    )

    account_limit = _bounded_limit(
        (
            account_limit_override
            if account_limit_override is not None
            else settings
            .trading_limit_order_account_limit
        )
    )

    account_window = _bounded_window(
        (
            account_window_override
            if account_window_override is not None
            else settings
            .trading_limit_order_account_window_seconds
        )
    )

    normalized_account = (
        account_id.strip().lower()
    )

    if not normalized_account:
        raise ValueError(
            "account_id cannot be empty"
        )

    if not username.strip():
        raise ValueError(
            "username cannot be empty"
        )

    now = utcnow()

    user_since = (
        now
        - timedelta(
            seconds=user_window
        )
    )

    account_since = (
        now
        - timedelta(
            seconds=account_window
        )
    )

    session = SessionLocal()

    try:
        # Serialize count + insert under SQLite.
        if engine.dialect.name == "sqlite":
            session.execute(
                text("BEGIN IMMEDIATE")
            )

        session.execute(
            delete(
                TradingRateLimitEvent
            ).where(
                TradingRateLimitEvent
                .created_at
                < (
                    now
                    - timedelta(days=2)
                )
            )
        )

        user_filter = (
            TradingRateLimitEvent.username
            == username,
            TradingRateLimitEvent.action
            == normalized_action,
            TradingRateLimitEvent.created_at
            >= user_since,
        )

        user_count = int(
            session.scalar(
                select(
                    func.count(
                        TradingRateLimitEvent.id
                    )
                ).where(
                    *user_filter
                )
            )
            or 0
        )

        if user_count >= user_limit:
            oldest = session.scalar(
                select(
                    TradingRateLimitEvent
                    .created_at
                )
                .where(
                    *user_filter
                )
                .order_by(
                    TradingRateLimitEvent
                    .created_at.asc()
                )
                .limit(1)
            )

            retry_after = (
                _retry_after(
                    oldest=oldest,
                    now=now,
                    window_seconds=(
                        user_window
                    ),
                )
            )

            session.rollback()

            raise (
                TradingRateLimitExceeded(
                    scope="user",
                    limit=user_limit,
                    window_seconds=(
                        user_window
                    ),
                    retry_after_seconds=(
                        retry_after
                    ),
                    action=(
                        normalized_action
                    ),
                )
            )

        account_filter = (
            TradingRateLimitEvent
            .account_id
            == normalized_account,
            TradingRateLimitEvent.action
            == normalized_action,
            TradingRateLimitEvent
            .created_at
            >= account_since,
        )

        account_count = int(
            session.scalar(
                select(
                    func.count(
                        TradingRateLimitEvent.id
                    )
                ).where(
                    *account_filter
                )
            )
            or 0
        )

        if (
            account_count
            >= account_limit
        ):
            oldest = session.scalar(
                select(
                    TradingRateLimitEvent
                    .created_at
                )
                .where(
                    *account_filter
                )
                .order_by(
                    TradingRateLimitEvent
                    .created_at.asc()
                )
                .limit(1)
            )

            retry_after = (
                _retry_after(
                    oldest=oldest,
                    now=now,
                    window_seconds=(
                        account_window
                    ),
                )
            )

            session.rollback()

            raise (
                TradingRateLimitExceeded(
                    scope="account",
                    limit=account_limit,
                    window_seconds=(
                        account_window
                    ),
                    retry_after_seconds=(
                        retry_after
                    ),
                    action=(
                        normalized_action
                    ),
                )
            )

        session.add(
            TradingRateLimitEvent(
                username=username,
                account_id=(
                    normalized_account
                ),
                action=(
                    normalized_action
                ),
                created_at=now,
            )
        )

        session.commit()

        return {
            "action": (
                normalized_action
            ),
            "user_count": (
                user_count + 1
            ),
            "user_limit": user_limit,
            "account_count": (
                account_count + 1
            ),
            "account_limit": (
                account_limit
            ),
        }

    except TradingRateLimitExceeded:
        raise

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()

def enforce_trading_cancel_rate_limit(
    *,
    settings: Settings,
    username: str,
    account_id: str,
) -> dict[str, Any] | None:
    """
    Apply the independent Spot cancellation bucket.

    This deliberately shares the persistent event table
    with order creation but never shares the action key
    or quota counters.
    """
    return enforce_trading_rate_limit(
        settings=settings,
        username=username,
        account_id=account_id,
        action=TRADING_ORDER_CANCEL,
        user_limit_override=(
            settings
            .trading_order_cancel_user_limit
        ),
        user_window_override=(
            settings
            .trading_order_cancel_user_window_seconds
        ),
        account_limit_override=(
            settings
            .trading_order_cancel_account_limit
        ),
        account_window_override=(
            settings
            .trading_order_cancel_account_window_seconds
        ),
    )
