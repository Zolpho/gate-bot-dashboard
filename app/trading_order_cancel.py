from __future__ import annotations

import time
from decimal import (
    Decimal,
    InvalidOperation,
)
from typing import Any

from .config import Settings
from .gate_client import (
    GateAPIError,
    GateClient,
)
from .trading_credentials import (
    TradingConfigError,
    get_trading_account,
)
from .trading_order_audit import (
    get_order_request,
)
from .trading_order_amend_audit import (
    get_active_order_amendment,
    list_order_amendments,
)
from .trading_order_cancel_audit import (
    TradingOrderCancelConflict,
    get_order_cancellation,
    mark_order_cancellation,
    reserve_order_cancellation,
)
from .trading_rate_limit import (
    enforce_trading_cancel_rate_limit,
)


_ALREADY_FINISHED_LABELS = {
    "ORDER_CLOSED",
    "ORDER_CANCELLED",
}


class TradingOrderCancelDenied(
    RuntimeError
):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code

        super().__init__(
            message
        )

    def detail(
        self,
    ) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status_code": (
                self.status_code
            ),
            "gate_write_performed": False,
            "write_performed": False,
        }


def _decimal(
    value: Any,
) -> Decimal | None:
    try:
        result = Decimal(
            str(value)
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None

    if not result.is_finite():
        return None

    return result


def _bounded_cancel_exptime_ms(
    settings: Settings,
) -> int:
    return max(
        1000,
        min(
            int(
                settings
                .trading_order_cancel_exptime_ms
            ),
            30000,
        ),
    )


def _base_result(
    *,
    status: str,
    order_request_id: str,
    gate_write_performed: bool,
    definitive: bool,
    cancellation: dict[str, Any] | None = None,
    manual_review_required: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "status": status,
        "order_request_id": (
            order_request_id
        ),
        "gate_write_performed": (
            gate_write_performed
        ),
        "write_performed": (
            gate_write_performed
        ),
        "definitive": definitive,
        "manual_review_required": (
            manual_review_required
        ),
        "cancellation": cancellation,
    }

    result.update(
        extra
    )

    return result


def _gate_order_state(
    data: Any,
) -> tuple[
    str,
    str,
]:
    if not isinstance(
        data,
        dict,
    ):
        return (
            "",
            "",
        )

    status = str(
        data.get("status")
        or ""
    ).strip().lower()

    finish_as = str(
        data.get("finish_as")
        or ""
    ).strip().lower()

    return (
        status,
        finish_as,
    )


def _is_cancelled(
    data: Any,
) -> bool:
    (
        status,
        finish_as,
    ) = _gate_order_state(
        data
    )

    return (
        status == "cancelled"
        or finish_as == "cancelled"
    )


def _is_finished(
    data: Any,
) -> bool:
    (
        status,
        finish_as,
    ) = _gate_order_state(
        data
    )

    if _is_cancelled(data):
        return True

    if status == "closed":
        return True

    return (
        finish_as
        not in {
            "",
            "open",
        }
    )



_SUCCESSFUL_AMENDMENT_PRICE_STATUSES = {
    "amended",
    "confirmed_amended",
}


def _cancellation_expected_price(
    source: dict[str, Any],
) -> tuple[
    Decimal | None,
    str | None,
]:
    """
    Resolve the last durable price that cancellation
    is allowed to expect from Gate.

    The creation audit remains immutable. A later
    definitive completed amendment changes only the
    expected current price; Gate order ID, pair, side,
    amount, type and text remain anchored to the
    original order request.

    Amendment history is newest-first. Failed,
    rejected, aborted or confirmed-not-applied
    amendments do not change the expected price.

    An unresolved active amendment fails closed:
    cancellation must not guess which price Gate has.
    """

    expected = _decimal(
        source.get("price")
    )

    request_id = str(
        source.get("request_id")
        or ""
    ).strip()

    if not request_id:
        return (
            expected,
            None,
        )

    active = (
        get_active_order_amendment(
            request_id
        )
    )

    if active is not None:
        return (
            None,
            "active_amendment",
        )

    amendments = (
        list_order_amendments(
            request_id,
            limit=200,
        )
    )

    for amendment in amendments:
        if not isinstance(
            amendment,
            dict,
        ):
            continue

        status = str(
            amendment.get("status")
            or ""
        ).strip().lower()

        if (
            status
            not in
            _SUCCESSFUL_AMENDMENT_PRICE_STATUSES
        ):
            continue

        completed_at = str(
            amendment.get(
                "completed_at"
            )
            or ""
        ).strip()

        if not completed_at:
            continue

        # A successful amendment status without
        # the historical PATCH boundary is an
        # inconsistent audit. Fail closed.
        if (
            amendment.get(
                "write_performed"
            )
            is not True
        ):
            return (
                None,
                "amendment_write_boundary",
            )

        requested_price = _decimal(
            amendment.get(
                "requested_price"
            )
        )

        if (
            requested_price is None
            or requested_price <= 0
        ):
            return (
                None,
                "amendment_price",
            )

        return (
            requested_price,
            None,
        )

    return (
        expected,
        None,
    )


def _source_matches_gate(
    *,
    source: dict[str, Any],
    data: Any,
) -> list[str]:
    if not isinstance(
        data,
        dict,
    ):
        return [
            "response_shape"
        ]

    mismatches: list[str] = []

    expected_id = str(
        source.get(
            "gate_order_id"
        )
        or ""
    )

    actual_id = str(
        data.get("id")
        or ""
    )

    if actual_id != expected_id:
        mismatches.append(
            "gate_order_id"
        )

    pair = str(
        data.get(
            "currency_pair"
        )
        or ""
    ).upper()

    if (
        pair
        and pair
        != str(
            source.get("pair")
            or ""
        ).upper()
    ):
        mismatches.append(
            "currency_pair"
        )

    account = str(
        data.get("account")
        or ""
    ).lower()

    if (
        account
        and account
        not in {
            "spot",
            "normal",
        }
    ):
        mismatches.append(
            "account"
        )

    side = str(
        data.get("side")
        or ""
    ).lower()

    if (
        side
        and side
        != str(
            source.get("side")
            or ""
        ).lower()
    ):
        mismatches.append(
            "side"
        )

    order_type = str(
        data.get("type")
        or ""
    ).lower()

    if (
        order_type
        and order_type
        != "limit"
    ):
        mismatches.append(
            "type"
        )

    actual_amount = _decimal(
        data.get("amount")
    )

    expected_amount = _decimal(
        source.get("amount")
    )

    if (
        actual_amount is not None
        and expected_amount is not None
        and actual_amount
        != expected_amount
    ):
        mismatches.append(
            "amount"
        )

    actual_price = _decimal(
        data.get("price")
    )

    (
        expected_price,
        amendment_issue,
    ) = _cancellation_expected_price(
        source
    )

    if amendment_issue is not None:
        mismatches.append(
            amendment_issue
        )

    elif (
        actual_price is not None
        and expected_price is not None
        and actual_price
        != expected_price
    ):
        mismatches.append(
            "price"
        )

    gate_text = str(
        source.get("gate_text")
        or ""
    )

    actual_text = str(
        data.get("text")
        or ""
    )

    if (
        gate_text
        and actual_text
        and actual_text
        != gate_text
    ):
        mismatches.append(
            "text"
        )

    return mismatches



_CANCEL_RECOVERY_RESULT_KEY = (
    "__cancel_recovery_result__"
)

_CANCEL_OPEN_SCAN_LIMIT = 100
_CANCEL_OPEN_SCAN_MAX_PAGES = 10

_CANCEL_LOOKUP_NOT_FOUND_LABELS = {
    "ORDER_NOT_FOUND",
    "CLIENT_ID_NOT_FOUND",
}

_DURABLE_COMPLETED_CANCELLATION_STATUSES = {
    "aborted",
    "already_cancelled",
    "already_finished",
    "cancelled",
    "confirmed_cancelled",
    "confirmed_finished",
    "local_rejected",
    "rejected",
}


def _gate_error_summary(
    error: GateAPIError,
) -> dict[str, Any]:
    return {
        "status_code":
            error.status_code,
        "label":
            error.label,
        "response":
            error.response,
        "message":
            str(error),
    }


def _is_cancel_lookup_not_found(
    error: GateAPIError,
) -> bool:
    label = str(
        error.label
        or ""
    ).strip().upper()

    return (
        error.status_code == 404
        and label
        in _CANCEL_LOOKUP_NOT_FOUND_LABELS
    )


def _cancel_recovery_sentinel(
    result: str,
    **details: Any,
) -> dict[str, Any]:
    value = {
        _CANCEL_RECOVERY_RESULT_KEY:
            result,
    }

    value.update(
        details
    )

    return value


def _cancel_recovery_result(
    data: Any,
) -> str:
    if not isinstance(
        data,
        dict,
    ):
        return ""

    return str(
        data.get(
            _CANCEL_RECOVERY_RESULT_KEY
        )
        or ""
    ).strip()


def _durable_completed_cancellation_result(
    cancellation: dict[str, Any],
) -> dict[str, Any] | None:
    """
    A completed cancellation audit is durable
    authority for the outcome of that cancellation
    attempt.

    Do not replace a completed result with later Gate
    lookup uncertainty simply because Gate no longer
    exposes the finished order.
    """

    completed_at = str(
        cancellation.get(
            "completed_at"
        )
        or ""
    ).strip()

    if not completed_at:
        return None

    status = str(
        cancellation.get("status")
        or ""
    ).strip().lower()

    order_request_id = str(
        cancellation.get(
            "order_request_id"
        )
        or ""
    ).strip()

    historical_write = bool(
        cancellation.get(
            "write_performed"
        )
    )

    if (
        status
        not in
        _DURABLE_COMPLETED_CANCELLATION_STATUSES
    ):
        return _base_result(
            status="attention",
            order_request_id=(
                order_request_id
            ),
            gate_write_performed=False,
            definitive=False,
            cancellation=(
                cancellation
            ),
            manual_review_required=True,
            reconciliation={
                "result":
                    "completed_audit_status_unknown",
                "stored_status":
                    status,
            },
            historical_cancel_write_performed=(
                historical_write
            ),
        )

    return _base_result(
        status=status,
        order_request_id=(
            order_request_id
        ),
        gate_write_performed=False,
        definitive=True,
        cancellation=(
            cancellation
        ),
        reconciliation={
            "result":
                "durable_completed",
            "stored_status":
                status,
        },
        historical_cancel_write_performed=(
            historical_write
        ),
    )


async def _read_cancel_state(
    *,
    client: GateClient,
    source: dict[str, Any],
) -> tuple[
    dict[str, Any] | None,
    GateAPIError | None,
]:
    """
    Read the current Gate state for cancellation
    recovery.

    Primary lookup:
        GET /spot/orders/{id}

    Gate runtime can return ORDER_NOT_FOUND immediately
    after a successful cancellation. In that specific
    case only, scan this pair's open orders.

    Absence from open orders never proves cancellation:
    the order may have filled. The caller must keep the
    cancellation outcome uncertain.
    """

    try:
        response = (
            await client.get_spot_order(
                str(
                    source[
                        "gate_order_id"
                    ]
                ),
                currency_pair=str(
                    source["pair"]
                ),
                account="spot",
            )
        )

    except GateAPIError as exc:
        if not _is_cancel_lookup_not_found(
            exc
        ):
            return (
                None,
                exc,
            )

        primary_error = (
            _gate_error_summary(
                exc
            )
        )

        gate_order_id = str(
            source.get(
                "gate_order_id"
            )
            or ""
        )

        pair = str(
            source.get("pair")
            or ""
        ).strip().upper()

        for page in range(
            1,
            _CANCEL_OPEN_SCAN_MAX_PAGES
            + 1,
        ):
            try:
                open_response = (
                    await client.list_spot_orders(
                        currency_pair=pair,
                        status="open",
                        page=page,
                        limit=(
                            _CANCEL_OPEN_SCAN_LIMIT
                        ),
                        account="spot",
                    )
                )

            except GateAPIError as scan_exc:
                return (
                    None,
                    scan_exc,
                )

            rows = open_response.data

            if not isinstance(
                rows,
                list,
            ):
                return (
                    _cancel_recovery_sentinel(
                        "open_scan_invalid",
                        primary_error=(
                            primary_error
                        ),
                        page=page,
                        response_shape=(
                            type(rows).__name__
                        ),
                    ),
                    None,
                )

            matches = [
                row
                for row in rows
                if isinstance(
                    row,
                    dict,
                )
                and str(
                    row.get("id")
                    or ""
                )
                == gate_order_id
            ]

            if len(matches) > 1:
                return (
                    _cancel_recovery_sentinel(
                        "open_order_duplicate",
                        primary_error=(
                            primary_error
                        ),
                        page=page,
                        match_count=(
                            len(matches)
                        ),
                    ),
                    None,
                )

            if len(matches) == 1:
                return (
                    matches[0],
                    None,
                )

            # A short page proves this bounded
            # pagination has reached the end.
            if (
                len(rows)
                < _CANCEL_OPEN_SCAN_LIMIT
            ):
                return (
                    _cancel_recovery_sentinel(
                        "not_found_not_open",
                        primary_error=(
                            primary_error
                        ),
                        pages_scanned=page,
                    ),
                    None,
                )

        # Every page was full. Do not claim absence:
        # there may be additional open orders beyond
        # our deliberately bounded scan.
        return (
            _cancel_recovery_sentinel(
                "open_scan_incomplete",
                primary_error=(
                    primary_error
                ),
                pages_scanned=(
                    _CANCEL_OPEN_SCAN_MAX_PAGES
                ),
                page_limit=(
                    _CANCEL_OPEN_SCAN_LIMIT
                ),
            ),
            None,
        )

    data = (
        response.data
        if isinstance(
            response.data,
            dict,
        )
        else None
    )

    return (
        data,
        None,
    )


async def _reconcile_after_cancel_write(
    *,
    client: GateClient,
    source: dict[str, Any],
    cancel_request_id: str,
    cancellation: dict[str, Any],
) -> dict[str, Any]:
    (
        data,
        error,
    ) = await _read_cancel_state(
        client=client,
        source=source,
    )

    if error is not None:
        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status="uncertain",
                response={
                    "phase":
                        "cancel_reconciliation",
                    "gate_status_code":
                        error.status_code,
                    "gate_label":
                        error.label,
                    "gate_response":
                        error.response,
                },
                error=str(error),
                gate_status_code=(
                    error.status_code
                ),
                gate_label=(
                    error.label
                ),
                write_performed=True,
                completed=False,
            )
        )

        return _base_result(
            status="uncertain",
            order_request_id=(
                source["request_id"]
            ),
            gate_write_performed=True,
            definitive=False,
            cancellation=updated,
            manual_review_required=True,
            reconciliation={
                "result":
                    "lookup_error",
            },
        )

    recovery_result = (
        _cancel_recovery_result(
            data
        )
    )

    if recovery_result:
        if (
            recovery_result
            == "open_order_duplicate"
        ):
            updated = (
                mark_order_cancellation(
                    cancel_request_id,
                    status="attention",
                    response={
                        "phase":
                            "cancel_reconciliation",
                        "result":
                            recovery_result,
                        "recovery":
                            data,
                    },
                    error=(
                        "Gate open-order recovery "
                        "returned duplicate matches"
                    ),
                    write_performed=True,
                    completed=False,
                )
            )

            return _base_result(
                status="attention",
                order_request_id=(
                    source["request_id"]
                ),
                gate_write_performed=True,
                definitive=False,
                cancellation=updated,
                manual_review_required=True,
                reconciliation={
                    "result":
                        recovery_result,
                },
            )

        messages = {
            "not_found_not_open": (
                "Gate no longer exposes the order "
                "by ID and it was not found in a "
                "complete open-order scan. "
                "Cancellation versus fill cannot "
                "be distinguished."
            ),
            "open_scan_incomplete": (
                "Gate no longer exposes the order "
                "by ID and the bounded open-order "
                "scan could not prove absence."
            ),
            "open_scan_invalid": (
                "Gate open-order recovery returned "
                "an unexpected response shape."
            ),
        }

        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status="uncertain",
                response={
                    "phase":
                        "cancel_reconciliation",
                    "result":
                        recovery_result,
                    "recovery":
                        data,
                },
                error=messages.get(
                    recovery_result,
                    (
                        "Gate cancellation recovery "
                        "remains uncertain"
                    ),
                ),
                write_performed=True,
                completed=False,
            )
        )

        return _base_result(
            status="uncertain",
            order_request_id=(
                source["request_id"]
            ),
            gate_write_performed=True,
            definitive=False,
            cancellation=updated,
            manual_review_required=True,
            reconciliation={
                "result":
                    recovery_result,
            },
        )

    mismatches = (
        _source_matches_gate(
            source=source,
            data=data,
        )
    )

    if mismatches:
        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status="attention",
                response={
                    "phase":
                        "cancel_reconciliation",
                    "gate_response":
                        data,
                    "mismatches":
                        mismatches,
                },
                error=(
                    "Gate cancellation reconciliation "
                    "returned a different order"
                ),
                write_performed=True,
                completed=False,
            )
        )

        return _base_result(
            status="attention",
            order_request_id=(
                source["request_id"]
            ),
            gate_write_performed=True,
            definitive=False,
            cancellation=updated,
            manual_review_required=True,
            reconciliation={
                "result":
                    "correlation_conflict",
                "mismatches":
                    mismatches,
            },
        )

    if _is_cancelled(data):
        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status=(
                    "confirmed_cancelled"
                ),
                response={
                    "phase":
                        "cancel_reconciliation",
                    "gate_response":
                        data,
                },
                write_performed=True,
                completed=True,
            )
        )

        return _base_result(
            status="confirmed_cancelled",
            order_request_id=(
                source["request_id"]
            ),
            gate_write_performed=True,
            definitive=True,
            cancellation=updated,
            gate_order=(
                data
            ),
        )

    if _is_finished(data):
        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status=(
                    "confirmed_finished"
                ),
                response={
                    "phase":
                        "cancel_reconciliation",
                    "gate_response":
                        data,
                },
                error=(
                    "Order finished before cancellation "
                    "could be confirmed"
                ),
                write_performed=True,
                completed=True,
            )
        )

        return _base_result(
            status="confirmed_finished",
            order_request_id=(
                source["request_id"]
            ),
            gate_write_performed=True,
            definitive=True,
            cancellation=updated,
            gate_order=(
                data
            ),
        )

    # Still open after an ambiguous DELETE.
    # Never automatically send another DELETE.
    updated = (
        mark_order_cancellation(
            cancel_request_id,
            status="uncertain",
            response={
                "phase":
                    "cancel_reconciliation",
                "gate_response":
                    data,
                "result":
                    "still_open",
            },
            error=(
                "Order remains open after an "
                "ambiguous cancellation attempt"
            ),
            write_performed=True,
            completed=False,
        )
    )

    return _base_result(
        status="uncertain",
        order_request_id=(
            source["request_id"]
        ),
        gate_write_performed=True,
        definitive=False,
        cancellation=updated,
        manual_review_required=True,
        gate_order=data,
        reconciliation={
            "result":
                "still_open",
        },
    )


