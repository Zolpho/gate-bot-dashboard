from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from decimal import (
    Decimal,
    InvalidOperation,
)
from typing import Any

from .gate_client import (
    GateAPIError,
    GateClient,
)
from .trading_order_audit import (
    get_order_request,
    mark_order_request,
    record_order_reconciliation,
)
from .trading_order_locks import (
    release_trading_lock,
)


PENDING_LOOKUP_MISS_LABELS = {
    "ORDER_NOT_FOUND",
    "ORDER_CLOSED",
    "ORDER_CANCELLED",
}

FINISHED_HISTORY_MAX_DAYS = 30
FINISHED_HISTORY_CLOCK_SKEW_SECONDS = 300
FINISHED_HISTORY_PAGE_LIMIT = 100
FINISHED_HISTORY_MAX_PAGES = 10


class TradingOrderReconcileError(
    RuntimeError
):
    pass


def _utc_datetime(
    value: str | None,
) -> datetime:
    if not value:
        raise TradingOrderReconcileError(
            "Trading request has no created_at"
        )

    parsed = datetime.fromisoformat(
        value
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )
    else:
        parsed = parsed.astimezone(
            timezone.utc
        )

    return parsed


def _decimal_equal(
    left: Any,
    right: Any,
) -> bool:
    try:
        return (
            Decimal(str(left))
            == Decimal(str(right))
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return False


def _pending_lookup_miss(
    exc: GateAPIError,
) -> bool:
    return bool(
        exc.status_code == 404
        or str(
            exc.label or ""
        ).upper()
        in PENDING_LOOKUP_MISS_LABELS
    )


def _order_matches_request(
    order: dict[str, Any],
    request: dict[str, Any],
) -> tuple[
    bool,
    list[str],
]:
    mismatches: list[str] = []

    expected_pair = str(
        request["pair"]
    ).upper()

    actual_pair = str(
        order.get("currency_pair")
        or ""
    ).upper()

    if actual_pair != expected_pair:
        mismatches.append(
            "currency_pair"
        )

    if str(
        order.get("type") or ""
    ).lower() != "limit":
        mismatches.append(
            "type"
        )

    actual_account = str(
        order.get("account")
        or ""
    ).lower()

    if (
        actual_account
        and actual_account != "spot"
    ):
        mismatches.append(
            "account"
        )

    if str(
        order.get("side") or ""
    ).lower() != str(
        request["side"]
    ).lower():
        mismatches.append(
            "side"
        )

    if not _decimal_equal(
        order.get("price"),
        request["price"],
    ):
        mismatches.append(
            "price"
        )

    if not _decimal_equal(
        order.get("amount"),
        request["amount"],
    ):
        mismatches.append(
            "amount"
        )

    actual_tif = str(
        order.get("time_in_force")
        or ""
    ).lower()

    if (
        actual_tif
        and actual_tif
        != str(
            request["time_in_force"]
        ).lower()
    ):
        mismatches.append(
            "time_in_force"
        )

    return (
        not mismatches,
        mismatches,
    )


def _order_status(
    order: dict[str, Any],
) -> str:
    return str(
        order.get("status")
        or ""
    ).strip().lower()


def _candidate_identity(
    order: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": str(
            order.get("id")
            or ""
        ),
        "text": str(
            order.get("text")
            or ""
        ),
        "currency_pair": str(
            order.get("currency_pair")
            or ""
        ),
        "status": _order_status(
            order
        ),
        "side": str(
            order.get("side")
            or ""
        ),
        "type": str(
            order.get("type")
            or ""
        ),
        "account": str(
            order.get("account")
            or ""
        ),
        "price": str(
            order.get("price")
            or ""
        ),
        "amount": str(
            order.get("amount")
            or ""
        ),
        "time_in_force": str(
            order.get("time_in_force")
            or ""
        ),
        "left": str(
            order.get("left")
            or ""
        ),
        "filled_total": str(
            order.get("filled_total")
            or ""
        ),
        "finish_as": str(
            order.get("finish_as")
            or ""
        ),
        "create_time": str(
            order.get("create_time")
            or ""
        ),
        "update_time": str(
            order.get("update_time")
            or ""
        ),
    }


