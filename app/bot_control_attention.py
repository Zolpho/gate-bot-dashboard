from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .db import session_scope
from .models import (
    BotControlAttentionReview,
    BotControlLockResolution,
    BotControlOperationLock,
    BotControlReconciliation,
    BotControlRequest,
)


ATTENTION_REQUEST_STATUSES = {
    "uncertain",
    "blocked",
    "rejected",
}

ATTENTION_RECONCILIATION_OUTCOMES = {
    "probable_created",
    "ambiguous",
    "not_found",
    "inconclusive",
    "observed_running",
    "observed_status",
    "stop_in_progress",
}


def _load_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except Exception:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _age_seconds(value: datetime | None) -> int:
    if value is None:
        return 0

    now = datetime.now(timezone.utc)

    if value.tzinfo is None:
        now = now.replace(tzinfo=None)

    return max(
        0,
        int((now - value).total_seconds()),
    )


def attention_reasons(
    *,
    status: str,
    lock_state: str | None,
    reconciliation_outcome: str | None,
) -> list[str]:
    reasons: list[str] = []

    if status in ATTENTION_REQUEST_STATUSES:
        reasons.append(
            f"request_status:{status}"
        )

    if lock_state == "held":
        reasons.append(
            "operation_lock:held"
        )

    if (
        reconciliation_outcome
        in ATTENTION_RECONCILIATION_OUTCOMES
    ):
        reasons.append(
            "reconciliation:"
            f"{reconciliation_outcome}"
        )

    return reasons


def attention_severity(
    *,
    status: str,
    lock_state: str | None,
    reconciliation_outcome: str | None,
) -> str:
    if (
        status == "uncertain"
        or lock_state == "held"
        or reconciliation_outcome
        in {
            "probable_created",
            "ambiguous",
        }
    ):
        return "high"

    if (
        status in {
            "blocked",
            "rejected",
        }
        or reconciliation_outcome
        in ATTENTION_RECONCILIATION_OUTCOMES
    ):
        return "medium"

    return "low"


def recommended_action(
    *,
    action: str,
    status: str,
    lock_state: str | None,
    reconciliation_outcome: str | None,
    has_reconciliation: bool,
    latest_resolution_type: str | None,
    latest_resolution_decision: str | None,
) -> str:
    if (
        latest_resolution_type == "manual"
        and latest_resolution_decision
        == "released"
        and lock_state != "held"
    ):
        return (
            "The lock was manually released. "
            "The original request outcome remains "
            "part of the audit history."
        )

    if status == "uncertain":
        if not has_reconciliation:
            return (
                "Run read-only reconciliation. "
                "Do not retry the original operation."
            )

        if (
            reconciliation_outcome
            == "stop_in_progress"
        ):
            return (
                "Keep the lock held and reconcile "
                "again later. Gate still reports the "
                "Stop operation as in progress."
            )

        if (
            reconciliation_outcome
            == "probable_created"
        ):
            return (
                "Do not retry creation. Review the "
                "candidate Gate strategy and reconcile "
                "again if necessary."
            )

        if reconciliation_outcome in {
            "ambiguous",
            "not_found",
            "inconclusive",
        }:
            return (
                "Keep the lock held while reviewing "
                "the Gate evidence. Manual release "
                "requires an explicit operator decision."
            )

        if (
            reconciliation_outcome
            == "observed_running"
        ):
            return (
                "Gate currently reports the strategy "
                "as running. Review the strategy state "
                "before considering lock release."
            )

        return (
            "Review reconciliation evidence before "
            "taking another Bot Control action."
        )

    if status == "blocked":
        return (
            "Inspect the conflicting request or lock. "
            "Do not bypass duplicate-operation "
            "protection."
        )

    if status == "rejected":
        return (
            "Review the Gate rejection and request "
            "parameters before preparing another "
            "operation."
        )

    if lock_state == "held":
        return (
            "Inspect the request owning this held "
            "operation lock before continuing."
        )

    if reconciliation_outcome:
        return (
            "Review the latest reconciliation evidence "
            "and request details."
        )

    return "Review the Bot Control request."


def _lock_snapshot(
    row: BotControlOperationLock,
) -> dict[str, Any]:
    return {
        "lock_type": row.lock_type,
        "state": row.state,
        "owner_request_id": (
            row.owner_request_id
        ),
        "strategy_id": (
            row.strategy_id or None
        ),
        "strategy_type": (
            row.strategy_type or None
        ),
        "market": row.market or None,
        "acquired_at": _iso(
            row.acquired_at
        ),
        "cooldown_until": _iso(
            row.cooldown_until
        ),
    }


def _reconciliation_snapshot(
    row: BotControlReconciliation,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "outcome": row.outcome,
        "confidence": row.confidence,
        "strategy_id": (
            row.strategy_id or None
        ),
        "gate_status": (
            row.gate_status or None
        ),
        "summary": row.summary,
        "created_at": _iso(
            row.created_at
        ),
    }


