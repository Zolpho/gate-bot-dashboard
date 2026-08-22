from __future__ import annotations

from typing import Any

from .trading_order_state import (
    derive_trading_order_state,
)


def _dict(
    value: Any,
) -> dict[str, Any]:
    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _text(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def _gate_response(
    operation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not operation:
        return None

    response = _dict(
        operation.get("response")
    )

    gate = response.get(
        "gate_response"
    )

    return (
        gate
        if (
            isinstance(gate, dict)
            and gate
        )
        else None
    )


def build_recent_spot_orders(
    *,
    requests: list[dict[str, Any]],
    cancellations_by_request_id: dict[
        str,
        dict[str, Any] | None,
    ],
) -> list[dict[str, Any]]:
    """
    Build durable recent-order rows from persisted
    dashboard audit records only.

    A persisted cancellation Gate response is newer
    evidence than the original execution response, so
    it is preferred as the last known Gate snapshot.
    """

    rows: list[
        dict[str, Any]
    ] = []

    for request in requests:
        if not isinstance(
            request,
            dict,
        ):
            continue

        request_id = _text(
            request.get("request_id")
        )

        cancellation = (
            cancellations_by_request_id
            .get(request_id)
            if request_id
            else None
        )

        order_state = (
            derive_trading_order_state(
                request=request,
                cancellation=cancellation,
            )
        )

        execution_gate = (
            _gate_response(
                request
            )
        )

        cancellation_gate = (
            _gate_response(
                cancellation
            )
        )

        gate_snapshot = (
            cancellation_gate
            or execution_gate
        )

        gate_snapshot_source = None

        if cancellation_gate is not None:
            gate_snapshot_source = (
                "cancellation"
            )

        elif execution_gate is not None:
            gate_snapshot_source = (
                "execution"
            )

        gate_order_id = (
            _text(
                request.get(
                    "gate_order_id"
                )
            )
            or _text(
                (
                    gate_snapshot
                    or {}
                ).get("id")
            )
        )

        gate_status = (
            _text(
                (
                    gate_snapshot
                    or {}
                ).get("status")
            ).lower()
            or None
        )

        finish_as = (
            _text(
                (
                    gate_snapshot
                    or {}
                ).get("finish_as")
            ).lower()
            or None
        )

        rows.append(
            {
                "managed": True,
                "history_source": (
                    "dashboard_audit"
                ),
                "request_id": (
                    request_id
                    or None
                ),
                "gate_order_id": (
                    gate_order_id
                    or None
                ),
                "gate_status": (
                    gate_status
                ),
                "finish_as": (
                    finish_as
                ),
                "gate_snapshot_source": (
                    gate_snapshot_source
                ),
                "gate_snapshot": (
                    gate_snapshot
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

    return rows
