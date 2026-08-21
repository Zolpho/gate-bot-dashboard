from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    delete,
    select,
)
from sqlalchemy.exc import (
    IntegrityError,
)

from .db import (
    session_scope,
    utcnow,
)
from .models import (
    TradingOrderOperationLock,
)


class TradingOrderLocked(
    RuntimeError
):
    def __init__(
        self,
        lock: dict[str, Any],
    ) -> None:
        self.lock = lock

        super().__init__(
            "Spot Trading account/funding "
            "asset is already locked by "
            "request "
            f"{lock.get('owner_request_id')}"
        )


def trading_lock_key(
    *,
    account_id: str,
    funding_asset: str,
) -> str:
    return (
        "trading:"
        f"{account_id.strip().lower()}:"
        f"{funding_asset.strip().upper()}"
    )


def _utc_iso(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )
    else:
        value = value.astimezone(
            timezone.utc
        )

    return value.isoformat()


def _snapshot(
    row: TradingOrderOperationLock,
) -> dict[str, Any]:
    return {
        "lock_key": row.lock_key,
        "account_id": row.account_id,
        "funding_asset": (
            row.funding_asset
        ),
        "pair": row.pair,
        "side": row.side,
        "owner_request_id": (
            row.owner_request_id
        ),
        "username": row.username,
        "state": row.state,
        "acquired_at": _utc_iso(
            row.acquired_at
        ),
        "cooldown_until": _utc_iso(
            row.cooldown_until
        ),
    }


def get_trading_lock(
    lock_key: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderOperationLock
            ).where(
                TradingOrderOperationLock
                .lock_key
                == lock_key
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def acquire_trading_lock(
    *,
    account_id: str,
    funding_asset: str,
    pair: str,
    side: str,
    owner_request_id: str,
    username: str,
) -> dict[str, Any]:
    normalized_account = (
        account_id.strip().lower()
    )

    normalized_asset = (
        funding_asset.strip().upper()
    )

    normalized_pair = (
        pair.strip().upper()
    )

    normalized_side = (
        side.strip().lower()
    )

    if not normalized_account:
        raise ValueError(
            "account_id cannot be empty"
        )

    if not normalized_asset:
        raise ValueError(
            "funding_asset cannot be empty"
        )

    if normalized_side not in {
        "buy",
        "sell",
    }:
        raise ValueError(
            "side must be buy or sell"
        )

    lock_key = trading_lock_key(
        account_id=(
            normalized_account
        ),
        funding_asset=(
            normalized_asset
        ),
    )

    try:
        with session_scope() as db:
            row = (
                TradingOrderOperationLock(
                    lock_key=lock_key,
                    account_id=(
                        normalized_account
                    ),
                    funding_asset=(
                        normalized_asset
                    ),
                    pair=normalized_pair,
                    side=normalized_side,
                    owner_request_id=(
                        owner_request_id
                    ),
                    username=username,
                    state="held",
                    acquired_at=utcnow(),
                )
            )

            db.add(row)
            db.flush()

            return _snapshot(row)

    except IntegrityError:
        existing = get_trading_lock(
            lock_key
        )

        if existing is None:
            raise

        if (
            existing[
                "owner_request_id"
            ]
            == owner_request_id
        ):
            if (
                existing["pair"]
                != normalized_pair
                or existing["side"]
                != normalized_side
            ):
                raise RuntimeError(
                    "Trading request already "
                    "owns this lock with "
                    "different order metadata"
                )

            return existing

        raise TradingOrderLocked(
            existing
        )


def release_trading_lock(
    *,
    account_id: str,
    funding_asset: str,
    owner_request_id: str,
) -> bool:
    lock_key = trading_lock_key(
        account_id=account_id,
        funding_asset=(
            funding_asset
        ),
    )

    with session_scope() as db:
        result = db.execute(
            delete(
                TradingOrderOperationLock
            ).where(
                TradingOrderOperationLock
                .lock_key
                == lock_key,
                TradingOrderOperationLock
                .owner_request_id
                == owner_request_id,
            )
        )

        return bool(
            result.rowcount
        )


def get_trading_lock_for_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderOperationLock
            ).where(
                TradingOrderOperationLock
                .owner_request_id
                == request_id
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_trading_locks(
    *,
    account_ids: set[str]
    | None = None,
) -> list[dict[str, Any]]:
    if (
        account_ids is not None
        and not account_ids
    ):
        return []

    with session_scope() as db:
        statement = (
            select(
                TradingOrderOperationLock
            )
            .order_by(
                TradingOrderOperationLock
                .acquired_at.asc(),
                TradingOrderOperationLock
                .id.asc(),
            )
        )

        if account_ids is not None:
            statement = (
                statement.where(
                    TradingOrderOperationLock
                    .account_id.in_(
                        sorted(
                            account_ids
                        )
                    )
                )
            )

        rows = db.scalars(
            statement
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]
