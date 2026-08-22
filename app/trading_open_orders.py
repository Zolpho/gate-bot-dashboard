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



def flatten_open_spot_orders(
    value: Any,
    *,
    inherited_pair: str = "",
) -> list[dict[str, Any]]:
    """
    Flatten Gate /spot/open_orders data into actual
    Spot order dictionaries.

    Gate may group account-wide open orders by pair.
    Preserve/inherit the group pair when an individual
    order omits currency_pair.

    This helper is pure/read-only.
    """

    rows: list[
        dict[str, Any]
    ] = []

    if isinstance(
        value,
        list,
    ):
        for item in value:
            rows.extend(
                flatten_open_spot_orders(
                    item,
                    inherited_pair=(
                        inherited_pair
                    ),
                )
            )

        return rows

    if not isinstance(
        value,
        dict,
    ):
        return rows

    pair = (
        _normalized(
            value.get(
                "currency_pair"
            )
        ).upper()
        or inherited_pair.strip().upper()
    )

    gate_id = _normalized(
        value.get("id")
    )

    if gate_id:
        row = dict(value)

        if (
            pair
            and not _normalized(
                row.get(
                    "currency_pair"
                )
            )
        ):
            row[
                "currency_pair"
            ] = pair

        rows.append(row)

        return rows

    for child in value.values():
        if isinstance(
            child,
            (list, dict),
        ):
            rows.extend(
                flatten_open_spot_orders(
                    child,
                    inherited_pair=pair,
                )
            )

    return rows


def merge_account_open_spot_orders(
    *,
    account_id: str,
    gate_orders: list[dict[str, Any]],
    local_requests: list[dict[str, Any]],
    cancellations_by_request_id: dict[
        str,
        dict[str, Any] | None,
    ],
) -> list[dict[str, Any]]:
    """
    Merge an account-wide Gate open-order set.

    Existing pair-scoped identity logic remains the
    authority. Gate orders are grouped by their live
    currency_pair and each group is passed through
    merge_open_spot_orders() independently.

    This prevents an audit from one pair from managing
    a live Gate order belonging to another pair even if
    an identity value collides.
    """

    by_pair: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    pair_order: list[str] = []

    for gate_order in gate_orders:
        if not isinstance(
            gate_order,
            dict,
        ):
            continue

        pair = _normalized(
            gate_order.get(
                "currency_pair"
            )
        ).upper()

        if pair not in by_pair:
            by_pair[pair] = []
            pair_order.append(pair)

        by_pair[pair].append(
            gate_order
        )

    result: list[
        dict[str, Any]
    ] = []

    for pair in pair_order:
        result.extend(
            merge_open_spot_orders(
                account_id=account_id,
                pair=pair,
                gate_orders=(
                    by_pair[pair]
                ),
                local_requests=(
                    local_requests
                ),
                cancellations_by_request_id=(
                    cancellations_by_request_id
                ),
            )
        )

    return result


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
