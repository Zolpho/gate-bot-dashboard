from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .bot_control_audit import request_fingerprint
from .db import session_scope, utcnow
from .models import BotControlOperationLock


class OperationLocked(RuntimeError):
    def __init__(
        self,
        lock: dict[str, Any],
    ) -> None:
        self.lock = lock

        super().__init__(
            "Bot Control operation is locked by "
            f"request {lock.get('owner_request_id')}"
        )


def _iso(value: datetime | None) -> str | None:
    return (
        value.isoformat()
        if value is not None
        else None
    )


def _snapshot(
    row: BotControlOperationLock,
) -> dict[str, Any]:
    return {
        "lock_key": row.lock_key,
        "lock_type": row.lock_type,
        "account_id": row.account_id,
        "action": row.action,
        "strategy_id": (
            row.strategy_id or None
        ),
        "strategy_type": (
            row.strategy_type or None
        ),
        "market": (
            row.market or None
        ),
        "intent_hash": (
            row.intent_hash or None
        ),
        "owner_request_id": (
            row.owner_request_id
        ),
        "username": row.username,
        "state": row.state,
        "acquired_at": _iso(
            row.acquired_at
        ),
        "cooldown_until": _iso(
            row.cooldown_until
        ),
    }


def _expired(
    value: datetime | None,
) -> bool:
    if value is None:
        return False

    now = utcnow()

    # SQLite may return DateTime values without
    # tzinfo even for DateTime(timezone=True).
    if value.tzinfo is None:
        now = now.replace(
            tzinfo=None
        )

    return value <= now


def strategy_lock_key(
    *,
    account_id: str,
    strategy_type: str,
    strategy_id: str,
) -> str:
    return (
        "strategy:"
        f"{account_id}:"
        f"{strategy_type}:"
        f"{strategy_id}"
    )


def create_intent_lock(
    *,
    account_id: str,
    gate_payload: Any,
) -> tuple[str, str]:
    fingerprint = request_fingerprint(
        gate_payload
    )

    return (
        (
            "create-intent:"
            f"{account_id}:"
            f"{fingerprint}"
        ),
        fingerprint,
    )


def get_operation_lock(
    lock_key: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.lock_key
                == lock_key
            )
        )

        if row is None:
            return None

        if (
            row.state == "cooldown"
            and _expired(
                row.cooldown_until
            )
        ):
            db.delete(row)
            db.flush()
            return None

        return _snapshot(row)


def get_operation_lock_for_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.owner_request_id
                == request_id
            )
        )

        if row is None:
            return None

        if (
            row.state == "cooldown"
            and _expired(
                row.cooldown_until
            )
        ):
            db.delete(row)
            db.flush()
            return None

        return _snapshot(row)


def _remove_expired_cooldown(
    lock_key: str,
) -> bool:
    with session_scope() as db:
        row = db.scalar(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.lock_key
                == lock_key
            )
        )

        if row is None:
            return True

        if (
            row.state != "cooldown"
            or not _expired(
                row.cooldown_until
            )
        ):
            return False

        db.delete(row)
        db.flush()

        return True


def acquire_operation_lock(
    *,
    lock_key: str,
    lock_type: str,
    account_id: str,
    action: str,
    owner_request_id: str,
    username: str,
    strategy_id: str = "",
    strategy_type: str = "",
    market: str = "",
    intent_hash: str = "",
) -> dict[str, Any]:
    for _ in range(3):
        try:
            with session_scope() as db:
                row = BotControlOperationLock(
                    lock_key=lock_key,
                    lock_type=lock_type,
                    account_id=account_id,
                    action=action,
                    strategy_id=strategy_id,
                    strategy_type=strategy_type,
                    market=market,
                    intent_hash=intent_hash,
                    owner_request_id=(
                        owner_request_id
                    ),
                    username=username,
                    state="held",
                    acquired_at=utcnow(),
                )

                db.add(row)
                db.flush()

                return _snapshot(row)

        except IntegrityError:
            existing = get_operation_lock(
                lock_key
            )

            if existing is None:
                continue

            if (
                existing[
                    "owner_request_id"
                ]
                == owner_request_id
            ):
                return existing

            if (
                existing["state"]
                == "cooldown"
            ):
                removed = (
                    _remove_expired_cooldown(
                        lock_key
                    )
                )

                if removed:
                    continue

            raise OperationLocked(
                existing
            )

    existing = get_operation_lock(
        lock_key
    )

    if existing is not None:
        raise OperationLocked(
            existing
        )

    raise RuntimeError(
        "Unable to acquire Bot Control "
        "operation lock"
    )


def release_operation_lock(
    *,
    lock_key: str,
    owner_request_id: str,
) -> bool:
    with session_scope() as db:
        result = db.execute(
            delete(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.lock_key
                == lock_key,
                BotControlOperationLock.owner_request_id
                == owner_request_id,
            )
        )

        return bool(
            result.rowcount
        )


def cooldown_operation_lock(
    *,
    lock_key: str,
    owner_request_id: str,
    seconds: int,
) -> dict[str, Any] | None:
    seconds = max(
        0,
        int(seconds),
    )

    if seconds == 0:
        release_operation_lock(
            lock_key=lock_key,
            owner_request_id=(
                owner_request_id
            ),
        )
        return None

    with session_scope() as db:
        row = db.scalar(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.lock_key
                == lock_key,
                BotControlOperationLock.owner_request_id
                == owner_request_id,
            )
        )

        if row is None:
            return None

        row.state = "cooldown"
        row.cooldown_until = (
            utcnow()
            + timedelta(
                seconds=seconds
            )
        )

        db.flush()

        return _snapshot(row)


def list_operation_locks(
    *,
    account_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    with session_scope() as db:
        statement = (
            select(
                BotControlOperationLock
            )
            .order_by(
                BotControlOperationLock.acquired_at.desc(),
                BotControlOperationLock.id.desc(),
            )
        )

        if account_ids is not None:
            if not account_ids:
                return []

            statement = statement.where(
                BotControlOperationLock.account_id.in_(
                    sorted(account_ids)
                )
            )

        rows = db.scalars(
            statement
        ).all()

        active: list[dict[str, Any]] = []

        for row in rows:
            if (
                row.state == "cooldown"
                and _expired(
                    row.cooldown_until
                )
            ):
                db.delete(row)
                continue

            active.append(
                _snapshot(row)
            )

        db.flush()

        return active
