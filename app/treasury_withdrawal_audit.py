from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import session_scope, utcnow
from .models import (
    TreasuryWithdrawalReconciliation,
    TreasuryWithdrawalRequest,
)


class TreasuryWithdrawalIdempotencyConflict(
    RuntimeError
):
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
    row: TreasuryWithdrawalRequest,
) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "owner_account_id": row.owner_account_id,
        "custody_account_id": (
            row.custody_account_id
        ),
        "username": row.username,
        "destination_id": row.destination_id,
        "currency": row.currency,
        "chain": row.chain,
        "address": row.address,
        "memo": row.memo,
        "amount": format(row.amount, "f"),
        "estimated_fee": format(
            row.estimated_fee,
            "f",
        ),
        "conservative_funding_required": format(
            row.conservative_funding_required,
            "f",
        ),
        "minimum_jit_transfer": format(
            row.minimum_jit_transfer,
            "f",
        ),
        "jit_required": row.jit_required,
        "status": row.status,
        "request_hash": row.request_hash,
        "request": _load_json(
            row.request_json
        ),
        "preflight": _load_json(
            row.preflight_json
        ),
        "destination_snapshot": _load_json(
            row.destination_snapshot_json
        ),
        "gate_withdraw_order_id": (
            row.gate_withdraw_order_id or None
        ),
        "gate_withdrawal_id": (
            row.gate_withdrawal_id or None
        ),
        "gate_txid": (
            row.gate_txid or None
        ),
        "gate_status": row.gate_status,
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
    row: TreasuryWithdrawalRequest,
    *,
    owner_account_id: str,
    username: str,
    fingerprint: str,
) -> None:
    if (
        row.owner_account_id != owner_account_id
        or row.username != username
        or row.request_hash != fingerprint
    ):
        raise TreasuryWithdrawalIdempotencyConflict(
            "request_id is already bound to a "
            "different Treasury withdrawal operation"
        )


def find_matching_withdrawal_request(
    *,
    request_id: str,
    owner_account_id: str,
    username: str,
    payload: Any,
) -> dict[str, Any] | None:
    fingerprint = request_fingerprint(payload)

    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalRequest
            ).where(
                TreasuryWithdrawalRequest.request_id
                == request_id
            )
        )

        if row is None:
            return None

        _verify_match(
            row,
            owner_account_id=owner_account_id,
            username=username,
            fingerprint=fingerprint,
        )

        return _snapshot(row)


def record_withdrawal_simulation(
    *,
    request_id: str,
    owner_account_id: str,
    custody_account_id: str,
    username: str,
    destination_id: str,
    currency: str,
    chain: str,
    address: str,
    memo: str,
    amount: Decimal,
    estimated_fee: Decimal,
    conservative_funding_required: Decimal,
    minimum_jit_transfer: Decimal,
    jit_required: bool,
    payload: Any,
    preflight: Any,
    destination_snapshot: Any,
) -> tuple[dict[str, Any], bool]:
    fingerprint = request_fingerprint(
        payload
    )

    try:
        with session_scope() as db:
            existing = db.scalar(
                select(
                    TreasuryWithdrawalRequest
                ).where(
                    TreasuryWithdrawalRequest
                    .request_id
                    == request_id
                )
            )

            if existing is not None:
                _verify_match(
                    existing,
                    owner_account_id=(
                        owner_account_id
                    ),
                    username=username,
                    fingerprint=fingerprint,
                )

                return (
                    _snapshot(existing),
                    False,
                )

            row = TreasuryWithdrawalRequest(
                request_id=request_id,
                owner_account_id=(
                    owner_account_id
                ),
                custody_account_id=(
                    custody_account_id
                ),
                username=username,
                destination_id=destination_id,
                currency=currency,
                chain=chain,
                address=address,
                memo=memo,
                amount=amount,
                estimated_fee=estimated_fee,
                conservative_funding_required=(
                    conservative_funding_required
                ),
                minimum_jit_transfer=(
                    minimum_jit_transfer
                ),
                jit_required=jit_required,
                status="simulated",
                request_hash=fingerprint,
                request_json=canonical_json(
                    payload
                ),
                preflight_json=canonical_json(
                    preflight
                ),
                destination_snapshot_json=(
                    canonical_json(
                        destination_snapshot
                    )
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
                select(
                    TreasuryWithdrawalRequest
                ).where(
                    TreasuryWithdrawalRequest
                    .request_id
                    == request_id
                )
            )

            if existing is None:
                raise

            _verify_match(
                existing,
                owner_account_id=(
                    owner_account_id
                ),
                username=username,
                fingerprint=fingerprint,
            )

            return _snapshot(existing), False


def get_withdrawal_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TreasuryWithdrawalRequest
            ).where(
                TreasuryWithdrawalRequest.request_id
                == request_id
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_withdrawal_requests(
    *,
    limit: int = 50,
    account_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    limit = max(
        1,
        min(int(limit), 200),
    )

    if (
        account_ids is not None
        and not account_ids
    ):
        return []

    with session_scope() as db:
        statement = (
            select(
                TreasuryWithdrawalRequest
            )
            .order_by(
                TreasuryWithdrawalRequest
                .created_at.desc(),
                TreasuryWithdrawalRequest
                .id.desc(),
            )
            .limit(limit)
        )

        if account_ids is not None:
            statement = statement.where(
                TreasuryWithdrawalRequest
                .owner_account_id
                .in_(sorted(account_ids))
            )

        rows = db.scalars(
            statement
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]


def _reconciliation_snapshot(
    row: TreasuryWithdrawalReconciliation,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "owner_account_id": (
            row.owner_account_id
        ),
        "username": row.username,
        "outcome": row.outcome,
        "confidence": row.confidence,
        "gate_status": (
            row.gate_status or None
        ),
        "gate_withdrawal_id": (
            row.gate_withdrawal_id or None
        ),
        "gate_txid": (
            row.gate_txid or None
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


def record_withdrawal_reconciliation(
    *,
    request_id: str,
    owner_account_id: str,
    username: str,
    outcome: str,
    confidence: str,
    gate_status: str = "",
    gate_withdrawal_id: str = "",
    gate_txid: str = "",
    summary: str = "",
    details: Any = None,
) -> dict[str, Any]:
    with session_scope() as db:
        row = TreasuryWithdrawalReconciliation(
            request_id=request_id,
            owner_account_id=(
                owner_account_id
            ),
            username=username,
            outcome=outcome,
            confidence=confidence,
            gate_status=gate_status,
            gate_withdrawal_id=(
                gate_withdrawal_id
            ),
            gate_txid=gate_txid,
            summary=summary,
            details_json=canonical_json(
                details or {}
            ),
        )

        db.add(row)
        db.flush()

        return _reconciliation_snapshot(row)


def list_withdrawal_reconciliations(
    request_id: str,
) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(
            select(
                TreasuryWithdrawalReconciliation
            )
            .where(
                TreasuryWithdrawalReconciliation
                .request_id
                == request_id
            )
            .order_by(
                TreasuryWithdrawalReconciliation
                .created_at.asc(),
                TreasuryWithdrawalReconciliation
                .id.asc(),
            )
        ).all()

        return [
            _reconciliation_snapshot(row)
            for row in rows
        ]
