from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from .config import Settings
from .db import session_scope, utcnow
from .models import (
    BotControlLockResolution,
    BotControlOperationLock,
)


class LockResolutionError(RuntimeError):
    pass


class LockNotFound(LockResolutionError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _load_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return {}


def _iso(value) -> str | None:
    return (
        value.isoformat()
        if value is not None
        else None
    )


def _lock_snapshot(
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
        "market": row.market or None,
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


def _resolution_snapshot(
    row: BotControlLockResolution,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "account_id": row.account_id,
        "action": row.action,
        "username": row.username,
        "resolution_type": (
            row.resolution_type
        ),
        "decision": row.decision,
        "reason": row.reason,
        "reconciliation_id": (
            row.reconciliation_id
        ),
        "reconciliation_outcome": (
            row.reconciliation_outcome
        ),
        "reconciliation_confidence": (
            row.reconciliation_confidence
        ),
        "lock_key": row.lock_key,
        "prior_state": row.prior_state,
        "prior_lock": _load_json(
            row.prior_lock_json
        ),
        "resulting_lock": _load_json(
            row.resulting_lock_json
        ),
        "created_at": _iso(
            row.created_at
        ),
    }


def decide_reconciliation_lock_action(
    *,
    action: str,
    outcome: str,
) -> str:
    if (
        action == "spot_grid_create"
        and outcome == "confirmed_created"
    ):
        return "cooldown"

    if (
        action == "bot_stop"
        and outcome == "confirmed_stopped"
    ):
        return "cooldown"

    if outcome in {
        "already_rejected",
        "not_applicable",
    }:
        return "release"

    return "keep"


def _cooldown_seconds(
    *,
    action: str,
    settings: Settings,
) -> int:
    if action == "spot_grid_create":
        return max(
            0,
            int(
                settings
                .bot_create_duplicate_cooldown_seconds
            ),
        )

    if action == "bot_stop":
        return max(
            0,
            int(
                settings
                .bot_stop_duplicate_cooldown_seconds
            ),
        )

    return 0


def apply_reconciliation_lock_policy(
    *,
    request_record: dict[str, Any],
    reconciliation: dict[str, Any],
    username: str,
    settings: Settings,
) -> dict[str, Any]:
    request_id = str(
        request_record["request_id"]
    )

    action = str(
        request_record["action"]
    )

    outcome = str(
        reconciliation.get("outcome")
        or ""
    )

    confidence = str(
        reconciliation.get("confidence")
        or ""
    )

    reconciliation_id = (
        reconciliation.get("id")
    )

    decision = (
        decide_reconciliation_lock_action(
            action=action,
            outcome=outcome,
        )
    )

    with session_scope() as db:
        lock = db.scalar(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.owner_request_id
                == request_id
            )
        )

        if lock is None:
            return {
                "decision": "no_lock",
                "operation_lock": None,
                "resolution": None,
            }

        prior = _lock_snapshot(
            lock
        )

        reason = ""

        if decision == "release":
            reason = (
                "Reconciliation produced terminal "
                f"outcome '{outcome}'."
            )

            db.delete(lock)

            resulting = None

        elif decision == "cooldown":
            seconds = _cooldown_seconds(
                action=action,
                settings=settings,
            )

            if seconds <= 0:
                reason = (
                    "Reconciliation confirmed the "
                    "operation and cooldown is disabled."
                )

                db.delete(lock)
                decision = "release"
                resulting = None

            else:
                reason = (
                    "Reconciliation confirmed the "
                    f"operation. Lock moved to a "
                    f"{seconds}-second cooldown."
                )

                lock.state = "cooldown"
                lock.cooldown_until = (
                    utcnow()
                    + timedelta(
                        seconds=seconds
                    )
                )

                db.flush()

                resulting = _lock_snapshot(
                    lock
                )

        else:
            reason = (
                "Reconciliation did not prove a "
                "terminal outcome. Lock remains held."
            )

            resulting = prior

        audit = BotControlLockResolution(
            request_id=request_id,
            account_id=str(
                request_record["account_id"]
            ),
            action=action,
            username=username,
            resolution_type="automatic",
            decision=decision,
            reason=reason,
            reconciliation_id=(
                int(reconciliation_id)
                if reconciliation_id
                is not None
                else None
            ),
            reconciliation_outcome=outcome,
            reconciliation_confidence=confidence,
            lock_key=prior["lock_key"],
            prior_state=str(
                prior["state"]
            ),
            prior_lock_json=_canonical_json(
                prior
            ),
            resulting_lock_json=_canonical_json(
                resulting or {}
            ),
        )

        db.add(audit)
        db.flush()

        return {
            "decision": decision,
            "operation_lock": resulting,
            "resolution": (
                _resolution_snapshot(
                    audit
                )
            ),
        }


def manual_release_operation_lock(
    *,
    request_record: dict[str, Any],
    reconciliation: dict[str, Any],
    username: str,
    reason: str,
) -> dict[str, Any]:
    request_id = str(
        request_record["request_id"]
    )

    reason = reason.strip()

    if len(reason) < 10:
        raise LockResolutionError(
            "Manual release reason is too short"
        )

    with session_scope() as db:
        lock = db.scalar(
            select(
                BotControlOperationLock
            ).where(
                BotControlOperationLock.owner_request_id
                == request_id
            )
        )

        if lock is None:
            raise LockNotFound(
                "No operation lock exists for "
                f"request {request_id}"
            )

        prior = _lock_snapshot(
            lock
        )

        db.delete(lock)

        audit = BotControlLockResolution(
            request_id=request_id,
            account_id=str(
                request_record["account_id"]
            ),
            action=str(
                request_record["action"]
            ),
            username=username,
            resolution_type="manual",
            decision="released",
            reason=reason,
            reconciliation_id=(
                reconciliation.get("id")
            ),
            reconciliation_outcome=str(
                reconciliation.get("outcome")
                or ""
            ),
            reconciliation_confidence=str(
                reconciliation.get("confidence")
                or ""
            ),
            lock_key=prior["lock_key"],
            prior_state=str(
                prior["state"]
            ),
            prior_lock_json=_canonical_json(
                prior
            ),
            resulting_lock_json="{}",
        )

        db.add(audit)
        db.flush()

        return {
            "decision": "released",
            "operation_lock": None,
            "resolution": (
                _resolution_snapshot(
                    audit
                )
            ),
        }


def list_lock_resolutions(
    request_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(
        1,
        min(int(limit), 100),
    )

    with session_scope() as db:
        rows = db.scalars(
            select(
                BotControlLockResolution
            )
            .where(
                BotControlLockResolution.request_id
                == request_id
            )
            .order_by(
                BotControlLockResolution.created_at.desc(),
                BotControlLockResolution.id.desc(),
            )
            .limit(limit)
        ).all()

        return [
            _resolution_snapshot(row)
            for row in rows
        ]
