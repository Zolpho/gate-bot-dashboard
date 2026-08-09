from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import session_scope, utcnow
from .models import TreasuryTransferRequest
from .treasury_transfer import gate_client_order_id


class TreasuryTransferIdempotencyConflict(RuntimeError):
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
    row: TreasuryTransferRequest,
) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "source_account_id": row.source_account_id,
        "destination_account_id": (
            row.destination_account_id
        ),
        "username": row.username,
        "direction": row.direction,
        "currency": row.currency,
        "amount": format(row.amount, "f"),
        "status": row.status,
        "request_hash": row.request_hash,
        "request": _load_json(row.request_json),
        "response": _load_json(row.response_json),
        "client_order_id": (
            row.client_order_id or None
        ),
        "gate_transfer_id": (
            row.gate_transfer_id or None
        ),
        "gate_status_code": row.gate_status_code,
        "gate_label": row.gate_label,
        "error": row.error,
        "simulation": row.simulation,
        "write_performed": row.write_performed,
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
    row: TreasuryTransferRequest,
    *,
    source_account_id: str,
    username: str,
    fingerprint: str,
) -> None:
    if (
        row.source_account_id != source_account_id
        or row.username != username
        or row.request_hash != fingerprint
    ):
        raise TreasuryTransferIdempotencyConflict(
            "request_id is already bound to a "
            "different Treasury transfer operation"
        )


def record_simulation(
    *,
    request_id: str,
    source_account_id: str,
    destination_account_id: str,
    username: str,
    currency: str,
    amount: Decimal,
    payload: Any,
    response: Any,
) -> tuple[dict[str, Any], bool]:
    fingerprint = request_fingerprint(payload)

    try:
        with session_scope() as db:
            existing = db.scalar(
                select(TreasuryTransferRequest).where(
                    TreasuryTransferRequest.request_id
                    == request_id
                )
            )

            if existing is not None:
                _verify_match(
                    existing,
                    source_account_id=source_account_id,
                    username=username,
                    fingerprint=fingerprint,
                )
                return _snapshot(existing), False

            row = TreasuryTransferRequest(
                request_id=request_id,
                source_account_id=source_account_id,
                destination_account_id=(
                    destination_account_id
                ),
                username=username,
                direction="from",
                currency=currency,
                amount=amount,
                status="simulated",
                request_hash=fingerprint,
                request_json=canonical_json(payload),
                response_json=canonical_json(response),
                client_order_id=gate_client_order_id(
                    request_id
                ),
                simulation=True,
                write_performed=False,
                completed_at=utcnow(),
            )

            db.add(row)
            db.flush()

            return _snapshot(row), True

    except IntegrityError:
        with session_scope() as db:
            existing = db.scalar(
                select(TreasuryTransferRequest).where(
                    TreasuryTransferRequest.request_id
                    == request_id
                )
            )

            if existing is None:
                raise

            _verify_match(
                existing,
                source_account_id=source_account_id,
                username=username,
                fingerprint=fingerprint,
            )

            return _snapshot(existing), False


def get_transfer_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(TreasuryTransferRequest).where(
                TreasuryTransferRequest.request_id
                == request_id
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_transfer_requests(
    *,
    limit: int = 50,
    account_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))

    if account_ids is not None and not account_ids:
        return []

    with session_scope() as db:
        statement = (
            select(TreasuryTransferRequest)
            .order_by(
                TreasuryTransferRequest.created_at.desc(),
                TreasuryTransferRequest.id.desc(),
            )
            .limit(limit)
        )

        if account_ids is not None:
            statement = statement.where(
                TreasuryTransferRequest
                .source_account_id.in_(
                    sorted(account_ids)
                )
            )

        rows = db.scalars(statement).all()

        return [
            _snapshot(row)
            for row in rows
        ]