def _match_candidate(
    order: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    matches, mismatches = (
        _order_matches_request(
            order,
            request,
        )
    )

    return {
        "matches": matches,
        "mismatches": mismatches,
        "order": _candidate_identity(
            order
        ),
    }


def _status_for_confirmed_order(
    order: dict[str, Any],
) -> str:
    status = _order_status(
        order
    )

    if status == "open":
        return "confirmed_open"

    if status == "closed":
        return "confirmed_closed"

    if status == "cancelled":
        return "confirmed_cancelled"

    return "confirmed"


def _finished_window(
    request: dict[str, Any],
    *,
    now: datetime,
) -> tuple[
    int,
    int,
    bool,
]:
    created = _utc_datetime(
        request.get("created_at")
    )

    oldest_allowed = (
        now
        - timedelta(
            days=FINISHED_HISTORY_MAX_DAYS
        )
        + timedelta(
            minutes=1
        )
    )

    requested_start = (
        created
        - timedelta(
            seconds=(
                FINISHED_HISTORY_CLOCK_SKEW_SECONDS
            )
        )
    )

    history_limited = (
        requested_start
        < oldest_allowed
    )

    start = max(
        requested_start,
        oldest_allowed,
    )

    return (
        int(start.timestamp()),
        int(now.timestamp()),
        history_limited,
    )


async def _lookup_pending(
    *,
    client: GateClient,
    lookup_id: str,
    pair: str,
) -> tuple[
    dict[str, Any] | None,
    GateAPIError | None,
]:
    try:
        response = (
            await client.get_spot_order(
                lookup_id,
                currency_pair=pair,
                account="spot",
            )
        )

    except GateAPIError as exc:
        if _pending_lookup_miss(
            exc
        ):
            return (
                None,
                exc,
            )

        raise

    data = response.data

    if not isinstance(
        data,
        dict,
    ):
        raise TradingOrderReconcileError(
            "Gate Spot order lookup returned "
            "an unexpected response shape"
        )

    return (
        data,
        None,
    )


async def _scan_finished(
    *,
    client: GateClient,
    request: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    (
        from_timestamp,
        to_timestamp,
        history_limited,
    ) = _finished_window(
        request,
        now=now,
    )

    gate_order_id = str(
        request.get(
            "gate_order_id"
        )
        or ""
    )

    gate_text = str(
        request.get(
            "gate_text"
        )
        or ""
    )

    matches: list[
        dict[str, Any]
    ] = []

    exhausted = False

    for page in range(
        1,
        FINISHED_HISTORY_MAX_PAGES
        + 1,
    ):
        response = (
            await client.list_spot_orders(
                currency_pair=(
                    request["pair"]
                ),
                status="finished",
                page=page,
                limit=(
                    FINISHED_HISTORY_PAGE_LIMIT
                ),
                account="spot",
                from_timestamp=(
                    from_timestamp
                ),
                to_timestamp=(
                    to_timestamp
                ),
            )
        )

        rows = (
            response.data
            if isinstance(
                response.data,
                list,
            )
            else []
        )

        clean = [
            item
            for item in rows
            if isinstance(
                item,
                dict,
            )
        ]

        for order in clean:
            order_id = str(
                order.get("id")
                or ""
            )

            text = str(
                order.get("text")
                or ""
            )

            if (
                gate_order_id
                and order_id
                == gate_order_id
            ):
                matches.append(
                    order
                )

            elif (
                gate_text
                and text == gate_text
            ):
                matches.append(
                    order
                )

        if len(clean) < (
            FINISHED_HISTORY_PAGE_LIMIT
        ):
            exhausted = True
            break

    return {
        "matches": matches,
        "history_limited": (
            history_limited
        ),
        "search_exhausted": (
            exhausted
        ),
        "from_timestamp": (
            from_timestamp
        ),
        "to_timestamp": (
            to_timestamp
        ),
    }


def _persist_result(
    *,
    request: dict[str, Any],
    outcome: str,
    confidence: str,
    summary: str,
    details: dict[str, Any],
    gate_order_id: str = "",
    gate_status: str = "",
    request_status: str,
    completed: bool,
    release_lock: bool,
) -> dict[str, Any]:
    reconciliation = (
        record_order_reconciliation(
            request_id=(
                request["request_id"]
            ),
            account_id=(
                request["account_id"]
            ),
            username=(
                request["username"]
            ),
            pair=request["pair"],
            outcome=outcome,
            confidence=confidence,
            gate_order_id=(
                gate_order_id
            ),
            gate_status=(
                gate_status
            ),
            summary=summary,
            details=details,
        )
    )

    updated = mark_order_request(
        request["request_id"],
        status=request_status,
        error=(
            ""
            if confidence
            == "definitive"
            else summary
        ),
        gate_order_id=(
            gate_order_id
        ),
        completed=completed,
    )

    lock_released = False

    if release_lock:
        lock_released = (
            release_trading_lock(
                account_id=(
                    request[
                        "account_id"
                    ]
                ),
                funding_asset=(
                    request[
                        "funding_asset"
                    ]
                ),
                owner_request_id=(
                    request[
                        "request_id"
                    ]
                ),
            )
        )

    return {
        "status": (
            request_status
        ),
        "outcome": outcome,
        "confidence": confidence,
        "gate_read_performed": (
            details.get(
                "gate_read_performed",
                False,
            )
        ),
        "lock_released": (
            lock_released
        ),
        "manual_review_required": (
            request_status
            in {
                "attention",
                "uncertain",
            }
        ),
        "audit": updated,
        "reconciliation": (
            reconciliation
        ),
    }


async def reconcile_spot_order_request(
    *,
    client: GateClient,
    request_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    request = get_order_request(
        request_id
    )

    if request is None:
        raise TradingOrderReconcileError(
            "Unknown Trading order request "
            f"{request_id}"
        )

    if not request[
        "write_performed"
    ]:
        return _persist_result(
            request=request,
            outcome="not_submitted",
            confidence="definitive",
            summary=(
                "The audit record proves no Gate "
                "Spot write was attempted."
            ),
            details={
                "gate_read_performed": False,
            },
            request_status=(
                "not_submitted"
            ),
            completed=True,
            release_lock=True,
        )

    effective_now = (
        now
        or datetime.now(
            timezone.utc
        )
    )

    if effective_now.tzinfo is None:
        effective_now = (
            effective_now.replace(
                tzinfo=timezone.utc
            )
        )

    gate_order_id = str(
        request.get(
            "gate_order_id"
        )
        or ""
    )

    gate_text = str(
        request.get(
            "gate_text"
        )
        or ""
    )

    lookup_id = (
        gate_order_id
        or gate_text
    )

    if not lookup_id:
        return _persist_result(
            request=request,
            outcome=(
                "missing_correlation"
            ),
            confidence=(
                "inconclusive"
            ),
            summary=(
                "Trading request has no Gate "
                "order ID or custom text."
            ),
            details={
                "gate_read_performed": False,
            },
            request_status="attention",
            completed=False,
            release_lock=False,
        )

    try:
        pending, pending_miss = (
            await _lookup_pending(
                client=client,
                lookup_id=lookup_id,
                pair=request["pair"],
            )
        )

    except GateAPIError as exc:
        return _persist_result(
            request=request,
            outcome="lookup_error",
            confidence="inconclusive",
            summary=(
                "Gate Spot order lookup failed."
            ),
            details={
                "gate_read_performed": True,
                "phase": (
                    "single_order_lookup"
                ),
                "status_code": (
                    exc.status_code
                ),
                "label": exc.label,
                "response": exc.response,
            },
            request_status="uncertain",
            completed=False,
            release_lock=False,
        )

    if pending is not None:
        candidate = _match_candidate(
            pending,
            request,
        )

        actual_id = str(
            pending.get("id")
            or ""
        )

        actual_status = (
            _order_status(
                pending
            )
        )

        if not candidate[
            "matches"
        ]:
            return _persist_result(
                request=request,
                outcome=(
                    "correlation_conflict"
                ),
                confidence="definitive",
                summary=(
                    "Gate returned an order for "
                    "the correlation identifier, "
                    "but its immutable order intent "
                    "does not match the dashboard "
                    "request."
                ),
                details={
                    "gate_read_performed": True,
                    "phase": (
                        "single_order_lookup"
                    ),
                    "candidate": candidate,
                },
                gate_order_id=actual_id,
                gate_status=(
                    actual_status
                ),
                request_status="attention",
                completed=False,
                release_lock=False,
            )

        return _persist_result(
            request=request,
            outcome=(
                "order_found"
            ),
            confidence="definitive",
            summary=(
                "Gate Spot order was found "
                "and matches the dashboard "
                "request."
            ),
            details={
                "gate_read_performed": True,
                "phase": (
                    "single_order_lookup"
                ),
                "candidate": candidate,
            },
            gate_order_id=actual_id,
            gate_status=actual_status,
            request_status=(
                _status_for_confirmed_order(
                    pending
                )
            ),
            completed=True,
            release_lock=True,
        )

    try:
        finished = await _scan_finished(
            client=client,
            request=request,
            now=effective_now,
        )

    except GateAPIError as exc:
        return _persist_result(
            request=request,
            outcome="lookup_error",
            confidence="inconclusive",
            summary=(
                "Gate finished-order history "
                "lookup failed."
            ),
            details={
                "gate_read_performed": True,
                "phase": (
                    "finished_history"
                ),
                "status_code": (
                    exc.status_code
                ),
                "label": exc.label,
                "response": exc.response,
                "pending_lookup_label": (
                    pending_miss.label
                    if pending_miss
                    else ""
                ),
            },
            request_status="uncertain",
            completed=False,
            release_lock=False,
        )

    matches = finished[
        "matches"
    ]

    if len(matches) > 1:
        return _persist_result(
            request=request,
            outcome=(
                "duplicate_correlation"
            ),
            confidence="definitive",
            summary=(
                "Multiple finished Gate orders "
                "matched the same dashboard "
                "correlation identifier."
            ),
            details={
                "gate_read_performed": True,
                "phase": (
                    "finished_history"
                ),
                "candidates": [
                    _candidate_identity(
                        order
                    )
                    for order
                    in matches
                ],
                "history": finished,
            },
            request_status="attention",
            completed=False,
            release_lock=False,
        )

    if len(matches) == 1:
        order = matches[0]

        candidate = _match_candidate(
            order,
            request,
        )

        actual_id = str(
            order.get("id")
            or ""
        )

        actual_status = (
            _order_status(
                order
            )
        )

        if not candidate[
            "matches"
        ]:
            return _persist_result(
                request=request,
                outcome=(
                    "correlation_conflict"
                ),
                confidence="definitive",
                summary=(
                    "Finished Gate order has the "
                    "expected correlation but "
                    "does not match the dashboard "
                    "order intent."
                ),
                details={
                    "gate_read_performed": True,
                    "phase": (
                        "finished_history"
                    ),
                    "candidate": candidate,
                    "history": finished,
                },
                gate_order_id=actual_id,
                gate_status=(
                    actual_status
                ),
                request_status="attention",
                completed=False,
                release_lock=False,
            )

        return _persist_result(
            request=request,
            outcome="order_found",
            confidence="definitive",
            summary=(
                "Finished Gate Spot order was "
                "found and matches the dashboard "
                "request."
            ),
            details={
                "gate_read_performed": True,
                "phase": (
                    "finished_history"
                ),
                "candidate": candidate,
                "history": finished,
            },
            gate_order_id=actual_id,
            gate_status=actual_status,
            request_status=(
                _status_for_confirmed_order(
                    order
                )
            ),
            completed=True,
            release_lock=True,
        )

    if finished[
        "history_limited"
    ]:
        outcome = (
            "history_window_expired"
        )

        summary = (
            "No matching Gate order was found, "
            "and the request predates Gate's "
            "searchable 30-day finished-order "
            "history window."
        )

    elif not finished[
        "search_exhausted"
    ]:
        outcome = (
            "history_search_incomplete"
        )

        summary = (
            "No matching Gate order was found "
            "within the bounded finished-order "
            "pagination search."
        )

    else:
        outcome = "not_found"

        summary = (
            "No matching pending or finished "
            "Gate Spot order was found. "
            "Absence is not sufficient proof "
            "that an ambiguous write did not "
            "reach Gate."
        )

    return _persist_result(
        request=request,
        outcome=outcome,
        confidence="inconclusive",
        summary=summary,
        details={
            "gate_read_performed": True,
            "phase": "finished_history",
            "history": finished,
            "pending_lookup_label": (
                pending_miss.label
                if pending_miss
                else ""
            ),
        },
        request_status="uncertain",
        completed=False,
        release_lock=False,
    )
