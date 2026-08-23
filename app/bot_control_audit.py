from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .db import session_scope, utcnow
from .models import (
    BotControlReconciliation,
    BotControlRequest,
)


class IdempotencyConflict(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def request_fingerprint(value: Any) -> str:
    return hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def _load_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return {}


def _snapshot(
    row: BotControlRequest,
) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "action": row.action,
        "account_id": row.account_id,
        "username": row.username,
        "status": row.status,
        "request_hash": row.request_hash,
        "request": _load_json(row.request_json),
        "response": _load_json(row.response_json),
        "error": row.error,
        "gate_status_code": row.gate_status_code,
        "gate_label": row.gate_label,
        "strategy_id": row.strategy_id,
        "created_at": (
            row.created_at.isoformat()
            if row.created_at
            else None
        ),
        "updated_at": (
            row.updated_at.isoformat()
            if row.updated_at
            else None
        ),
        "completed_at": (
            row.completed_at.isoformat()
            if row.completed_at
            else None
        ),
    }


def _verify_match(
    row: BotControlRequest,
    *,
    account_id: str,
    username: str,
    action: str,
    fingerprint: str,
) -> None:
    if (
        row.account_id != account_id
        or row.username != username
        or row.action != action
        or row.request_hash != fingerprint
    ):
        raise IdempotencyConflict(
            "request_id is already bound to a "
            "different Bot Control operation"
        )


def find_matching_request(
    *,
    request_id: str,
    account_id: str,
    username: str,
    action: str,
    payload: Any,
) -> dict[str, Any] | None:
    fingerprint = request_fingerprint(payload)

    with session_scope() as db:
        row = db.scalar(
            select(BotControlRequest).where(
                BotControlRequest.request_id
                == request_id
            )
        )

        if row is None:
            return None

        _verify_match(
            row,
            account_id=account_id,
            username=username,
            action=action,
            fingerprint=fingerprint,
        )

        return _snapshot(row)


def reserve_request(
    *,
    request_id: str,
    account_id: str,
    username: str,
    action: str,
    payload: Any,
) -> tuple[dict[str, Any], bool]:
    fingerprint = request_fingerprint(payload)
    serialized = canonical_json(payload)

    try:
        with session_scope() as db:
            existing = db.scalar(
                select(BotControlRequest).where(
                    BotControlRequest.request_id
                    == request_id
                )
            )

            if existing is not None:
                _verify_match(
                    existing,
                    account_id=account_id,
                    username=username,
                    action=action,
                    fingerprint=fingerprint,
                )
                return _snapshot(existing), False

            row = BotControlRequest(
                request_id=request_id,
                account_id=account_id,
                username=username,
                action=action,
                status="reserved",
                request_hash=fingerprint,
                request_json=serialized,
            )

            db.add(row)
            db.flush()

            return _snapshot(row), True

    except IntegrityError:
        # Concurrent request may have won the unique-key race.
        with session_scope() as db:
            existing = db.scalar(
                select(BotControlRequest).where(
                    BotControlRequest.request_id
                    == request_id
                )
            )

            if existing is None:
                raise

            _verify_match(
                existing,
                account_id=account_id,
                username=username,
                action=action,
                fingerprint=fingerprint,
            )

            return _snapshot(existing), False


def mark_request(
    request_id: str,
    *,
    status: str,
    response: Any = None,
    error: str = "",
    strategy_id: str = "",
    gate_status_code: int | None = None,
    gate_label: str = "",
    completed: bool = False,
) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(
            select(BotControlRequest).where(
                BotControlRequest.request_id
                == request_id
            )
        )

        if row is None:
            raise RuntimeError(
                f"Unknown Bot Control request {request_id}"
            )

        row.status = status
        row.error = error

        if response is not None:
            row.response_json = canonical_json(
                response
            )

        if strategy_id:
            row.strategy_id = strategy_id

        row.gate_status_code = gate_status_code
        row.gate_label = gate_label

        if completed:
            row.completed_at = utcnow()

        db.flush()

        return _snapshot(row)


def get_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(BotControlRequest).where(
                BotControlRequest.request_id
                == request_id
            )
        )

        if row is None:
            return None

        return _snapshot(row)


def count_requests(
    *,
    account_ids: set[str] | None = None,
) -> int:
    """
    Return the number of visible Bot Control requests.

    This is a local audit-database read only. It performs
    no Gate request and shares the same account filter as
    list_requests().
    """
    if account_ids is not None and not account_ids:
        return 0

    with session_scope() as db:
        statement = (
            select(func.count())
            .select_from(BotControlRequest)
        )

        if account_ids is not None:
            statement = statement.where(
                BotControlRequest.account_id.in_(
                    sorted(account_ids)
                )
            )

        return int(
            db.scalar(statement)
            or 0
        )


def list_requests(
    *,
    limit: int = 50,
    offset: int = 0,
    account_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    limit = max(
        1,
        min(int(limit), 200),
    )

    offset = max(
        0,
        int(offset),
    )

    if account_ids is not None and not account_ids:
        return []

    with session_scope() as db:
        statement = (
            select(BotControlRequest)
            .order_by(
                BotControlRequest.created_at.desc(),
                BotControlRequest.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        if account_ids is not None:
            statement = statement.where(
                BotControlRequest.account_id.in_(
                    sorted(account_ids)
                )
            )

        rows = db.scalars(
            statement
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]



def _reconciliation_snapshot(
    row: BotControlReconciliation,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "account_id": row.account_id,
        "username": row.username,
        "action": row.action,
        "outcome": row.outcome,
        "confidence": row.confidence,
        "strategy_id": (
            row.strategy_id or None
        ),
        "gate_status": (
            row.gate_status or None
        ),
        "summary": row.summary,
        "details": _load_json(
            row.details_json
        ),
        "created_at": (
            row.created_at.isoformat()
            if row.created_at
            else None
        ),
    }


def record_reconciliation(
    *,
    request_id: str,
    account_id: str,
    username: str,
    action: str,
    outcome: str,
    confidence: str,
    strategy_id: str = "",
    gate_status: str = "",
    summary: str = "",
    details: Any = None,
) -> dict[str, Any]:
    with session_scope() as db:
        row = BotControlReconciliation(
            request_id=request_id,
            account_id=account_id,
            username=username,
            action=action,
            outcome=outcome,
            confidence=confidence,
            strategy_id=strategy_id,
            gate_status=gate_status,
            summary=summary,
            details_json=canonical_json(
                details or {}
            ),
        )

        db.add(row)
        db.flush()

        return _reconciliation_snapshot(
            row
        )


def list_reconciliations(
    request_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    limit = max(
        1,
        min(int(limit), 100),
    )

    with session_scope() as db:
        rows = db.scalars(
            select(
                BotControlReconciliation
            )
            .where(
                BotControlReconciliation.request_id
                == request_id
            )
            .order_by(
                BotControlReconciliation.created_at.desc(),
                BotControlReconciliation.id.desc(),
            )
            .limit(limit)
        ).all()

        return [
            _reconciliation_snapshot(row)
            for row in rows
        ]
