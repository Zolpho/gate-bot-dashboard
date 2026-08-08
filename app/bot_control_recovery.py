from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .db import (
    session_scope,
    utcnow,
)
from .models import (
    BotControlOperationLock,
    BotControlRequest,
)


RECOVERABLE_STATUSES = {
    "reserved",
    "submitting",
}


def _lock_snapshot(
    row: BotControlOperationLock | None,
) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "lock_key": row.lock_key,
        "lock_type": row.lock_type,
        "state": row.state,
        "owner_request_id": (
            row.owner_request_id
        ),
        "account_id": row.account_id,
        "action": row.action,
        "strategy_id": (
            row.strategy_id or None
        ),
        "strategy_type": (
            row.strategy_type or None
        ),
        "market": row.market or None,
    }


def recovery_message(
    *,
    previous_status: str,
    lock_state: str | None,
) -> str:
    lock_text = (
        f" Operation lock remains {lock_state}."
        if lock_state
        else " No operation lock was found."
    )

    return (
        "Startup recovery detected a Bot Control "
        f"request left in '{previous_status}' by a "
        "previous application process. The operation "
        "outcome cannot be assumed. Automatic retry "
        "was NOT performed and automatic lock release "
        "was NOT performed."
        f"{lock_text} Read-only reconciliation is "
        "required before any retry or manual lock "
        "decision."
    )


def recover_stale_bot_control_requests(
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    if not enabled:
        return {
            "enabled": False,
            "scanned": 0,
            "recovered": 0,
            "items": [],
        }

    recovered: list[
        dict[str, Any]
    ] = []

    with session_scope() as db:
        rows = list(
            db.scalars(
                select(
                    BotControlRequest
                )
                .where(
                    BotControlRequest.status.in_(
                        sorted(
                            RECOVERABLE_STATUSES
                        )
                    )
                )
                .order_by(
                    BotControlRequest
                    .created_at.asc(),
                    BotControlRequest
                    .id.asc(),
                )
            ).all()
        )

        scanned = len(rows)

        for row in rows:
            previous_status = str(
                row.status
            )

            lock_row = db.scalar(
                select(
                    BotControlOperationLock
                ).where(
                    BotControlOperationLock
                    .owner_request_id
                    == row.request_id
                )
            )

            lock = _lock_snapshot(
                lock_row
            )

            lock_state = (
                str(lock["state"])
                if lock
                else None
            )

            message = recovery_message(
                previous_status=(
                    previous_status
                ),
                lock_state=lock_state,
            )

            existing_error = (
                str(row.error or "").strip()
            )

            if existing_error:
                message = (
                    existing_error
                    + "\n\n"
                    + message
                )

            # Critical policy:
            #
            # - mark request uncertain
            # - preserve request/response evidence
            # - preserve strategy_id
            # - preserve Gate status fields
            # - KEEP any operation lock untouched
            # - NEVER call Gate here
            row.status = "uncertain"
            row.error = message

            if row.completed_at is None:
                row.completed_at = utcnow()

            recovered.append({
                "request_id": (
                    row.request_id
                ),
                "account_id": (
                    row.account_id
                ),
                "username": row.username,
                "action": row.action,
                "previous_status": (
                    previous_status
                ),
                "new_status": "uncertain",
                "operation_lock": lock,
                "lock_preserved": (
                    lock is not None
                ),
                "automatic_retry": False,
                "automatic_lock_release": False,
            })

        db.flush()

    return {
        "enabled": True,
        "scanned": scanned,
        "recovered": len(
            recovered
        ),
        "items": recovered,
    }
