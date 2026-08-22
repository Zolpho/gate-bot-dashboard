from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import session_scope, utcnow
from .models import (
    TradingOrderReconciliation,
    TradingOrderRequest,
)
from .trading_order_identity import (
    gate_text_for_request_id,
)


class TradingOrderIdempotencyConflict(
    RuntimeError
):
    pass


def canonical_json(
    value: Any,
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def request_fingerprint(
    value: Any,
) -> str:
    return hashlib.sha256(
        canonical_json(value).encode(
            "utf-8"
        )
    ).hexdigest()


def _load_json(
    value: str,
) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return {}


def _decimal_text(
    value: Decimal,
) -> str:
    return format(
        value,
        "f",
    )


def limit_order_intent(
    *,
    account_id: str,
    pair: str,
    side: str,
    price: Decimal,
    amount: Decimal,
    time_in_force: str,
    funding_asset: str,
) -> dict[str, str]:
    normalized_side = (
        side.strip().lower()
    )

    normalized_tif = (
        time_in_force.strip().lower()
    )

    if normalized_side not in {
        "buy",
        "sell",
    }:
        raise ValueError(
            "side must be buy or sell"
        )

    if normalized_tif not in {
        "gtc",
        "poc",
    }:
        raise ValueError(
            "time_in_force must be "
            "gtc or poc"
        )

    if price <= 0:
        raise ValueError(
            "price must be positive"
        )

    if amount <= 0:
        raise ValueError(
            "amount must be positive"
        )

    normalized_asset = (
        funding_asset.strip().upper()
    )

    if not normalized_asset:
        raise ValueError(
            "funding_asset cannot be empty"
        )

    return {
        "account_id": (
            account_id.strip().lower()
        ),
        "pair": pair.strip().upper(),
        "side": normalized_side,
        "order_type": "limit",
        "time_in_force": normalized_tif,
        "price": _decimal_text(price),
        "amount": _decimal_text(amount),
        "funding_asset": normalized_asset,
    }


def _snapshot(
    row: TradingOrderRequest,
) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "account_id": row.account_id,
        "username": row.username,
        "pair": row.pair,
        "side": row.side,
        "order_type": row.order_type,
        "time_in_force": (
            row.time_in_force
        ),
        "price": _decimal_text(
            row.price
        ),
        "amount": _decimal_text(
            row.amount
        ),
        "total": _decimal_text(
            row.total
        ),
        "funding_asset": (
            row.funding_asset
        ),
        "status": row.status,
        "request_hash": (
            row.request_hash
        ),
        "request": _load_json(
            row.request_json
        ),
        "response": _load_json(
            row.response_json
        ),
        "gate_text": (
            row.gate_text or None
        ),
        "gate_order_id": (
            row.gate_order_id or None
        ),
        "gate_status_code": (
            row.gate_status_code
        ),
        "gate_label": (
            row.gate_label or None
        ),
        "error": row.error,
        "write_performed": (
            row.write_performed
        ),
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
    row: TradingOrderRequest,
    *,
    account_id: str,
    username: str,
    fingerprint: str,
) -> None:
    if (
        row.account_id
        != account_id
        or row.username
        != username
        or row.request_hash
        != fingerprint
    ):
        raise (
            TradingOrderIdempotencyConflict(
                "request_id is already bound "
                "to a different Spot order "
                "operation"
            )
        )


