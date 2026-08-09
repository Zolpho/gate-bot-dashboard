from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .db import session_scope, utcnow
from .models import TreasuryTransferOperationLock


class TreasuryTransferLocked(RuntimeError):
    def __init__(
        self,
        lock: dict[str, Any],
    ) -> None:
        self.lock = lock

        super().__init__(
            "Treasury transfer source/currency is "
            "already locked by request "
            f"{lock.get('owner_request_id')}"
        )


def transfer_lock_key(
    *,
    source_account_id: str,
    currency: str,
) -> str:
    return (
        "treasury-transfer:"
        f"{source_account_id.strip().lower()}:"
        f"{currency.strip().upper()}"
    )


def _snapshot(
    row: TreasuryTransferOperationLock,
) -> dict[str, Any]:
    return {
        "lock_key": row.lock_key,
        "source_account_id": (
            row.source_account_id
        ),
        "currency": row.currency,
        "owner_request_id": (
            row.owner_request_id
        ),
        "username": row.username,
        "state": row.state,
        "acquired_at": (
            row.acquired_at.isoformat()
            if row.acquired_at
            else None
        ),
    }


def get_transfer_lock(
    lock_key: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryTransferOperationLock
            ).where(
                TreasuryTransferOperationLock.lock_key
                == lock_key
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def acquire_transfer_lock(
    *,
    source_account_id: str,
    currency: str,
    owner_request_id: str,
    username: str,
) -> dict[str, Any]:
    lock_key = transfer_lock_key(
        source_account_id=source_account_id,
        currency=currency,
    )

    try:
        with session_scope() as db:
            row = TreasuryTransferOperationLock(
                lock_key=lock_key,
                source_account_id=(
                    source_account_id
                    .strip()
                    .lower()
                ),
                currency=currency.strip().upper(),
                owner_request_id=owner_request_id,
                username=username,
                state="held",
                acquired_at=utcnow(),
            )

            db.add(row)
            db.flush()

            return _snapshot(row)

    except IntegrityError:
        existing = get_transfer_lock(lock_key)

        if existing is None:
            raise

        if (
            existing["owner_request_id"]
            == owner_request_id
        ):
            return existing

        raise TreasuryTransferLocked(
            existing
        )


def release_transfer_lock(
    *,
    source_account_id: str,
    currency: str,
    owner_request_id: str,
) -> bool:
    lock_key = transfer_lock_key(
        source_account_id=source_account_id,
        currency=currency,
    )

    with session_scope() as db:
        result = db.execute(
            delete(
                TreasuryTransferOperationLock
            ).where(
                TreasuryTransferOperationLock.lock_key
                == lock_key,
                TreasuryTransferOperationLock
                .owner_request_id
                == owner_request_id,
            )
        )

        return bool(result.rowcount)

def get_transfer_lock_for_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryTransferOperationLock
            ).where(
                TreasuryTransferOperationLock
                .owner_request_id
                == request_id
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_transfer_locks(
    *,
    source_account_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if (
        source_account_ids is not None
        and not source_account_ids
    ):
        return []

    with session_scope() as db:
        statement = (
            select(
                TreasuryTransferOperationLock
            )
            .order_by(
                TreasuryTransferOperationLock
                .acquired_at.asc(),
                TreasuryTransferOperationLock
                .id.asc(),
            )
        )

        if source_account_ids is not None:
            statement = statement.where(
                TreasuryTransferOperationLock
                .source_account_id.in_(
                    sorted(source_account_ids)
                )
            )

        rows = db.scalars(statement).all()

        return [
            _snapshot(row)
            for row in rows
        ]
