from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .db import session_scope, utcnow
from .models import (
    TreasuryWithdrawalOperationLock,
)


class TreasuryWithdrawalLocked(RuntimeError):
    def __init__(
        self,
        lock: dict[str, Any],
    ) -> None:
        self.lock = lock

        super().__init__(
            "Treasury withdrawal custody/currency "
            "is already locked by request "
            f"{lock.get('owner_request_id')}"
        )


def withdrawal_lock_key(
    *,
    custody_account_id: str,
    currency: str,
) -> str:
    return (
        "treasury-withdrawal:"
        f"{custody_account_id.strip().lower()}:"
        f"{currency.strip().upper()}"
    )


def _snapshot(
    row: TreasuryWithdrawalOperationLock,
) -> dict[str, Any]:
    return {
        "lock_key": row.lock_key,
        "owner_account_id": (
            row.owner_account_id
        ),
        "custody_account_id": (
            row.custody_account_id
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


def get_withdrawal_lock(
    lock_key: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalOperationLock
            ).where(
                TreasuryWithdrawalOperationLock
                .lock_key
                == lock_key
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def get_withdrawal_lock_for_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalOperationLock
            ).where(
                TreasuryWithdrawalOperationLock
                .owner_request_id
                == request_id
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def acquire_withdrawal_lock(
    *,
    owner_account_id: str,
    custody_account_id: str,
    currency: str,
    owner_request_id: str,
    username: str,
) -> dict[str, Any]:
    key = withdrawal_lock_key(
        custody_account_id=(
            custody_account_id
        ),
        currency=currency,
    )

    existing_for_request = (
        get_withdrawal_lock_for_request(
            owner_request_id
        )
    )

    if existing_for_request is not None:
        if existing_for_request["lock_key"] == key:
            return existing_for_request

        raise RuntimeError(
            "Treasury withdrawal request already "
            "owns a different operation lock"
        )

    try:
        with session_scope() as db:
            row = TreasuryWithdrawalOperationLock(
                lock_key=key,
                owner_account_id=(
                    owner_account_id
                    .strip()
                    .lower()
                ),
                custody_account_id=(
                    custody_account_id
                    .strip()
                    .lower()
                ),
                currency=(
                    currency.strip().upper()
                ),
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
        existing = get_withdrawal_lock(
            key
        )

        if existing is None:
            raise

        if (
            existing["owner_request_id"]
            == owner_request_id
        ):
            return existing

        raise TreasuryWithdrawalLocked(
            existing
        )


def release_withdrawal_lock(
    *,
    custody_account_id: str,
    currency: str,
    owner_request_id: str,
) -> bool:
    key = withdrawal_lock_key(
        custody_account_id=(
            custody_account_id
        ),
        currency=currency,
    )

    with session_scope() as db:
        result = db.execute(
            delete(
                TreasuryWithdrawalOperationLock
            ).where(
                TreasuryWithdrawalOperationLock
                .lock_key
                == key,
                TreasuryWithdrawalOperationLock
                .owner_request_id
                == owner_request_id,
            )
        )

        return bool(result.rowcount)


def list_withdrawal_locks(
    *,
    owner_account_ids: (
        set[str] | None
    ) = None,
) -> list[dict[str, Any]]:
    if (
        owner_account_ids is not None
        and not owner_account_ids
    ):
        return []

    with session_scope() as db:
        statement = (
            select(
                TreasuryWithdrawalOperationLock
            )
            .order_by(
                TreasuryWithdrawalOperationLock
                .acquired_at.asc(),
                TreasuryWithdrawalOperationLock
                .id.asc(),
            )
        )

        if owner_account_ids is not None:
            statement = statement.where(
                TreasuryWithdrawalOperationLock
                .owner_account_id
                .in_(
                    sorted(owner_account_ids)
                )
            )

        rows = db.scalars(
            statement
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]