def reserve_limit_order(
    *,
    request_id: str,
    account_id: str,
    username: str,
    pair: str,
    side: str,
    price: Decimal,
    amount: Decimal,
    time_in_force: str,
    funding_asset: str,
) -> tuple[
    dict[str, Any],
    bool,
]:
    normalized_request_id = (
        request_id.strip()
    )

    if not normalized_request_id:
        raise ValueError(
            "request_id cannot be empty"
        )

    intent = limit_order_intent(
        account_id=account_id,
        pair=pair,
        side=side,
        price=price,
        amount=amount,
        time_in_force=(
            time_in_force
        ),
        funding_asset=(
            funding_asset
        ),
    )

    fingerprint = request_fingerprint(
        intent
    )

    normalized_account = intent[
        "account_id"
    ]

    gate_text = (
        gate_text_for_request_id(
            normalized_request_id
        )
    )

    total = price * amount

    try:
        with session_scope() as db:
            existing = db.scalar(
                select(
                    TradingOrderRequest
                ).where(
                    TradingOrderRequest
                    .request_id
                    == normalized_request_id
                )
            )

            if existing is not None:
                _verify_match(
                    existing,
                    account_id=(
                        normalized_account
                    ),
                    username=username,
                    fingerprint=(
                        fingerprint
                    ),
                )

                return (
                    _snapshot(existing),
                    False,
                )

            row = TradingOrderRequest(
                request_id=(
                    normalized_request_id
                ),
                account_id=(
                    normalized_account
                ),
                username=username,
                pair=intent["pair"],
                side=intent["side"],
                order_type="limit",
                time_in_force=(
                    intent[
                        "time_in_force"
                    ]
                ),
                price=price,
                amount=amount,
                total=total,
                funding_asset=(
                    intent[
                        "funding_asset"
                    ]
                ),
                status="reserved",
                request_hash=(
                    fingerprint
                ),
                request_json=(
                    canonical_json(
                        intent
                    )
                ),
                response_json="{}",
                gate_text=gate_text,
                gate_order_id="",
                write_performed=False,
            )

            db.add(row)
            db.flush()

            return (
                _snapshot(row),
                True,
            )

    except IntegrityError:
        with session_scope() as db:
            existing = db.scalar(
                select(
                    TradingOrderRequest
                ).where(
                    TradingOrderRequest
                    .request_id
                    == normalized_request_id
                )
            )

            if existing is None:
                raise

            _verify_match(
                existing,
                account_id=(
                    normalized_account
                ),
                username=username,
                fingerprint=(
                    fingerprint
                ),
            )

            return (
                _snapshot(existing),
                False,
            )