async def cancel_limit_order(
    *,
    settings: Settings,
    username: str,
    allowed_account_ids: set[str],
    cancel_request_id: str,
    order_request_id: str,
    confirmation: str,
) -> dict[str, Any]:
    """
    Cancel exactly one audited Gate Spot order.

    Safety invariants:
    - source order must exist in our Trading audit;
    - dashboard account assignment is explicit;
    - cancellation has its own independent live arm;
    - exact cancellation confirmation;
    - real Gate order ID required;
    - fresh Trading-key GET before DELETE;
    - Gate order identity must match local audit;
    - persistent cancellation idempotency;
    - exactly one DELETE attempt;
    - no automatic DELETE retry;
    - ambiguous DELETE uses GET-only reconciliation.
    """
    normalized_username = (
        username.strip()
    )

    normalized_cancel_id = (
        cancel_request_id.strip()
    )

    normalized_order_id = (
        order_request_id.strip()
    )

    if not normalized_username:
        raise TradingOrderCancelDenied(
            code="invalid_user",
            message=(
                "Dashboard username "
                "is required"
            ),
            status_code=400,
        )

    if not normalized_cancel_id:
        raise TradingOrderCancelDenied(
            code="invalid_cancel_request_id",
            message=(
                "cancel_request_id "
                "is required"
            ),
            status_code=400,
        )

    if not normalized_order_id:
        raise TradingOrderCancelDenied(
            code="invalid_order_request_id",
            message=(
                "order_request_id "
                "is required"
            ),
            status_code=400,
        )

    source = get_order_request(
        normalized_order_id
    )

    if source is None:
        raise TradingOrderCancelDenied(
            code="order_not_found",
            message=(
                "Trading order request "
                "not found"
            ),
            status_code=404,
        )

    account_id = str(
        source.get("account_id")
        or ""
    ).strip().lower()

    allowed = {
        item.strip().lower()
        for item in allowed_account_ids
        if item.strip()
    }

    if account_id not in allowed:
        # Hide cross-account request existence.
        raise TradingOrderCancelDenied(
            code="order_not_found",
            message=(
                "Trading order request "
                "not found"
            ),
            status_code=404,
        )

    # Independent cancellation kill switch.
    if not (
        settings
        .trading_order_cancels_enabled
    ):
        raise TradingOrderCancelDenied(
            code="cancellation_disabled",
            message=(
                "Live Spot order "
                "cancellation is disabled"
            ),
            status_code=503,
        )

    if confirmation != (
        settings
        .trading_order_cancel_confirmation_text
    ):
        raise TradingOrderCancelDenied(
            code="confirmation_mismatch",
            message=(
                "Exact cancellation "
                "confirmation text "
                "is required"
            ),
            status_code=400,
        )

    if str(
        source.get("order_type")
        or ""
    ).lower() != "limit":
        raise TradingOrderCancelDenied(
            code="unsupported_order_type",
            message=(
                "Only audited Spot "
                "limit orders can be cancelled"
            ),
            status_code=409,
        )

    if not bool(
        source.get(
            "write_performed"
        )
    ):
        raise TradingOrderCancelDenied(
            code="order_not_submitted",
            message=(
                "This Trading request "
                "did not perform a Gate write"
            ),
            status_code=409,
        )

    gate_order_id = str(
        source.get(
            "gate_order_id"
        )
        or ""
    ).strip()

    if (
        not gate_order_id
        or not gate_order_id.isdigit()
    ):
        raise TradingOrderCancelDenied(
            code="gate_order_id_missing",
            message=(
                "A real Gate order ID "
                "is required for cancellation"
            ),
            status_code=409,
        )

    pair = str(
        source.get("pair")
        or ""
    ).strip().upper()

    if (
        not pair
        or "_"
        not in pair
    ):
        raise TradingOrderCancelDenied(
            code="invalid_pair",
            message=(
                "Audited Trading pair "
                "is invalid"
            ),
            status_code=409,
        )

    try:
        trading_account = (
            get_trading_account(
                account_id
            )
        )

    except TradingConfigError as exc:
        raise TradingOrderCancelDenied(
            code="trading_config_error",
            message=str(exc),
            status_code=503,
        ) from exc

    if (
        trading_account is None
        or not trading_account.enabled
        or not trading_account.configured
    ):
        raise TradingOrderCancelDenied(
            code=(
                "trading_credentials_missing"
            ),
            message=(
                "Isolated Spot Trading "
                "credentials are not configured "
                f"for Gate account {account_id}"
            ),
            status_code=503,
        )

    async with GateClient(
        settings,
        trading_account,
    ) as client:
        # Fresh read before reserving a cancellation
        # operation. If this fails, no DELETE has
        # been attempted and no cancellation audit
        # is consumed.
        (
            current,
            precheck_error,
        ) = await _read_cancel_state(
            client=client,
            source=source,
        )

        if precheck_error is not None:
            return _base_result(
                status="precheck_error",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                gate_status_code=(
                    precheck_error.status_code
                ),
                gate_label=(
                    precheck_error.label
                ),
                error=str(
                    precheck_error
                ),
            )

        mismatches = (
            _source_matches_gate(
                source=source,
                data=current,
            )
        )

        if mismatches:
            return _base_result(
                status="precheck_conflict",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                manual_review_required=True,
                mismatches=(
                    mismatches
                ),
            )

        if _is_cancelled(
            current
        ):
            return _base_result(
                status="already_cancelled",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                gate_order=current,
            )

        if _is_finished(
            current
        ):
            return _base_result(
                status="already_finished",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                gate_order=current,
            )

        (
            current_status,
            current_finish_as,
        ) = _gate_order_state(
            current
        )

        if (
            current_status != "open"
            or current_finish_as
            not in {
                "",
                "open",
            }
        ):
            return _base_result(
                status="precheck_error",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                error=(
                    "Gate order is not in a "
                    "cancellable open state"
                ),
                gate_order=current,
            )

        # Existing cancellation intent is checked
        # before consuming a new rate-limit token.
        #
        # We check both unique identities. The central
        # reservation verifier remains authoritative:
        # a matching prior cancellation is replayed,
        # while an ID collision/mismatch is rejected.
        existing_by_order = (
            get_order_cancellation(
                order_request_id=(
                    normalized_order_id
                )
            )
        )

        existing_by_cancel = (
            get_order_cancellation(
                cancel_request_id=(
                    normalized_cancel_id
                )
            )
        )

        if (
            existing_by_order is not None
            or existing_by_cancel is not None
        ):
            try:
                (
                    cancellation,
                    created,
                ) = reserve_order_cancellation(
                    cancel_request_id=(
                        normalized_cancel_id
                    ),
                    order_request_id=(
                        normalized_order_id
                    ),
                    account_id=(
                        account_id
                    ),
                    username=(
                        normalized_username
                    ),
                    pair=pair,
                    gate_order_id=(
                        gate_order_id
                    ),
                )

            except TradingOrderCancelConflict as exc:
                raise TradingOrderCancelDenied(
                    code=(
                        "cancel_idempotency_conflict"
                    ),
                    message=str(exc),
                    status_code=409,
                ) from exc

            if created:
                # An existing immutable cancellation
                # disappeared between lookup and reserve.
                # Fail closed rather than allowing an
                # unmetered cancellation write.
                raise TradingOrderCancelDenied(
                    code=(
                        "cancel_idempotency_conflict"
                    ),
                    message=(
                        "Cancellation audit changed "
                        "during idempotency validation"
                    ),
                    status_code=409,
                )

            return _base_result(
                status="idempotent_replay",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=bool(
                    cancellation.get(
                        "completed_at"
                    )
                ),
                cancellation=(
                    cancellation
                ),
                original_status=(
                    cancellation.get(
                        "status"
                    )
                ),
                original_write_performed=(
                    bool(
                        cancellation.get(
                            "write_performed"
                        )
                    )
                ),
                manual_review_required=(
                    not bool(
                        cancellation.get(
                            "completed_at"
                        )
                    )
                ),
            )

        # Only a genuinely new cancellation intent
        # consumes the independent cancellation bucket.
        #
        # This happens after authorization, confirmation,
        # credentials and the fresh Gate open-state GET,
        # but before creating a cancellation audit or
        # crossing the DELETE boundary.
        enforce_trading_cancel_rate_limit(
            settings=settings,
            username=(
                normalized_username
            ),
            account_id=account_id,
        )

        try:
            (
                cancellation,
                created,
            ) = reserve_order_cancellation(
                cancel_request_id=(
                    normalized_cancel_id
                ),
                order_request_id=(
                    normalized_order_id
                ),
                account_id=(
                    account_id
                ),
                username=(
                    normalized_username
                ),
                pair=pair,
                gate_order_id=(
                    gate_order_id
                ),
            )

        except TradingOrderCancelConflict as exc:
            raise TradingOrderCancelDenied(
                code=(
                    "cancel_idempotency_conflict"
                ),
                message=str(exc),
                status_code=409,
            ) from exc

        if not created:
            # A concurrent identical cancellation may
            # have won after our pre-check. The unique
            # audit constraint still prevents a second
            # DELETE. At worst this conservatively
            # consumes one extra rate-limit token.
            return _base_result(
                status="idempotent_replay",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=bool(
                    cancellation.get(
                        "completed_at"
                    )
                ),
                cancellation=(
                    cancellation
                ),
                original_status=(
                    cancellation.get(
                        "status"
                    )
                ),
                original_write_performed=(
                    bool(
                        cancellation.get(
                            "write_performed"
                        )
                    )
                ),
                manual_review_required=(
                    not bool(
                        cancellation.get(
                            "completed_at"
                        )
                    )
                ),
            )

        # Recheck the independent arm immediately
        # before crossing the cancellation boundary.
        if not (
            settings
            .trading_order_cancels_enabled
        ):
            updated = (
                mark_order_cancellation(
                    normalized_cancel_id,
                    status="aborted",
                    response={
                        "reason":
                            "Cancellation arm "
                            "is disabled",
                    },
                    error=(
                        "Cancellation arm "
                        "is disabled"
                    ),
                    write_performed=False,
                    completed=True,
                )
            )

            return _base_result(
                status="aborted",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                cancellation=updated,
            )

        try:
            final_account = (
                get_trading_account(
                    account_id
                )
            )

        except TradingConfigError:
            final_account = None

        if (
            final_account is None
            or not final_account.enabled
            or not final_account.configured
            or final_account.api_key
            != trading_account.api_key
        ):
            updated = (
                mark_order_cancellation(
                    normalized_cancel_id,
                    status="aborted",
                    response={
                        "reason":
                            "Trading credential "
                            "changed before cancel",
                    },
                    error=(
                        "Trading credential "
                        "changed or became unavailable"
                    ),
                    write_performed=False,
                    completed=True,
                )
            )

            return _base_result(
                status="aborted",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                cancellation=updated,
            )

        expires_at_ms = (
            int(
                time.time_ns()
                // 1_000_000
            )
            + _bounded_cancel_exptime_ms(
                settings
            )
        )

        # Persist BEFORE DELETE. A process crash
        # after this point must fail closed as an
        # ambiguous cancellation attempt.
        cancelling = (
            mark_order_cancellation(
                normalized_cancel_id,
                status="cancelling",
                response={
                    "gate_order_id":
                        gate_order_id,
                    "pair":
                        pair,
                    "expires_at_ms":
                        expires_at_ms,
                },
                write_performed=True,
                completed=False,
            )
        )

        try:
            response = (
                await client.cancel_spot_order(
                    gate_order_id,
                    currency_pair=pair,
                    expires_at_ms=(
                        expires_at_ms
                    ),
                    account="spot",
                )
            )

        except ValueError as exc:
            updated = (
                mark_order_cancellation(
                    normalized_cancel_id,
                    status="local_rejected",
                    response={
                        "message":
                            str(exc),
                    },
                    error=str(exc),
                    write_performed=False,
                    completed=True,
                )
            )

            return _base_result(
                status="local_rejected",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=True,
                cancellation=updated,
            )

        except GateAPIError as exc:
            label = str(
                exc.label or ""
            ).upper()

            if (
                label
                in _ALREADY_FINISHED_LABELS
            ):
                status = (
                    "already_cancelled"
                    if label
                    == "ORDER_CANCELLED"
                    else "already_finished"
                )

                updated = (
                    mark_order_cancellation(
                        normalized_cancel_id,
                        status=status,
                        response={
                            "gate_response":
                                exc.response,
                        },
                        error=str(exc),
                        gate_status_code=(
                            exc.status_code
                        ),
                        gate_label=(
                            exc.label
                        ),
                        write_performed=True,
                        completed=True,
                    )
                )

                return _base_result(
                    status=status,
                    order_request_id=(
                        normalized_order_id
                    ),
                    gate_write_performed=True,
                    definitive=True,
                    cancellation=updated,
                )

            # A normal client-side Gate rejection
            # is a definitive response, but it is
            # never automatically retried.
            if (
                exc.status_code
                is not None
                and 400
                <= exc.status_code
                < 500
                and exc.status_code
                not in {
                    408,
                    409,
                    425,
                    429,
                }
            ):
                updated = (
                    mark_order_cancellation(
                        normalized_cancel_id,
                        status="rejected",
                        response={
                            "gate_response":
                                exc.response,
                        },
                        error=str(exc),
                        gate_status_code=(
                            exc.status_code
                        ),
                        gate_label=(
                            exc.label
                        ),
                        write_performed=True,
                        completed=True,
                    )
                )

                return _base_result(
                    status="rejected",
                    order_request_id=(
                        normalized_order_id
                    ),
                    gate_write_performed=True,
                    definitive=True,
                    cancellation=updated,
                )

            uncertain = (
                mark_order_cancellation(
                    normalized_cancel_id,
                    status="uncertain",
                    response={
                        "phase":
                            "gate_cancel",
                        "gate_response":
                            exc.response,
                    },
                    error=str(exc),
                    gate_status_code=(
                        exc.status_code
                    ),
                    gate_label=(
                        exc.label
                    ),
                    write_performed=True,
                    completed=False,
                )
            )

            return await (
                _reconcile_after_cancel_write(
                    client=client,
                    source=source,
                    cancel_request_id=(
                        normalized_cancel_id
                    ),
                    cancellation=(
                        uncertain
                    ),
                )
            )

        except Exception as exc:
            uncertain = (
                mark_order_cancellation(
                    normalized_cancel_id,
                    status="uncertain",
                    response={
                        "phase":
                            "gate_cancel",
                        "exception_type":
                            type(exc).__name__,
                    },
                    error=str(exc),
                    write_performed=True,
                    completed=False,
                )
            )

            return await (
                _reconcile_after_cancel_write(
                    client=client,
                    source=source,
                    cancel_request_id=(
                        normalized_cancel_id
                    ),
                    cancellation=(
                        uncertain
                    ),
                )
            )

        data = (
            response.data
            if isinstance(
                response.data,
                dict,
            )
            else None
        )

        mismatches = (
            _source_matches_gate(
                source=source,
                data=data,
            )
        )

        if (
            response.status_code != 200
            or mismatches
            or not _is_cancelled(
                data
            )
        ):
            uncertain = (
                mark_order_cancellation(
                    normalized_cancel_id,
                    status="uncertain",
                    response={
                        "phase":
                            "gate_cancel_response",
                        "response_status":
                            response.status_code,
                        "gate_response":
                            data,
                        "mismatches":
                            mismatches,
                    },
                    error=(
                        "Gate cancellation response "
                        "could not be accepted as "
                        "definitive"
                    ),
                    gate_status_code=(
                        response.status_code
                    ),
                    write_performed=True,
                    completed=False,
                )
            )

            return await (
                _reconcile_after_cancel_write(
                    client=client,
                    source=source,
                    cancel_request_id=(
                        normalized_cancel_id
                    ),
                    cancellation=(
                        uncertain
                    ),
                )
            )

        updated = (
            mark_order_cancellation(
                normalized_cancel_id,
                status="cancelled",
                response={
                    "gate_response":
                        data,
                    "response_status":
                        response.status_code,
                },
                gate_status_code=(
                    response.status_code
                ),
                write_performed=True,
                completed=True,
            )
        )

        return _base_result(
            status="cancelled",
            order_request_id=(
                normalized_order_id
            ),
            gate_write_performed=True,
            definitive=True,
            cancellation=updated,
            gate_order=data,
        )


