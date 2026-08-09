from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from .db import session_scope
from .models import (
    TreasuryTransferLockResolution,
    TreasuryTransferOperationLock,
    TreasuryTransferReconciliation,
    TreasuryTransferRequest,
)


class TreasuryLockResolutionError(RuntimeError):
    pass


def _snapshot(
    row: TreasuryTransferLockResolution,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "source_account_id": (
            row.source_account_id
        ),
        "username": row.username,
        "decision": row.decision,
        "reason": row.reason,
        "prior_request_status": (
            row.prior_request_status
        ),
        "prior_lock_state": (
            row.prior_lock_state
        ),
        "reconciliation_outcome": (
            row.reconciliation_outcome
        ),
        "created_at": (
            row.created_at.isoformat()
            if row.created_at
            else None
        ),
    }


def _lock_snapshot(
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


def list_lock_resolutions(
    request_id: str,
) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(
            select(
                TreasuryTransferLockResolution
            )
            .where(
                TreasuryTransferLockResolution
                .request_id
                == request_id
            )
            .order_by(
                TreasuryTransferLockResolution
                .created_at.asc(),
                TreasuryTransferLockResolution
                .id.asc(),
            )
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]


def manual_release_transfer_lock(
    *,
    request_id: str,
    username: str,
    reason: str,
    live_armed: bool,
) -> dict[str, Any]:
    reason = reason.strip()

    if live_armed:
        raise TreasuryLockResolutionError(
            "Treasury must be disarmed before an "
            "unresolved transfer lock can be "
            "manually released"
        )

    if len(reason) < 20:
        raise TreasuryLockResolutionError(
            "Manual Treasury lock release requires "
            "a reason of at least 20 characters"
        )

    # Everything below is deliberately performed in one
    # transaction. The lock must never disappear without
    # the corresponding resolution audit row committing.
    with session_scope() as db:
        request = db.scalar(
            select(
                TreasuryTransferRequest
            ).where(
                TreasuryTransferRequest.request_id
                == request_id
            )
        )

        if request is None:
            raise TreasuryLockResolutionError(
                "Treasury transfer request not found"
            )

        if request.simulation:
            raise TreasuryLockResolutionError(
                "Simulation records cannot own a "
                "live Treasury transfer lock"
            )

        status = str(
            request.status or ""
        ).lower()

        # PENDING / PARTIAL_SUCCESS / attention must not
        # be manually unlocked. Those outcomes may still
        # represent active or partially executed money
        # movement.
        if status != "uncertain":
            raise TreasuryLockResolutionError(
                "Manual Treasury lock release is only "
                "allowed for an uncertain request"
            )

        lock = db.scalar(
            select(
                TreasuryTransferOperationLock
            ).where(
                TreasuryTransferOperationLock
                .owner_request_id
                == request_id
            )
        )

        if lock is None:
            raise TreasuryLockResolutionError(
                "Treasury transfer lock not found"
            )

        if str(lock.state or "").lower() != "held":
            raise TreasuryLockResolutionError(
                "Only a held Treasury transfer lock "
                "can be manually released"
            )

        latest_reconciliation = db.scalar(
            select(
                TreasuryTransferReconciliation
            )
            .where(
                TreasuryTransferReconciliation
                .request_id
                == request_id
            )
            .order_by(
                TreasuryTransferReconciliation
                .created_at.desc(),
                TreasuryTransferReconciliation
                .id.desc(),
            )
            .limit(1)
        )

        if latest_reconciliation is None:
            raise TreasuryLockResolutionError(
                "Reconcile with Gate at least once "
                "before manually releasing the lock"
            )

        reconciliation_outcome = str(
            latest_reconciliation.outcome
            or ""
        ).lower()

        reconciliation_confidence = str(
            latest_reconciliation.confidence
            or ""
        ).lower()

        if (
            reconciliation_confidence
            != "inconclusive"
        ):
            raise TreasuryLockResolutionError(
                "Manual release requires the latest "
                "Gate reconciliation to remain "
                "inconclusive"
            )

        lock_data = _lock_snapshot(lock)

        result = db.execute(
            delete(
                TreasuryTransferOperationLock
            ).where(
                TreasuryTransferOperationLock.id
                == lock.id,
                TreasuryTransferOperationLock
                .owner_request_id
                == request_id,
            )
        )

        if result.rowcount != 1:
            raise TreasuryLockResolutionError(
                "Treasury transfer lock changed before "
                "manual release completed"
            )

        resolution = (
            TreasuryTransferLockResolution(
                request_id=request_id,
                source_account_id=(
                    request.source_account_id
                ),
                username=username,
                decision="released",
                reason=reason,
                prior_request_status=status,
                prior_lock_state=str(
                    lock.state or ""
                ),
                reconciliation_outcome=(
                    reconciliation_outcome
                ),
            )
        )

        db.add(resolution)
        db.flush()

        return {
            "released": True,
            "lock": lock_data,
            "resolution": _snapshot(
                resolution
            ),
        }
