from __future__ import annotations

from typing import Any

_CANCELLED_STATUSES = {
    "already_cancelled",
    "cancelled",
    "confirmed_cancelled",
}

_FINISHED_STATUSES = {
    "confirmed_finished",
}

_UNCERTAIN_CANCELLATION_STATUSES = {
    "attention",
    "cancelling",
    "lookup_error",
    "uncertain",
}


def _normalized(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip().lower()


def derive_trading_order_state(
    *,
    request: dict[str, Any],
    cancellation: dict[str, Any] | None,
) -> dict[str, str | None]:
    """
    Preserve the original execution lifecycle while
    exposing the best known current order state.

    A definitive cancellation overrides an older
    execution state such as confirmed_open without
    rewriting the execution audit itself.
    """

    execution_status = (
        _normalized(
            request.get("status")
        )
        or "unknown"
    )

    cancellation_status = (
        _normalized(
            cancellation.get("status")
        )
        if cancellation
        else ""
    )

    effective_status = execution_status
    source = "execution"

    if (
        cancellation_status
        in _CANCELLED_STATUSES
    ):
        effective_status = (
            "confirmed_cancelled"
        )
        source = "cancellation"

    elif (
        cancellation_status
        in _FINISHED_STATUSES
    ):
        effective_status = (
            "confirmed_closed"
        )
        source = "cancellation"

    elif (
        cancellation_status
        in _UNCERTAIN_CANCELLATION_STATUSES
    ):
        effective_status = "uncertain"
        source = "cancellation"

    return {
        "execution_status": (
            execution_status
        ),
        "cancellation_status": (
            cancellation_status or None
        ),
        "effective_status": (
            effective_status
        ),
        "source": source,
    }