async def reconcile_limit_order_cancellation(
    *,
    settings: Settings,
    username: str,
    allowed_account_ids: set[str],
    order_request_id: str,
) -> dict[str, Any]:
    """
    Reconcile an existing cancellation attempt.

    This function performs Gate reads only.
    It never sends DELETE and never retries a
    cancellation write.
    """
    normalized_username = (
        username.strip()
    )

    normalized_order_id = (
        order_request_id.strip()
    )

    if not normalized_username:
        raise TradingOrderCancelDenied(
            code="invalid_user",
            message=(
                "Dashboard username "
                "is required"
            ),
            status_code=400,
        )

    if not normalized_order_id:
        raise TradingOrderCancelDenied(
            code="invalid_order_request_id",
            message=(
                "order_request_id "
                "is required"
            ),
            status_code=400,
        )

    source = get_order_request(
        normalized_order_id
    )

    if source is None:
        raise TradingOrderCancelDenied(
            code="order_not_found",
            message=(
                "Trading order request "
                "not found"
            ),
            status_code=404,
        )

    account_id = str(
        source.get("account_id")
        or ""
    ).strip().lower()

    allowed = {
        item.strip().lower()
        for item in allowed_account_ids
        if item.strip()
    }

    if account_id not in allowed:
        raise TradingOrderCancelDenied(
            code="order_not_found",
            message=(
                "Trading order request "
                "not found"
            ),
            status_code=404,
        )

    from .trading_order_cancel_audit import (
        get_order_cancellation,
    )

    cancellation = (
        get_order_cancellation(
            order_request_id=(
                normalized_order_id
            )
        )
    )

    if cancellation is None:
        raise TradingOrderCancelDenied(
            code="cancellation_not_found",
            message=(
                "No cancellation attempt "
                "exists for this order"
            ),
            status_code=404,
        )

    durable_result = (
        _durable_completed_cancellation_result(
            cancellation
        )
    )

    if durable_result is not None:
        return durable_result

    gate_order_id = str(
        source.get(
            "gate_order_id"
        )
        or ""
    ).strip()

    if (
        not gate_order_id
        or not gate_order_id.isdigit()
    ):
        raise TradingOrderCancelDenied(
            code="gate_order_id_missing",
            message=(
                "A real Gate order ID "
                "is required for reconciliation"
            ),
            status_code=409,
        )

    try:
        trading_account = (
            get_trading_account(
                account_id
            )
        )

    except TradingConfigError as exc:
        raise TradingOrderCancelDenied(
            code="trading_config_error",
            message=str(exc),
            status_code=503,
        ) from exc

    if (
        trading_account is None
        or not trading_account.enabled
        or not trading_account.configured
    ):
        raise TradingOrderCancelDenied(
            code=(
                "trading_credentials_missing"
            ),
            message=(
                "Isolated Spot Trading "
                "credentials are not configured "
                f"for Gate account {account_id}"
            ),
            status_code=503,
        )

    async with GateClient(
        settings,
        trading_account,
    ) as client:
        (
            current,
            error,
        ) = await _read_cancel_state(
            client=client,
            source=source,
        )

    if error is not None:
        return _base_result(
            status="uncertain",
            order_request_id=(
                normalized_order_id
            ),
            gate_write_performed=False,
            definitive=False,
            cancellation=(
                cancellation
            ),
            manual_review_required=True,
            reconciliation={
                "result":
                    "lookup_error",
                "gate_status_code":
                    error.status_code,
                "gate_label":
                    error.label,
                "message":
                    str(error),
            },
        )

    recovery_result = (
        _cancel_recovery_result(
            current
        )
    )

    if recovery_result:
        cancel_request_id = str(
            cancellation[
                "cancel_request_id"
            ]
        )

        historical_write = bool(
            cancellation.get(
                "write_performed"
            )
        )

        if (
            recovery_result
            == "open_order_duplicate"
        ):
            updated = (
                mark_order_cancellation(
                    cancel_request_id,
                    status="attention",
                    response={
                        "phase":
                            "manual_cancel_reconciliation",
                        "result":
                            recovery_result,
                        "recovery":
                            current,
                    },
                    error=(
                        "Gate open-order recovery "
                        "returned duplicate matches"
                    ),
                    write_performed=(
                        historical_write
                    ),
                    completed=False,
                )
            )

            return _base_result(
                status="attention",
                order_request_id=(
                    normalized_order_id
                ),
                gate_write_performed=False,
                definitive=False,
                cancellation=updated,
                manual_review_required=True,
                reconciliation={
                    "result":
                        recovery_result,
                },
                historical_cancel_write_performed=(
                    historical_write
                ),
            )

        messages = {
            "not_found_not_open": (
                "Gate no longer exposes the order "
                "by ID and it was not found in a "
                "complete open-order scan. "
                "Cancellation versus fill cannot "
                "be distinguished."
            ),
            "open_scan_incomplete": (
                "Gate no longer exposes the order "
                "by ID and the bounded open-order "
                "scan could not prove absence."
            ),
            "open_scan_invalid": (
                "Gate open-order recovery returned "
                "an unexpected response shape."
            ),
        }

        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status="uncertain",
                response={
                    "phase":
                        "manual_cancel_reconciliation",
                    "result":
                        recovery_result,
                    "recovery":
                        current,
                },
                error=messages.get(
                    recovery_result,
                    (
                        "Gate cancellation recovery "
                        "remains uncertain"
                    ),
                ),
                write_performed=(
                    historical_write
                ),
                completed=False,
            )
        )

        return _base_result(
            status="uncertain",
            order_request_id=(
                normalized_order_id
            ),
            gate_write_performed=False,
            definitive=False,
            cancellation=updated,
            manual_review_required=True,
            reconciliation={
                "result":
                    recovery_result,
            },
            historical_cancel_write_performed=(
                historical_write
            ),
        )

    mismatches = (
        _source_matches_gate(
            source=source,
            data=current,
        )
    )

    if mismatches:
        return _base_result(
            status="attention",
            order_request_id=(
                normalized_order_id
            ),
            gate_write_performed=False,
            definitive=False,
            cancellation=(
                cancellation
            ),
            manual_review_required=True,
            reconciliation={
                "result":
                    "correlation_conflict",
                "mismatches":
                    mismatches,
            },
        )

    cancel_request_id = str(
        cancellation[
            "cancel_request_id"
        ]
    )

    if _is_cancelled(
        current
    ):
        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status=(
                    "confirmed_cancelled"
                ),
                response={
                    "phase":
                        "manual_cancel_reconciliation",
                    "gate_response":
                        current,
                },

                # Preserve whether the original
                # cancellation attempt crossed
                # the DELETE boundary.
                write_performed=(
                    bool(
                        cancellation.get(
                            "write_performed"
                        )
                    )
                ),
                completed=True,
            )
        )

        return _base_result(
            status="confirmed_cancelled",
            order_request_id=(
                normalized_order_id
            ),
            gate_write_performed=False,
            definitive=True,
            cancellation=updated,
            gate_order=current,
            reconciliation={
                "result":
                    "confirmed_cancelled",
            },
        )

    if _is_finished(
        current
    ):
        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status=(
                    "confirmed_finished"
                ),
                response={
                    "phase":
                        "manual_cancel_reconciliation",
                    "gate_response":
                        current,
                },
                error=(
                    "Order finished without a "
                    "confirmed cancelled state"
                ),
                write_performed=(
                    bool(
                        cancellation.get(
                            "write_performed"
                        )
                    )
                ),
                completed=True,
            )
        )

        return _base_result(
            status="confirmed_finished",
            order_request_id=(
                normalized_order_id
            ),
            gate_write_performed=False,
            definitive=True,
            cancellation=updated,
            gate_order=current,
            reconciliation={
                "result":
                    "confirmed_finished",
            },
        )

    (
        current_status,
        current_finish_as,
    ) = _gate_order_state(
        current
    )

    if (
        current_status == "open"
        and current_finish_as
        in {
            "",
            "open",
        }
    ):
        updated = (
            mark_order_cancellation(
                cancel_request_id,
                status="uncertain",
                response={
                    "phase":
                        "manual_cancel_reconciliation",
                    "gate_response":
                        current,
                    "result":
                        "still_open",
                },
                error=(
                    "Order remains open after "
                    "the cancellation attempt"
                ),
                write_performed=(
                    bool(
                        cancellation.get(
                            "write_performed"
                        )
                    )
                ),
                completed=False,
            )
        )

        return _base_result(
            status="uncertain",
            order_request_id=(
                normalized_order_id
            ),
            gate_write_performed=False,
            definitive=False,
            cancellation=updated,
            manual_review_required=True,
            gate_order=current,
            reconciliation={
                "result":
                    "still_open",
            },
        )

    return _base_result(
        status="attention",
        order_request_id=(
            normalized_order_id
        ),
        gate_write_performed=False,
        definitive=False,
        cancellation=(
            cancellation
        ),
        manual_review_required=True,
        gate_order=current,
        reconciliation={
            "result":
                "unknown_gate_state",
        },
    )
