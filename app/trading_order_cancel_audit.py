from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import (
    or_,
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
    TradingOrderCancellation,
)


class TradingOrderCancelConflict(
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


def _snapshot(
    row: TradingOrderCancellation,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "cancel_request_id": (
            row.cancel_request_id
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
        "username": username.strip(),
        "pair": (
            pair
            .strip()
            .upper()
        ),
        "gate_order_id": (
            gate_order_id.strip()
        ),
    }

    for key, value in (
        normalized.items()
    ):
        if not value:
            raise ValueError(
                f"{key} cannot be empty"
            )

    return normalized


def _verify_match(
    row: TradingOrderCancellation,
    *,
    intent: dict[str, str],
    fingerprint: str,
) -> None:
    if (
        row.order_request_id
        != intent[
            "order_request_id"
        ]
        or row.account_id
        != intent["account_id"]
        or row.username
        != intent["username"]
        or row.pair
        != intent["pair"]
        or row.gate_order_id
        != intent[
            "gate_order_id"
        ]
        or row.request_hash
        != fingerprint
    ):
        raise TradingOrderCancelConflict(
            "Cancellation identity is already "
            "bound to a different Spot order"
        )


def reserve_order_cancellation(
    *,
    cancel_request_id: str,
    order_request_id: str,
    account_id: str,
    username: str,
    pair: str,
    gate_order_id: str,
) -> tuple[
    dict[str, Any],
    bool,
]:
    normalized_cancel_id = (
        cancel_request_id.strip()
    )

    if not normalized_cancel_id:
        raise ValueError(
            "cancel_request_id cannot be empty"
        )

    intent = _intent(
        order_request_id=(
            order_request_id
        ),
        account_id=account_id,
        username=username,
        pair=pair,
        gate_order_id=(
            gate_order_id
        ),
    )

    fingerprint = (
        _fingerprint(
            intent
        )
    )

    try:
        with session_scope() as db:
            existing = db.scalar(
                select(
                    TradingOrderCancellation
                ).where(
                    or_(
                        TradingOrderCancellation
                        .cancel_request_id
                        == normalized_cancel_id,

                        TradingOrderCancellation
                        .order_request_id
                        == intent[
                            "order_request_id"
                        ],
                    )
                )
            )

            if existing is not None:
                _verify_match(
                    existing,
                    intent=intent,
                    fingerprint=(
                        fingerprint
                    ),
                )

                return (
                    _snapshot(existing),
                    False,
                )

            row = (
                TradingOrderCancellation(
                    cancel_request_id=(
                        normalized_cancel_id
                    ),
                    order_request_id=(
                        intent[
                            "order_request_id"
                        ]
                    ),
                    account_id=(
                        intent[
                            "account_id"
                        ]
                    ),
                    username=(
                        intent[
                            "username"
                        ]
                    ),
                    pair=(
                        intent["pair"]
                    ),
                    gate_order_id=(
                        intent[
                            "gate_order_id"
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
                    TradingOrderCancellation
                ).where(
                    or_(
                        TradingOrderCancellation
                        .cancel_request_id
                        == normalized_cancel_id,

                        TradingOrderCancellation
                        .order_request_id
                        == intent[
                            "order_request_id"
                        ],
                    )
                )
            )

            if existing is None:
                raise

            _verify_match(
                existing,
                intent=intent,
                fingerprint=(
                    fingerprint
                ),
            )

            return (
                _snapshot(existing),
                False,
            )


def get_order_cancellation(
    *,
    cancel_request_id: str
    | None = None,
    order_request_id: str
    | None = None,
) -> dict[str, Any] | None:
    if bool(cancel_request_id) == bool(
        order_request_id
    ):
        raise ValueError(
            "Specify exactly one cancellation identifier"
        )

    with session_scope() as db:
        if cancel_request_id:
            condition = (
                TradingOrderCancellation
                .cancel_request_id
                == cancel_request_id.strip()
            )
        else:
            condition = (
                TradingOrderCancellation
                .order_request_id
                == str(
                    order_request_id
                ).strip()
            )

        row = db.scalar(
            select(
                TradingOrderCancellation
            ).where(
                condition
            )
        )

        return (
            _snapshot(row)
            if row is not None
            else None
        )


def mark_order_cancellation(
    cancel_request_id: str,
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
    with session_scope() as db:
        row = db.scalar(
            select(
                TradingOrderCancellation
            ).where(
                TradingOrderCancellation
                .cancel_request_id
                == cancel_request_id.strip()
            )
        )

        if row is None:
            raise RuntimeError(
                "Unknown Trading cancellation "
                f"{cancel_request_id}"
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
            row.completed_at = (
                utcnow()
            )

        db.flush()

        return _snapshot(row)
