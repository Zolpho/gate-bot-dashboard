from __future__ import annotations

from typing import Any

from .trading_order_state import (
    derive_trading_order_state,
)

_TERMINAL_LOCAL_STATES = {
    "confirmed_cancelled",
    "confirmed_closed",
}


def _normalized(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def _request_id(
    request: dict[str, Any] | None,
) -> str:
    if not request:
        return ""

    return _normalized(
        request.get("request_id")
    )


def _unique_index(
    requests: list[dict[str, Any]],
    *,
    field: str,
) -> tuple[
    dict[str, dict[str, Any]],
    set[str],
]:
    index: dict[
        str,
        dict[str, Any],
    ] = {}

    conflicts: set[str] = set()

    for request in requests:
        value = _normalized(
            request.get(field)
        )

        if not value:
            continue

        existing = index.get(value)

        if (
            existing is not None
            and _request_id(existing)
            != _request_id(request)
        ):
            conflicts.add(value)
            continue

        index[value] = request

    return (
        index,
        conflicts,
    )


def _gate_order_state(
    gate_order: dict[str, Any],
) -> dict[str, str | None]:
    gate_status = (
        _normalized(
            gate_order.get("status")
        ).lower()
        or "open"
    )

    return {
        "execution_status": None,
        "cancellation_status": None,
        "effective_status": gate_status,
        "source": "gate",
    }


def merge_open_spot_orders(
    *,
    account_id: str,
    pair: str,
    gate_orders: list[dict[str, Any]],
    local_requests: list[dict[str, Any]],
    cancellations_by_request_id: dict[
        str,
        dict[str, Any] | None,
    ],
) -> list[dict[str, Any]]:
    """
    Join Gate's actual open-order set to dashboard audits.

    Gate determines which orders are actually open.
    Dashboard records determine whether an order has a
    managed intent/audit trail.

    Ambiguous local identity matches fail closed and are
    reported as unmanaged.
    """

    normalized_account = (
        account_id.strip().lower()
    )

    normalized_pair = (
        pair.strip().upper()
    )

    candidates = [
        request
        for request in local_requests
        if (
            str(
                request.get("account_id")
                or ""
            ).strip().lower()
            == normalized_account
            and str(
                request.get("pair")
                or ""
            ).strip().upper()
            == normalized_pair
        )
    ]

    (
        by_gate_id,
        gate_id_conflicts,
    ) = _unique_index(
        candidates,
        field="gate_order_id",
    )

    (
        by_gate_text,
        gate_text_conflicts,
    ) = _unique_index(
        candidates,
        field="gate_text",
    )

    result: list[dict[str, Any]] = []

    for gate_order in gate_orders:
        if not isinstance(
            gate_order,
            dict,
        ):
            continue

        gate_id = _normalized(
            gate_order.get("id")
        )

        gate_text = _normalized(
            gate_order.get("text")
        )

        id_conflict = (
            bool(gate_id)
            and gate_id
            in gate_id_conflicts
        )

        text_conflict = (
            bool(gate_text)
            and gate_text
            in gate_text_conflicts
        )

        id_match = (
            by_gate_id.get(gate_id)
            if (
                gate_id
                and not id_conflict
            )
            else None
        )

        text_match = (
            by_gate_text.get(gate_text)
            if (
                gate_text
                and not text_conflict
            )
            else None
        )

        cross_conflict = (
            id_match is not None
            and text_match is not None
            and _request_id(id_match)
            != _request_id(text_match)
        )

        identity_conflict = (
            id_conflict
            or text_conflict
            or cross_conflict
        )

        request = None
        match_method = "none"

        if identity_conflict:
            match_method = "conflict"

        elif id_match is not None:
            request = id_match
            match_method = "gate_order_id"

        elif text_match is not None:
            request = text_match
            match_method = "gate_text"

        managed = (
            request is not None
            and not identity_conflict
        )

        cancellation = None

        if managed:
            cancellation = (
                cancellations_by_request_id
                .get(
                    _request_id(request)
                )
            )

            order_state = (
                derive_trading_order_state(
                    request=request,
                    cancellation=cancellation,
                )
            )
        else:
            order_state = (
                _gate_order_state(
                    gate_order
                )
            )

        gate_status = (
            _normalized(
                gate_order.get("status")
            ).lower()
            or "open"
        )

        local_effective = str(
            order_state.get(
                "effective_status"
            )
            or ""
        ).lower()

        state_conflict = (
            managed
            and gate_status == "open"
            and local_effective
            in _TERMINAL_LOCAL_STATES
        )

        result.append(
            {
                "gate_order": gate_order,
                "gate_order_id": (
                    gate_id or None
                ),
                "gate_status": gate_status,
                "managed": managed,
                "match_method": (
                    match_method
                ),
                "identity_conflict": (
                    identity_conflict
                ),
                "state_conflict": (
                    state_conflict
                ),
                "request": request,
                "cancellation": (
                    cancellation
                ),
                "order_state": (
                    order_state
                ),
            }
        )

    return result