def _resolution_snapshot(
    row: BotControlLockResolution,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "resolution_type": (
            row.resolution_type
        ),
        "decision": row.decision,
        "username": row.username,
        "reason": row.reason,
        "created_at": _iso(
            row.created_at
        ),
    }


def build_attention_queue(
    *,
    account_ids: set[str] | None,
    limit: int = 50,
) -> dict[str, Any]:
    limit = max(
        1,
        min(int(limit), 200),
    )

    scan_limit = max(
        200,
        limit * 5,
    )

    with session_scope() as db:
        lock_statement = (
            select(
                BotControlOperationLock
            )
            .order_by(
                BotControlOperationLock
                .acquired_at.desc(),
                BotControlOperationLock
                .id.desc(),
            )
        )

        request_statement = (
            select(
                BotControlRequest
            )
            .order_by(
                BotControlRequest
                .created_at.desc(),
                BotControlRequest
                .id.desc(),
            )
            .limit(scan_limit)
        )

        if account_ids is not None:
            if not account_ids:
                return {
                    "count": 0,
                    "summary": {
                        "high": 0,
                        "medium": 0,
                        "low": 0,
                    },
                    "items": [],
                }

            accounts = sorted(
                account_ids
            )

            lock_statement = (
                lock_statement.where(
                    BotControlOperationLock
                    .account_id.in_(
                        accounts
                    )
                )
            )

            request_statement = (
                request_statement.where(
                    BotControlRequest
                    .account_id.in_(
                        accounts
                    )
                )
            )

        locks = db.scalars(
            lock_statement
        ).all()

        requests = list(
            db.scalars(
                request_statement
            ).all()
        )

        lock_by_request = {
            row.owner_request_id: row
            for row in locks
        }

        existing_request_ids = {
            row.request_id
            for row in requests
        }

        missing_locked_ids = {
            row.owner_request_id
            for row in locks
            if row.owner_request_id
            not in existing_request_ids
        }

        if missing_locked_ids:
            extra_statement = (
                select(
                    BotControlRequest
                )
                .where(
                    BotControlRequest
                    .request_id.in_(
                        sorted(
                            missing_locked_ids
                        )
                    )
                )
            )

            if account_ids is not None:
                extra_statement = (
                    extra_statement.where(
                        BotControlRequest
                        .account_id.in_(
                            sorted(
                                account_ids
                            )
                        )
                    )
                )

            requests.extend(
                db.scalars(
                    extra_statement
                ).all()
            )

        request_ids = {
            row.request_id
            for row in requests
        }

        latest_reconciliation: dict[
            str,
            BotControlReconciliation,
        ] = {}

        latest_resolution: dict[
            str,
            BotControlLockResolution,
        ] = {}

        review_by_request: dict[
            str,
            BotControlAttentionReview,
        ] = {}

        if request_ids:
            reconciliation_rows = (
                db.scalars(
                    select(
                        BotControlReconciliation
                    )
                    .where(
                        BotControlReconciliation
                        .request_id.in_(
                            sorted(
                                request_ids
                            )
                        )
                    )
                    .order_by(
                        BotControlReconciliation
                        .created_at.desc(),
                        BotControlReconciliation
                        .id.desc(),
                    )
                )
                .all()
            )

            for row in reconciliation_rows:
                latest_reconciliation.setdefault(
                    row.request_id,
                    row,
                )

            resolution_rows = (
                db.scalars(
                    select(
                        BotControlLockResolution
                    )
                    .where(
                        BotControlLockResolution
                        .request_id.in_(
                            sorted(
                                request_ids
                            )
                        )
                    )
                    .order_by(
                        BotControlLockResolution
                        .created_at.desc(),
                        BotControlLockResolution
                        .id.desc(),
                    )
                )
                .all()
            )

            for row in resolution_rows:
                latest_resolution.setdefault(
                    row.request_id,
                    row,
                )

            review_rows = db.scalars(
                select(BotControlAttentionReview)
                .where(
                    BotControlAttentionReview
                    .request_id.in_(
                        sorted(request_ids)
                    )
                )
            ).all()

            review_by_request = {
                row.request_id: row
                for row in review_rows
            }

        items: list[
            dict[str, Any]
        ] = []

        for row in requests:
            status = str(
                row.status or ""
            ).lower()

            lock_row = lock_by_request.get(
                row.request_id
            )

            lock_state = (
                str(lock_row.state)
                if lock_row is not None
                else None
            )

            reconciliation_row = (
                latest_reconciliation.get(
                    row.request_id
                )
            )

            reconciliation_outcome = (
                str(
                    reconciliation_row.outcome
                    or ""
                )
                if reconciliation_row
                else None
            )

            resolution_row = (
                latest_resolution.get(
                    row.request_id
                )
            )

            reasons = attention_reasons(
                status=status,
                lock_state=lock_state,
                reconciliation_outcome=(
                    reconciliation_outcome
                ),
            )

            if not reasons:
                continue

            review_row = review_by_request.get(
                row.request_id
            )

            # A held lock always requires attention, regardless of any
            # earlier operator review.
            if review_row is not None and lock_state != "held":
                activity_times = [
                    value
                    for value in (
                        row.updated_at,
                        (
                            reconciliation_row.created_at
                            if reconciliation_row
                            else None
                        ),
                        (
                            resolution_row.created_at
                            if resolution_row
                            else None
                        ),
                    )
                    if value is not None
                ]

                latest_activity = max(
                    activity_times
                ) if activity_times else None

                reviewed_at = review_row.reviewed_at

                if (
                    latest_activity is not None
                    and reviewed_at is not None
                ):
                    # SQLite may return naive datetimes.
                    if (
                        latest_activity.tzinfo is None
                        and reviewed_at.tzinfo is not None
                    ):
                        reviewed_at = (
                            reviewed_at.replace(
                                tzinfo=None
                            )
                        )
                    elif (
                        latest_activity.tzinfo is not None
                        and reviewed_at.tzinfo is None
                    ):
                        latest_activity = (
                            latest_activity.replace(
                                tzinfo=None
                            )
                        )

                    if reviewed_at >= latest_activity:
                        continue

            request_data = _load_json(
                row.request_json
            )

            gate_payload = (
                request_data.get(
                    "gate_payload"
                )
                if isinstance(
                    request_data,
                    dict,
                )
                else {}
            )

            if not isinstance(
                gate_payload,
                dict,
            ):
                gate_payload = {}

            create_params = (
                gate_payload.get(
                    "create_params"
                )
                or {}
            )

            if not isinstance(
                create_params,
                dict,
            ):
                create_params = {}

            strategy_id = str(
                row.strategy_id
                or gate_payload.get(
                    "strategy_id"
                )
                or (
                    reconciliation_row
                    .strategy_id
                    if reconciliation_row
                    else ""
                )
                or ""
            )

            market = str(
                gate_payload.get(
                    "market"
                )
                or (
                    lock_row.market
                    if lock_row
                    else ""
                )
                or ""
            )

            severity = (
                attention_severity(
                    status=status,
                    lock_state=lock_state,
                    reconciliation_outcome=(
                        reconciliation_outcome
                    ),
                )
            )

            resolution_type = (
                resolution_row
                .resolution_type
                if resolution_row
                else None
            )

            resolution_decision = (
                resolution_row.decision
                if resolution_row
                else None
            )

            recommendation = (
                recommended_action(
                    action=row.action,
                    status=status,
                    lock_state=lock_state,
                    reconciliation_outcome=(
                        reconciliation_outcome
                    ),
                    has_reconciliation=(
                        reconciliation_row
                        is not None
                    ),
                    latest_resolution_type=(
                        resolution_type
                    ),
                    latest_resolution_decision=(
                        resolution_decision
                    ),
                )
            )

            items.append({
                "request_id": (
                    row.request_id
                ),
                "account_id": (
                    row.account_id
                ),
                "username": row.username,
                "action": row.action,
                "status": status,
                "severity": severity,
                "reasons": reasons,
                "market": market or None,
                "investment": (
                    create_params.get(
                        "money"
                    )
                ),
                "strategy_id": (
                    strategy_id or None
                ),
                "error": row.error or "",
                "created_at": _iso(
                    row.created_at
                ),
                "completed_at": _iso(
                    row.completed_at
                ),
                "age_seconds": (
                    _age_seconds(
                        row.created_at
                    )
                ),
                "operation_lock": (
                    _lock_snapshot(
                        lock_row
                    )
                    if lock_row
                    else None
                ),
                "latest_reconciliation": (
                    _reconciliation_snapshot(
                        reconciliation_row
                    )
                    if reconciliation_row
                    else None
                ),
                "latest_lock_resolution": (
                    _resolution_snapshot(
                        resolution_row
                    )
                    if resolution_row
                    else None
                ),
                "recommended_action": (
                    recommendation
                ),
                "manual_release_available": (
                    status == "uncertain"
                    and lock_state == "held"
                    and reconciliation_row
                    is not None
                    and reconciliation_outcome
                    != "stop_in_progress"
                ),
                "review_available": (
                    lock_state != "held"
                ),
            })

        severity_rank = {
            "high": 0,
            "medium": 1,
            "low": 2,
        }

        items.sort(
            key=lambda item: (
                severity_rank.get(
                    item["severity"],
                    9,
                ),
                -int(
                    item["age_seconds"]
                ),
            )
        )

        items = items[:limit]

        summary = {
            "high": sum(
                1
                for item in items
                if item["severity"]
                == "high"
            ),
            "medium": sum(
                1
                for item in items
                if item["severity"]
                == "medium"
            ),
            "low": sum(
                1
                for item in items
                if item["severity"]
                == "low"
            ),
        }

        return {
            "count": len(items),
            "summary": summary,
            "items": items,
        }
