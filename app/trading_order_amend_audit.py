from __future__ import annotations

import hashlib
import json
from decimal import (
    Decimal,
    InvalidOperation,
)
from typing import Any

from sqlalchemy import (
    select,
)
from sqlalchemy.exc import (
    IntegrityError,
)

from .db import (
    session_scope,
    utcnow,
)
from .models import (
    TradingOrderAmendment,
)


class TradingOrderAmendConflict(
    RuntimeError
):
    pass


def _canonical_json(
    value: Any,
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _fingerprint(
    value: Any,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            value
        ).encode("utf-8")
    ).hexdigest()


def _load_json(
    value: str,
) -> Any:
    try:
        return json.loads(
            value or "{}"
        )
    except (
        TypeError,
        ValueError,
    ):
        return {}


def _decimal(
    value: Any,
) -> Decimal:
    try:
        result = Decimal(
            str(value)
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid amendment price"
        ) from exc

    if (
        not result.is_finite()
        or result <= 0
    ):
        raise ValueError(
            "Amendment price must be positive"
        )

    return result


def _decimal_text(
    value: Any,
) -> str:
    return format(
        _decimal(value).normalize(),
        "f",
    )


def _snapshot(
    row: TradingOrderAmendment,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "amend_request_id": (
            row.amend_request_id
        ),
        "order_request_id": (
            row.order_request_id
        ),
        "account_id": row.account_id,
        "username": row.username,
        "pair": row.pair,
        "gate_order_id": (
            row.gate_order_id
        ),
        "current_price": (
            _decimal_text(
                row.current_price
            )
        ),
        "requested_price": (
            _decimal_text(
                row.requested_price
            )
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
        "gate_status_code": (
            row.gate_status_code
        ),
        "gate_label": (
            row.gate_label
            or None
        ),
        "error": (
            row.error
            or None
        ),
        "write_performed": (
            bool(
                row.write_performed
            )
        ),
        "active": (
            row.active_order_key
            is not None
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


def _intent(
    *,
    order_request_id: str,
    account_id: str,
    username: str,
    pair: str,
    gate_order_id: str,
    current_price: Any,
    requested_price: Any,
) -> dict[str, str]:
    normalized = {
        "order_request_id": (
            order_request_id.strip()
        ),
        "account_id": (
            account_id
            .strip()
            .lower()
        ),
        "username": (
            username.strip()
        ),
        "pair": (
            pair
            .strip()
            .upper()
        ),
        "gate_order_id": (
            gate_order_id.strip()
        ),
        "current_price": (
            _decimal_text(
                current_price
            )
        ),
        "requested_price": (
            _decimal_text(
                requested_price
            )
        ),
    }

    for key in (
        "order_request_id",
        "account_id",
        "username",
        "pair",
        "gate_order_id",
    ):
        if not normalized[key]:
            raise ValueError(
                f"{key} cannot be empty"
            )

    if not normalized[
        "gate_order_id"
    ].isdigit():
        raise ValueError(
            "Amendment requires the real "
            "numeric Gate order ID"
        )

    if "_" not in normalized["pair"]:
        raise ValueError(
            "pair must be a Gate Spot pair"
        )

    if (
        normalized["current_price"]
        == normalized["requested_price"]
    ):
        raise ValueError(
            "Requested amendment price "
            "must differ from current price"
        )

    return normalized


def _verify_match(
    row: TradingOrderAmendment,
    *,
    intent: dict[str, str],
    fingerprint: str,
) -> None:
    if (
        row.order_request_id
        != intent["order_request_id"]
        or row.account_id
        != intent["account_id"]
        or row.username
        != intent["username"]
        or row.pair
        != intent["pair"]
        or row.gate_order_id
        != intent["gate_order_id"]
        or _decimal_text(
            row.current_price
        ) != intent["current_price"]
        or _decimal_text(
            row.requested_price
        ) != intent["requested_price"]
        or row.request_hash
        != fingerprint
    ):
        raise TradingOrderAmendConflict(
            "Amendment request identity is "
            "already bound to different intent"
        )


def reserve_order_amendment(
    *,
    amend_request_id: str,
    order_request_id: str,
    account_id: str,
    username: str,
    pair: str,
    gate_order_id: str,
    current_price: Any,
    requested_price: Any,
) -> tuple[
    dict[str, Any],
    bool,
]:
    normalized_amend_id = (
        amend_request_id.strip()
    )

    if not normalized_amend_id:
        raise ValueError(
            "amend_request_id cannot be empty"
        )

    intent = _intent(
        order_request_id=(
            order_request_id
        ),
        account_id=account_id,
        username=username,
        pair=pair,
        gate_order_id=gate_order_id,
        current_price=current_price,
        requested_price=(
            requested_price
        ),
    )

    fingerprint = _fingerprint(
        intent
    )

    try:
        with session_scope() as db:
            by_id = db.scalar(
                select(
                    TradingOrderAmendment
                ).where(
                    TradingOrderAmendment
                    .amend_request_id
                    == normalized_amend_id
                )
            )

            if by_id is not None:
                _verify_match(
                    by_id,
                    intent=intent,
                    fingerprint=fingerprint,
                )

                return (
                    _snapshot(by_id),
                    False,
                )

            active = db.scalar(
                select(
                    TradingOrderAmendment
                ).where(
                    TradingOrderAmendment
                    .active_order_key
                    == intent[
                        "order_request_id"
                    ]
                )
            )

            if active is not None:
                raise TradingOrderAmendConflict(
                    "Another unresolved amendment "
                    "already exists for this Spot order"
                )

            row = TradingOrderAmendment(
                amend_request_id=(
                    normalized_amend_id
                ),
                order_request_id=(
                    intent[
                        "order_request_id"
                    ]
                ),
                active_order_key=(
                    intent[
                        "order_request_id"
                    ]
                ),
                account_id=(
                    intent["account_id"]
                ),
                username=(
                    intent["username"]
                ),
                pair=intent["pair"],
                gate_order_id=(
                    intent[
                        "gate_order_id"
                    ]
                ),
                current_price=Decimal(
                    intent[
                        "current_price"
                    ]
                ),
                requested_price=Decimal(
                    intent[
                        "requested_price"
                    ]
                ),
                status="reserved",
                request_hash=(
                    fingerprint
                ),
                request_json=(
                    _canonical_json(
                        intent
                    )
                ),
                response_json="{}",
                write_performed=False,
            )

            db.add(row)
            db.flush()

            return (
                _snapshot(row),
                True,
            )

    except IntegrityError:
        # Handles the race where two workers both
        # observed no active amendment before insert.
        with session_scope() as db:
            by_id = db.scalar(
                select(
                    TradingOrderAmendment
                ).where(
                    TradingOrderAmendment
                    .amend_request_id
                    == normalized_amend_id
                )
            )

            if by_id is not None:
                _verify_match(
                    by_id,
                    intent=intent,
                    fingerprint=fingerprint,
                )

                return (
                    _snapshot(by_id),
                    False,
                )

            active = db.scalar(
                select(
                    TradingOrderAmendment
                ).where(
                    TradingOrderAmendment
                    .active_order_key
                    == intent[
                        "order_request_id"
                    ]
                )
            )

            if active is not None:
                raise TradingOrderAmendConflict(
                    "Another unresolved amendment "
                    "already exists for this Spot order"
                )

            raise


def get_order_amendment(
    amend_request_id: str,
) -> dict[str, Any] | None:
    normalized = (
        amend_request_id.strip()
    )

    if not normalized:
        return None

    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderAmendment
            ).where(
                TradingOrderAmendment
                .amend_request_id
                == normalized
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def get_active_order_amendment(
    order_request_id: str,
) -> dict[str, Any] | None:
    normalized = (
        order_request_id.strip()
    )

    if not normalized:
        return None

    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderAmendment
            ).where(
                TradingOrderAmendment
                .active_order_key
                == normalized
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def get_latest_order_amendment(
    order_request_id: str,
) -> dict[str, Any] | None:
    normalized = (
        order_request_id.strip()
    )

    if not normalized:
        return None

    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderAmendment
            ).where(
                TradingOrderAmendment
                .order_request_id
                == normalized
            )
            .order_by(
                TradingOrderAmendment
                .created_at.desc(),
                TradingOrderAmendment
                .id.desc(),
            )
            .limit(1)
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def list_order_amendments(
    order_request_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    normalized = (
        order_request_id.strip()
    )

    if not normalized:
        return []

    bounded_limit = max(
        1,
        min(
            int(limit),
            200,
        ),
    )

    with session_scope() as db:
        rows = db.scalars(
            select(
                TradingOrderAmendment
            ).where(
                TradingOrderAmendment
                .order_request_id
                == normalized
            )
            .order_by(
                TradingOrderAmendment
                .created_at.desc(),
                TradingOrderAmendment
                .id.desc(),
            )
            .limit(
                bounded_limit
            )
        ).all()

        return [
            _snapshot(row)
            for row in rows
        ]


def list_order_amendments_for_requests(
    order_request_ids: (
        list[str]
        | set[str]
        | tuple[str, ...]
    ),
) -> dict[
    str,
    list[dict[str, Any]],
]:
    """
    Bulk read amendment history for dashboard
    order-list rendering.

    This helper is read-only and performs one
    local database SELECT regardless of the
    number of requested order IDs.

    Each history is newest-first, matching
    get_latest_order_amendment().
    """
    normalized = sorted(
        {
            str(value or "").strip()
            for value in order_request_ids
            if str(value or "").strip()
        }
    )

    if not normalized:
        return {}

    result: dict[
        str,
        list[dict[str, Any]],
    ] = {
        request_id: []
        for request_id in normalized
    }

    with session_scope() as db:
        rows = db.scalars(
            select(
                TradingOrderAmendment
            )
            .where(
                TradingOrderAmendment
                .order_request_id.in_(
                    normalized
                )
            )
            .order_by(
                TradingOrderAmendment
                .order_request_id.asc(),
                TradingOrderAmendment
                .created_at.desc(),
                TradingOrderAmendment
                .id.desc(),
            )
        ).all()

        for row in rows:
            request_id = str(
                row.order_request_id
                or ""
            ).strip()

            if request_id in result:
                result[
                    request_id
                ].append(
                    _snapshot(row)
                )

    return result


def mark_order_amendment(
    amend_request_id: str,
    *,
    status: str,
    response: Any = None,
    error: str = "",
    gate_status_code: int
    | None = None,
    gate_label: str = "",
    write_performed: bool
    | None = None,
    completed: bool = False,
) -> dict[str, Any]:
    normalized = (
        amend_request_id.strip()
    )

    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderAmendment
            ).where(
                TradingOrderAmendment
                .amend_request_id
                == normalized
            )
        )

        if row is None:
            raise RuntimeError(
                "Unknown Trading amendment "
                f"{amend_request_id}"
            )

        row.status = status
        row.error = error
        row.gate_status_code = (
            gate_status_code
        )
        row.gate_label = (
            gate_label
        )

        if response is not None:
            row.response_json = (
                _canonical_json(
                    response
                )
            )

        if (
            write_performed
            is not None
        ):
            row.write_performed = (
                write_performed
            )

        if completed:
            if row.completed_at is None:
                row.completed_at = (
                    utcnow()
                )

            # Release the database-level
            # unresolved-amendment lock only after
            # the outcome is definitive.
            row.active_order_key = None

        db.flush()

        return _snapshot(row)