def get_order_request(
    request_id: str,
) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderRequest
            ).where(
                TradingOrderRequest
                .request_id
                == request_id.strip()
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_order_requests(
    *,
    limit: int = 50,
    account_ids: set[str]
    | None = None,
) -> list[dict[str, Any]]:
    normalized_limit = max(
        1,
        min(
            int(limit),
            200,
        ),
    )

    if (
        account_ids is not None
        and not account_ids
    ):
        return []

    with session_scope() as db:
        statement = (
            select(
                TradingOrderRequest
            )
            .order_by(
                TradingOrderRequest
                .created_at.desc(),
                TradingOrderRequest
                .id.desc(),
            )
            .limit(
                normalized_limit
            )
        )

        if account_ids is not None:
            statement = (
                statement.where(
                    TradingOrderRequest
                    .account_id.in_(
                        sorted(
                            account_ids
                        )
                    )
                )
            )

        rows = db.scalars(
            statement
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]



def find_order_requests_by_gate_identity(
    *,
    account_id: str,
    gate_order_ids: set[str] | None = None,
    gate_texts: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Return local Spot order audits matching Gate identities.

    This is intentionally identity-based rather than
    "most recent N requests" so a long-lived open order
    cannot fall out of the dashboard join merely because
    newer trading requests were created later.
    """

    normalized_account = (
        account_id.strip().lower()
    )

    if not normalized_account:
        raise ValueError(
            "account_id cannot be empty"
        )

    normalized_ids = {
        str(value).strip()
        for value in (
            gate_order_ids or set()
        )
        if str(value).strip()
    }

    normalized_texts = {
        str(value).strip()
        for value in (
            gate_texts or set()
        )
        if str(value).strip()
    }

    if (
        not normalized_ids
        and not normalized_texts
    ):
        return []

    identity_filter = None

    if normalized_ids:
        identity_filter = (
            TradingOrderRequest
            .gate_order_id.in_(
                sorted(normalized_ids)
            )
        )

    if normalized_texts:
        text_filter = (
            TradingOrderRequest
            .gate_text.in_(
                sorted(normalized_texts)
            )
        )

        identity_filter = (
            text_filter
            if identity_filter is None
            else (
                identity_filter
                | text_filter
            )
        )

    with session_scope() as db:
        statement = (
            select(
                TradingOrderRequest
            )
            .where(
                TradingOrderRequest
                .account_id
                == normalized_account
            )
            .where(
                identity_filter
            )
            .order_by(
                TradingOrderRequest
                .created_at.desc(),
                TradingOrderRequest
                .id.desc(),
            )
        )

        rows = db.scalars(
            statement
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]

def mark_order_request(
    request_id: str,
    *,
    status: str,
    response: Any = None,
    error: str = "",
    gate_order_id: str = "",
    gate_status_code: int
    | None = None,
    gate_label: str = "",
    write_performed: bool
    | None = None,
    completed: bool = False,
) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderRequest
            ).where(
                TradingOrderRequest
                .request_id
                == request_id.strip()
            )
        )

        if row is None:
            raise RuntimeError(
                "Unknown Trading order request "
                f"{request_id}"
            )

        row.status = status
        row.error = error

        if response is not None:
            row.response_json = (
                canonical_json(
                    response
                )
            )

        if gate_order_id:
            row.gate_order_id = (
                gate_order_id
            )

        row.gate_status_code = (
            gate_status_code
        )

        row.gate_label = (
            gate_label
        )

        if write_performed is not None:
            row.write_performed = (
                write_performed
            )

        if completed:
            row.completed_at = (
                utcnow()
            )

        db.flush()

        return _snapshot(row)


def _reconciliation_snapshot(
    row: TradingOrderReconciliation,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": (
            row.request_id
        ),
        "account_id": (
            row.account_id
        ),
        "username": row.username,
        "pair": row.pair,
        "outcome": row.outcome,
        "confidence": row.confidence,
        "gate_order_id": (
            row.gate_order_id
            or None
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


def record_order_reconciliation(
    *,
    request_id: str,
    account_id: str,
    username: str,
    pair: str,
    outcome: str,
    confidence: str,
    gate_order_id: str = "",
    gate_status: str = "",
    summary: str = "",
    details: Any = None,
) -> dict[str, Any]:
    normalized_request_id = (
        request_id.strip()
    )

    normalized_account = (
        account_id.strip().lower()
    )

    normalized_pair = (
        pair.strip().upper()
    )

    with session_scope() as db:
        request = db.scalar(
            select(
                TradingOrderRequest
            ).where(
                TradingOrderRequest
                .request_id
                == normalized_request_id
            )
        )

        if request is None:
            raise RuntimeError(
                "Cannot reconcile unknown "
                "Trading request "
                f"{normalized_request_id}"
            )

        if (
            request.account_id
            != normalized_account
            or request.username
            != username
            or request.pair
            != normalized_pair
        ):
            raise RuntimeError(
                "Reconciliation metadata "
                "does not match Trading request"
            )

        row = (
            TradingOrderReconciliation(
                request_id=(
                    normalized_request_id
                ),
                account_id=(
                    normalized_account
                ),
                username=username,
                pair=normalized_pair,
                outcome=outcome,
                confidence=confidence,
                gate_order_id=(
                    gate_order_id
                ),
                gate_status=(
                    gate_status
                ),
                summary=summary,
                details_json=(
                    canonical_json(
                        details or {}
                    )
                ),
            )
        )

        db.add(row)
        db.flush()

        return (
            _reconciliation_snapshot(
                row
            )
        )


def list_order_reconciliations(
    request_id: str,
) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(
            select(
                TradingOrderReconciliation
            )
            .where(
                TradingOrderReconciliation
                .request_id
                == request_id.strip()
            )
            .order_by(
                TradingOrderReconciliation
                .created_at.asc(),
                TradingOrderReconciliation
                .id.asc(),
            )
        ).all()

        return [
            _reconciliation_snapshot(
                row
            )
            for row in rows
        ]
