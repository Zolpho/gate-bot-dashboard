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
from .trading_order_amend_audit import (
    TradingOrderAmendConflict,
    get_active_order_amendment,
    get_order_amendment,
    mark_order_amendment,
    reserve_order_amendment,
)
from .trading_order_audit import (
    get_order_request,
)
from .trading_order_cancel_audit import (
    get_order_cancellation,
)


_AMBIGUOUS_HTTP_STATUS_CODES = {
    408,
    409,
    425,
    429,
}


class TradingOrderAmendDenied(
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


def _decimal_text(
    value: Decimal,
) -> str:
    return format(
        value.normalize(),
        "f",
    )


def _bounded_amend_exptime_ms(
    settings: Settings,
) -> int:
    return max(
        1000,
        min(
            int(
                settings
                .trading_order_amend_exptime_ms
            ),
            30000,
        ),
    )


def _base_result(
    *,
    status: str,
    order_request_id: str,
    amend_request_id: str,
    gate_write_performed: bool,
    definitive: bool,
    amendment: dict[str, Any]
    | None = None,
    manual_review_required: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "status": status,
        "order_request_id": (
            order_request_id
        ),
        "amend_request_id": (
            amend_request_id
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
        "amendment": amendment,
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

    return (
        str(
            data.get("status")
            or ""
        ).strip().lower(),
        str(
            data.get("finish_as")
            or ""
        ).strip().lower(),
    )


def _order_is_open(
    data: Any,
) -> bool:
    (
        status,
        finish_as,
    ) = _gate_order_state(
        data
    )

    return (
        status == "open"
        and finish_as
        in {
            "",
            "open",
        }
    )


def _order_is_terminal(
    data: Any,
) -> bool:
    (
        status,
        finish_as,
    ) = _gate_order_state(
        data
    )

    if status in {
        "closed",
        "cancelled",
    }:
        return True

    return (
        bool(finish_as)
        and finish_as != "open"
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
            "Gate order payload is not an object"
        ]

    mismatches: list[str] = []

    expected_id = str(
        source.get("gate_order_id")
        or ""
    ).strip()

    actual_id = str(
        data.get("id")
        or ""
    ).strip()

    if actual_id != expected_id:
        mismatches.append(
            "Gate order ID mismatch"
        )

    expected_pair = str(
        source.get("pair")
        or ""
    ).strip().upper()

    actual_pair = str(
        data.get("currency_pair")
        or ""
    ).strip().upper()

    if actual_pair != expected_pair:
        mismatches.append(
            "Gate currency pair mismatch"
        )

    actual_account = str(
        data.get("account")
        or ""
    ).strip().lower()

    if actual_account != "spot":
        mismatches.append(
            "Gate account is not spot"
        )

    actual_type = str(
        data.get("type")
        or ""
    ).strip().lower()

    if actual_type != "limit":
        mismatches.append(
            "Gate order type is not limit"
        )

    expected_side = str(
        source.get("side")
        or ""
    ).strip().lower()

    actual_side = str(
        data.get("side")
        or ""
    ).strip().lower()

    if (
        expected_side
        and actual_side
        != expected_side
    ):
        mismatches.append(
            "Gate order side mismatch"
        )

    expected_text = str(
        source.get("gate_text")
        or ""
    ).strip()

    actual_text = str(
        data.get("text")
        or ""
    ).strip()

    if (
        expected_text
        and actual_text
        and actual_text
        != expected_text
    ):
        mismatches.append(
            "Gate order text mismatch"
        )

    expected_tif = str(
        source.get("time_in_force")
        or ""
    ).strip().lower()

    actual_tif = str(
        data.get("time_in_force")
        or ""
    ).strip().lower()

    if (
        expected_tif
        and actual_tif
        and actual_tif
        != expected_tif
    ):
        mismatches.append(
            "Gate time-in-force mismatch"
        )

    return mismatches


async def _read_gate_order(
    *,
    client: GateClient,
    source: dict[str, Any],
) -> tuple[
    dict[str, Any] | None,
    GateAPIError | None,
]:
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
        return (
            None,
            exc,
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


def _price_digits(
    value: Decimal,
) -> int:
    normalized = (
        value.normalize()
    )

    exponent = (
        normalized
        .as_tuple()
        .exponent
    )

    return max(
        0,
        -int(exponent),
    )


def _trade_status_allows(
    *,
    trade_status: str,
    side: str,
) -> bool:
    status = (
        trade_status
        .strip()
        .lower()
    )

    if status == "tradable":
        return True

    if (
        side == "buy"
        and status == "buyable"
    ):
        return True

    if (
        side == "sell"
        and status == "sellable"
    ):
        return True

    return False


def _book_price(
    level: Any,
) -> Decimal | None:
    if not isinstance(
        level,
        (
            list,
            tuple,
        ),
    ):
        return None

    if not level:
        return None

    value = _decimal(
        level[0]
    )

    if (
        value is None
        or value <= 0
    ):
        return None

    return value


async def _validate_requested_price(
    *,
    client: GateClient,
    source: dict[str, Any],
    requested_price: Decimal,
) -> tuple[
    dict[str, Any] | None,
    str | None,
]:
    pair = str(
        source.get("pair")
        or ""
    ).strip().upper()

    side = str(
        source.get("side")
        or ""
    ).strip().lower()

    try:
        response = (
            await client
            .get_spot_currency_pair(
                pair
            )
        )

    except GateAPIError as exc:
        return (
            None,
            (
                "Unable to read fresh Gate "
                "pair metadata: "
                + str(exc)
            ),
        )

    metadata = (
        response.data
        if isinstance(
            response.data,
            dict,
        )
        else None
    )

    if metadata is None:
        return (
            None,
            (
                "Gate pair metadata response "
                "is not an object"
            ),
        )

    metadata_pair = str(
        metadata.get("id")
        or ""
    ).strip().upper()

    if metadata_pair != pair:
        return (
            metadata,
            "Gate pair metadata identity mismatch",
        )

    try:
        precision = int(
            metadata.get(
                "precision"
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return (
            metadata,
            "Gate price precision is unavailable",
        )

    if (
        precision < 0
        or precision > 24
    ):
        return (
            metadata,
            "Gate price precision is invalid",
        )

    if (
        _price_digits(
            requested_price
        )
        > precision
    ):
        return (
            metadata,
            (
                "Requested price exceeds Gate "
                f"price precision ({precision})"
            ),
        )

    if not _trade_status_allows(
        trade_status=str(
            metadata.get(
                "trade_status"
            )
            or ""
        ),
        side=side,
    ):
        return (
            metadata,
            (
                "Gate pair is not currently "
                f"{side}able"
            ),
        )

    tif = str(
        source.get("time_in_force")
        or ""
    ).strip().lower()

    if tif != "poc":
        return (
            metadata,
            None,
        )

    try:
        book_response = (
            await client
            .get_spot_order_book(
                pair,
                limit=1,
                with_id=False,
            )
        )

    except GateAPIError as exc:
        return (
            metadata,
            (
                "Unable to read fresh Gate "
                "order book for POC validation: "
                + str(exc)
            ),
        )

    book = (
        book_response.data
        if isinstance(
            book_response.data,
            dict,
        )
        else None
    )

    if book is None:
        return (
            metadata,
            (
                "Gate order book response "
                "is not an object"
            ),
        )

    bids = (
        book.get("bids")
        if isinstance(
            book.get("bids"),
            list,
        )
        else []
    )

    asks = (
        book.get("asks")
        if isinstance(
            book.get("asks"),
            list,
        )
        else []
    )

    best_bid = (
        _book_price(
            bids[0]
        )
        if bids
        else None
    )

    best_ask = (
        _book_price(
            asks[0]
        )
        if asks
        else None
    )

    if side == "buy":
        if best_ask is None:
            return (
                metadata,
                (
                    "Fresh best ask is unavailable "
                    "for POC validation"
                ),
            )

        if (
            requested_price
            >= best_ask
        ):
            return (
                metadata,
                (
                    "POC buy amendment would "
                    "cross the current best ask"
                ),
            )

    elif side == "sell":
        if best_bid is None:
            return (
                metadata,
                (
                    "Fresh best bid is unavailable "
                    "for POC validation"
                ),
            )

        if (
            requested_price
            <= best_bid
        ):
            return (
                metadata,
                (
                    "POC sell amendment would "
                    "cross the current best bid"
                ),
            )

    return (
        metadata,
        None,
    )


def _existing_amendment_matches(
    *,
    amendment: dict[str, Any],
    source: dict[str, Any],
    username: str,
    requested_price: Decimal,
) -> bool:
    return (
        str(
            amendment.get(
                "order_request_id"
            )
            or ""
        ).strip()
        == str(
            source.get(
                "request_id"
            )
            or ""
        ).strip()
        and str(
            amendment.get(
                "account_id"
            )
            or ""
        ).strip().lower()
        == str(
            source.get(
                "account_id"
            )
            or ""
        ).strip().lower()
        and str(
            amendment.get(
                "username"
            )
            or ""
        ).strip()
        == username
        and str(
            amendment.get(
                "pair"
            )
            or ""
        ).strip().upper()
        == str(
            source.get(
                "pair"
            )
            or ""
        ).strip().upper()
        and str(
            amendment.get(
                "gate_order_id"
            )
            or ""
        ).strip()
        == str(
            source.get(
                "gate_order_id"
            )
            or ""
        ).strip()
        and _decimal(
            amendment.get(
                "requested_price"
            )
        )
        == requested_price
    )


def _definitive_gate_rejection(
    exc: GateAPIError,
) -> bool:
    status = exc.status_code

    return (
        status is not None
        and 400 <= status < 500
        and status
        not in _AMBIGUOUS_HTTP_STATUS_CODES
    )


async def _reconcile_after_amend_write(
    *,
    client: GateClient,
    source: dict[str, Any],
    amend_request_id: str,
    amendment: dict[str, Any],
) -> dict[str, Any]:
    (
        data,
        error,
    ) = await _read_gate_order(
        client=client,
        source=source,
    )

    if error is not None:
        updated = (
            mark_order_amendment(
                amend_request_id,
                status="uncertain",
                response={
                    "phase":
                        "amend_reconciliation",
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
            amend_request_id=(
                amend_request_id
            ),
            gate_write_performed=True,
            definitive=False,
            amendment=updated,
            manual_review_required=True,
            reconciliation={
                "result":
                    "lookup_error",
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
            mark_order_amendment(
                amend_request_id,
                status="attention",
                response={
                    "phase":
                        "amend_reconciliation",
                    "gate_response":
                        data,
                    "mismatches":
                        mismatches,
                },
                error=(
                    "Gate amend reconciliation "
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
            amend_request_id=(
                amend_request_id
            ),
            gate_write_performed=True,
            definitive=False,
            amendment=updated,
            manual_review_required=True,
            gate_order=data,
            reconciliation={
                "result":
                    "correlation_conflict",
                "mismatches":
                    mismatches,
            },
        )

    requested_price = _decimal(
        amendment.get(
            "requested_price"
        )
    )

    current_price = _decimal(
        amendment.get(
            "current_price"
        )
    )

    gate_price = _decimal(
        (
            data or {}
        ).get(
            "price"
        )
    )

    if (
        requested_price is not None
        and gate_price
        == requested_price
    ):
        updated = (
            mark_order_amendment(
                amend_request_id,
                status=(
                    "confirmed_amended"
                ),
                response={
                    "phase":
                        "amend_reconciliation",
                    "gate_response":
                        data,
                    "result":
                        "requested_price_present",
                },
                write_performed=True,
                completed=True,
            )
        )

        return _base_result(
            status="confirmed_amended",
            order_request_id=(
                source["request_id"]
            ),
            amend_request_id=(
                amend_request_id
            ),
            gate_write_performed=True,
            definitive=True,
            amendment=updated,
            gate_order=data,
            reconciliation={
                "result":
                    "confirmed_amended",
            },
        )

    if _order_is_terminal(
        data
    ):
        updated = (
            mark_order_amendment(
                amend_request_id,
                status=(
                    "confirmed_not_applied"
                ),
                response={
                    "phase":
                        "amend_reconciliation",
                    "gate_response":
                        data,
                    "result":
                        "terminal_without_requested_price",
                },
                error=(
                    "Order became terminal without "
                    "the requested amendment price"
                ),
                write_performed=True,
                completed=True,
            )
        )

        return _base_result(
            status="confirmed_not_applied",
            order_request_id=(
                source["request_id"]
            ),
            amend_request_id=(
                amend_request_id
            ),
            gate_write_performed=True,
            definitive=True,
            amendment=updated,
            gate_order=data,
            reconciliation={
                "result":
                    "terminal_without_requested_price",
            },
        )

    if (
        _order_is_open(
            data
        )
        and current_price
        is not None
        and gate_price
        == current_price
    ):
        updated = (
            mark_order_amendment(
                amend_request_id,
                status="uncertain",
                response={
                    "phase":
                        "amend_reconciliation",
                    "gate_response":
                        data,
                    "result":
                        "still_at_previous_price",
                },
                error=(
                    "Order remains open at the "
                    "previous price after an "
                    "ambiguous amendment attempt"
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
            amend_request_id=(
                amend_request_id
            ),
            gate_write_performed=True,
            definitive=False,
            amendment=updated,
            manual_review_required=True,
            gate_order=data,
            reconciliation={
                "result":
                    "still_at_previous_price",
            },
        )

    updated = (
        mark_order_amendment(
            amend_request_id,
            status="attention",
            response={
                "phase":
                    "amend_reconciliation",
                "gate_response":
                    data,
                "result":
                    "unexpected_price_state",
            },
            error=(
                "Gate order price after ambiguous "
                "amendment is neither the previous "
                "nor requested price"
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
        amend_request_id=(
            amend_request_id
        ),
        gate_write_performed=True,
        definitive=False,
        amendment=updated,
        manual_review_required=True,
        gate_order=data,
        reconciliation={
            "result":
                "unexpected_price_state",
        },
    )


async def amend_limit_order_price(
    *,
    settings: Settings,
    username: str,
    allowed_account_ids: set[str],
    amend_request_id: str,
    order_request_id: str,
    requested_price: Decimal,
    confirmation: str,
) -> dict[str, Any]:
    """
    Amend the price of one audited Gate Spot limit order.

    Safety invariants:
    - source order exists in local Trading audit;
    - dashboard account scope is explicit;
    - amendment has an independent live arm;
    - exact confirmation is required;
    - only a real numeric Gate order ID is accepted;
    - existing cancellation intent blocks amendment;
    - only one unresolved amendment per source order;
    - fresh Trading-key Gate GET before PATCH;
    - immutable Gate identity must match local audit;
    - order must still be open;
    - requested price must satisfy fresh pair precision;
    - POC amendments cannot cross the fresh book;
    - audit is marked amending before PATCH;
    - exactly one PATCH attempt;
    - PATCH is never automatically retried;
    - ambiguous PATCH uses GET-only reconciliation.
    """
    normalized_username = (
        username.strip()
    )

    normalized_amend_id = (
        amend_request_id.strip()
    )

    normalized_order_id = (
        order_request_id.strip()
    )

    price = _decimal(
        requested_price
    )

    if not normalized_username:
        raise TradingOrderAmendDenied(
            code="invalid_user",
            message=(
                "Dashboard username is required"
            ),
            status_code=400,
        )

    if not normalized_amend_id:
        raise TradingOrderAmendDenied(
            code="invalid_amend_request_id",
            message=(
                "amend_request_id is required"
            ),
            status_code=400,
        )

    if not normalized_order_id:
        raise TradingOrderAmendDenied(
            code="invalid_order_request_id",
            message=(
                "order_request_id is required"
            ),
            status_code=400,
        )

    if (
        price is None
        or price <= 0
    ):
        raise TradingOrderAmendDenied(
            code="invalid_price",
            message=(
                "Requested amendment price "
                "must be a positive finite decimal"
            ),
            status_code=400,
        )

    source = get_order_request(
        normalized_order_id
    )

    if source is None:
        raise TradingOrderAmendDenied(
            code="order_not_found",
            message=(
                "Trading order request not found"
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
        raise TradingOrderAmendDenied(
            code="order_not_found",
            message=(
                "Trading order request not found"
            ),
            status_code=404,
        )

    if not (
        settings
        .trading_order_amends_enabled
    ):
        raise TradingOrderAmendDenied(
            code="amendment_disabled",
            message=(
                "Live Spot order amendment "
                "is disabled"
            ),
            status_code=503,
        )

    if confirmation != (
        settings
        .trading_order_amend_confirmation_text
    ):
        raise TradingOrderAmendDenied(
            code="confirmation_mismatch",
            message=(
                "Exact amendment confirmation "
                "text is required"
            ),
            status_code=400,
        )

    if str(
        source.get("order_type")
        or ""
    ).strip().lower() != "limit":
        raise TradingOrderAmendDenied(
            code="unsupported_order_type",
            message=(
                "Only audited limit orders "
                "can be amended"
            ),
            status_code=409,
        )

    if source.get(
        "write_performed"
    ) is not True:
        raise TradingOrderAmendDenied(
            code="source_not_submitted",
            message=(
                "Source order did not cross "
                "the Gate write boundary"
            ),
            status_code=409,
        )

    source_status = str(
        source.get("status")
        or ""
    ).strip().lower()

    if source_status not in {
        "submitted",
        "confirmed_open",
    }:
        raise TradingOrderAmendDenied(
            code="source_state_not_amendable",
            message=(
                "Source order audit is not "
                "in an amendable state"
            ),
            status_code=409,
        )

    gate_order_id = str(
        source.get("gate_order_id")
        or ""
    ).strip()

    if (
        not gate_order_id
        or not gate_order_id.isdigit()
    ):
        raise TradingOrderAmendDenied(
            code="gate_order_id_missing",
            message=(
                "A real numeric Gate order ID "
                "is required for amendment"
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
        raise TradingOrderAmendDenied(
            code="invalid_pair",
            message=(
                "Source Gate Spot pair "
                "is invalid"
            ),
            status_code=409,
        )

    existing = get_order_amendment(
        normalized_amend_id
    )

    if existing is not None:
        if not _existing_amendment_matches(
            amendment=existing,
            source=source,
            username=(
                normalized_username
            ),
            requested_price=price,
        ):
            raise TradingOrderAmendDenied(
                code=(
                    "amend_idempotency_conflict"
                ),
                message=(
                    "Amendment request identity "
                    "is already bound to "
                    "different intent"
                ),
                status_code=409,
            )

        return _base_result(
            status="idempotent_replay",
            order_request_id=(
                normalized_order_id
            ),
            amend_request_id=(
                normalized_amend_id
            ),
            gate_write_performed=False,
            definitive=bool(
                existing.get(
                    "completed_at"
                )
            ),
            amendment=existing,
            original_status=(
                existing.get("status")
            ),
            original_write_performed=(
                bool(
                    existing.get(
                        "write_performed"
                    )
                )
            ),
            manual_review_required=(
                not bool(
                    existing.get(
                        "completed_at"
                    )
                )
            ),
        )

    active = (
        get_active_order_amendment(
            normalized_order_id
        )
    )

    if active is not None:
        raise TradingOrderAmendDenied(
            code="amendment_in_progress",
            message=(
                "Another unresolved amendment "
                "already exists for this order"
            ),
            status_code=409,
        )

    cancellation = (
        get_order_cancellation(
            order_request_id=(
                normalized_order_id
            )
        )
    )

    if cancellation is not None:
        raise TradingOrderAmendDenied(
            code="cancellation_recorded",
            message=(
                "A cancellation audit already "
                "exists for this order"
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
        raise TradingOrderAmendDenied(
            code="trading_config_error",
            message=str(exc),
            status_code=503,
        ) from exc

    if (
        trading_account is None
        or not trading_account.enabled
        or not trading_account.configured
    ):
        raise TradingOrderAmendDenied(
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
            lookup_error,
        ) = await _read_gate_order(
            client=client,
            source=source,
        )

        if lookup_error is not None:
            return _base_result(
                status="precheck_error",
                order_request_id=(
                    normalized_order_id
                ),
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                error=(
                    "Unable to read fresh Gate "
                    "order state"
                ),
                gate_error={
                    "status_code":
                        lookup_error.status_code,
                    "label":
                        lookup_error.label,
                    "message":
                        str(lookup_error),
                },
            )

        mismatches = (
            _source_matches_gate(
                source=source,
                data=current,
            )
        )

        if mismatches:
            return _base_result(
                status="precheck_error",
                order_request_id=(
                    normalized_order_id
                ),
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                error=(
                    "Fresh Gate order identity "
                    "does not match local audit"
                ),
                mismatches=mismatches,
                gate_order=current,
            )

        if not _order_is_open(
            current
        ):
            return _base_result(
                status="precheck_error",
                order_request_id=(
                    normalized_order_id
                ),
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                error=(
                    "Gate order is not in an "
                    "amendable open state"
                ),
                gate_order=current,
            )

        current_price = _decimal(
            (
                current or {}
            ).get("price")
        )

        if (
            current_price is None
            or current_price <= 0
        ):
            return _base_result(
                status="precheck_error",
                order_request_id=(
                    normalized_order_id
                ),
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                error=(
                    "Fresh Gate order price "
                    "is invalid"
                ),
                gate_order=current,
            )

        if price == current_price:
            return _base_result(
                status=(
                    "already_at_requested_price"
                ),
                order_request_id=(
                    normalized_order_id
                ),
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                gate_order=current,
            )

        (
            pair_metadata,
            price_error,
        ) = await _validate_requested_price(
            client=client,
            source=source,
            requested_price=price,
        )

        if price_error is not None:
            return _base_result(
                status="precheck_error",
                order_request_id=(
                    normalized_order_id
                ),
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                error=price_error,
                pair_metadata=(
                    pair_metadata
                ),
                gate_order=current,
            )

        try:
            (
                amendment,
                created,
            ) = reserve_order_amendment(
                amend_request_id=(
                    normalized_amend_id
                ),
                order_request_id=(
                    normalized_order_id
                ),
                account_id=account_id,
                username=(
                    normalized_username
                ),
                pair=pair,
                gate_order_id=(
                    gate_order_id
                ),
                current_price=(
                    current_price
                ),
                requested_price=price,
            )

        except TradingOrderAmendConflict as exc:
            raise TradingOrderAmendDenied(
                code=(
                    "amend_idempotency_conflict"
                ),
                message=str(exc),
                status_code=409,
            ) from exc

        if not created:
            return _base_result(
                status="idempotent_replay",
                order_request_id=(
                    normalized_order_id
                ),
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=bool(
                    amendment.get(
                        "completed_at"
                    )
                ),
                amendment=amendment,
                original_status=(
                    amendment.get(
                        "status"
                    )
                ),
                original_write_performed=(
                    bool(
                        amendment.get(
                            "write_performed"
                        )
                    )
                ),
                manual_review_required=(
                    not bool(
                        amendment.get(
                            "completed_at"
                        )
                    )
                ),
            )

        # Cross-operation fail-closed check:
        # cancellation may have been reserved while
        # we were performing fresh Gate reads.
        if get_order_cancellation(
            order_request_id=(
                normalized_order_id
            )
        ) is not None:
            updated = (
                mark_order_amendment(
                    normalized_amend_id,
                    status="aborted",
                    response={
                        "reason":
                            "Cancellation appeared "
                            "before amendment write",
                    },
                    error=(
                        "Cancellation audit exists"
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
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                amendment=updated,
            )

        # Recheck independent arm immediately
        # before the amendment write boundary.
        if not (
            settings
            .trading_order_amends_enabled
        ):
            updated = (
                mark_order_amendment(
                    normalized_amend_id,
                    status="aborted",
                    response={
                        "reason":
                            "Amendment arm "
                            "is disabled",
                    },
                    error=(
                        "Amendment arm "
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
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                amendment=updated,
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
                mark_order_amendment(
                    normalized_amend_id,
                    status="aborted",
                    response={
                        "reason":
                            "Trading credential "
                            "changed before amend",
                    },
                    error=(
                        "Trading credential changed "
                        "or became unavailable"
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
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                amendment=updated,
            )

        expires_at_ms = (
            int(
                time.time_ns()
                // 1_000_000
            )
            + _bounded_amend_exptime_ms(
                settings
            )
        )

        # Persist BEFORE PATCH. A crash after
        # this point is an ambiguous write.
        amending = (
            mark_order_amendment(
                normalized_amend_id,
                status="amending",
                response={
                    "phase":
                        "gate_amend",
                    "gate_order":
                        current,
                    "pair_metadata":
                        pair_metadata,
                    "current_price":
                        _decimal_text(
                            current_price
                        ),
                    "requested_price":
                        _decimal_text(
                            price
                        ),
                    "expires_at_ms":
                        expires_at_ms,
                },
                write_performed=True,
                completed=False,
            )
        )

        try:
            response = (
                await client
                .amend_spot_order(
                    gate_order_id,
                    currency_pair=pair,
                    price=(
                        _decimal_text(
                            price
                        )
                    ),
                    expires_at_ms=(
                        expires_at_ms
                    ),
                    account="spot",
                )
            )

        except ValueError as exc:
            # GateClient validation is local and
            # occurs before its HTTP request.
            updated = (
                mark_order_amendment(
                    normalized_amend_id,
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
                amend_request_id=(
                    normalized_amend_id
                ),
                gate_write_performed=False,
                definitive=True,
                amendment=updated,
            )

        except GateAPIError as exc:
            if _definitive_gate_rejection(
                exc
            ):
                updated = (
                    mark_order_amendment(
                        normalized_amend_id,
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
                    amend_request_id=(
                        normalized_amend_id
                    ),
                    gate_write_performed=True,
                    definitive=True,
                    amendment=updated,
                    definitive_rejection=True,
                )

            uncertain = (
                mark_order_amendment(
                    normalized_amend_id,
                    status="uncertain",
                    response={
                        "phase":
                            "gate_amend",
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
                _reconcile_after_amend_write(
                    client=client,
                    source=source,
                    amend_request_id=(
                        normalized_amend_id
                    ),
                    amendment=uncertain,
                )
            )

        except Exception as exc:
            uncertain = (
                mark_order_amendment(
                    normalized_amend_id,
                    status="uncertain",
                    response={
                        "phase":
                            "gate_amend",
                        "exception_type":
                            type(exc).__name__,
                    },
                    error=str(exc),
                    write_performed=True,
                    completed=False,
                )
            )

            return await (
                _reconcile_after_amend_write(
                    client=client,
                    source=source,
                    amend_request_id=(
                        normalized_amend_id
                    ),
                    amendment=uncertain,
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

        response_mismatches = (
            _source_matches_gate(
                source=source,
                data=data,
            )
        )

        response_price = _decimal(
            (
                data or {}
            ).get("price")
        )

        if (
            response.status_code < 200
            or response.status_code >= 300
            or response_mismatches
            or response_price != price
        ):
            uncertain = (
                mark_order_amendment(
                    normalized_amend_id,
                    status="uncertain",
                    response={
                        "phase":
                            "gate_amend_response",
                        "response_status":
                            response.status_code,
                        "gate_response":
                            data,
                        "mismatches":
                            response_mismatches,
                    },
                    error=(
                        "Gate amendment response "
                        "could not be accepted "
                        "as definitive"
                    ),
                    gate_status_code=(
                        response.status_code
                    ),
                    write_performed=True,
                    completed=False,
                )
            )

            return await (
                _reconcile_after_amend_write(
                    client=client,
                    source=source,
                    amend_request_id=(
                        normalized_amend_id
                    ),
                    amendment=uncertain,
                )
            )

        updated = (
            mark_order_amendment(
                normalized_amend_id,
                status="amended",
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
            status="amended",
            order_request_id=(
                normalized_order_id
            ),
            amend_request_id=(
                normalized_amend_id
            ),
            gate_write_performed=True,
            definitive=True,
            amendment=updated,
            gate_order=data,
            previous_price=(
                _decimal_text(
                    current_price
                )
            ),
            requested_price=(
                _decimal_text(
                    price
                )
            ),
        )


async def reconcile_limit_order_amendment(
    *,
    settings: Settings,
    username: str,
    allowed_account_ids: set[str],
    order_request_id: str,
    amend_request_id: str,
) -> dict[str, Any]:
    """
    Explicit manual reconciliation of one unresolved
    Spot price amendment.

    This recovery operation is intentionally available
    even when the live amendment arm is disabled.

    Safety invariants:
    - source order exists in our Trading audit;
    - Gate account authorization is explicit;
    - amendment identity is explicit and correlated;
    - the amendment must already have crossed the
      ambiguous write boundary;
    - completed amendments are never re-reconciled;
    - Gate access is GET-only;
    - no amendment PATCH can originate here;
    - local audit state may be updated from the GET.
    """
    if not username.strip():
        raise TradingOrderAmendDenied(
            code="invalid_user",
            message="Dashboard username is required",
            status_code=400,
        )

    normalized_order_id = (
        order_request_id.strip()
    )
    normalized_amend_id = (
        amend_request_id.strip()
    )

    if not normalized_order_id:
        raise TradingOrderAmendDenied(
            code="invalid_order_request_id",
            message=(
                "order_request_id is required"
            ),
            status_code=400,
        )

    if not normalized_amend_id:
        raise TradingOrderAmendDenied(
            code="invalid_amend_request_id",
            message=(
                "amend_request_id is required"
            ),
            status_code=400,
        )

    source = get_order_request(
        normalized_order_id
    )

    if source is None:
        raise TradingOrderAmendDenied(
            code="order_not_found",
            message=(
                "Trading order request not found"
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
        raise TradingOrderAmendDenied(
            code="order_not_found",
            message=(
                "Trading order request not found"
            ),
            status_code=404,
        )

    amendment = get_order_amendment(
        normalized_amend_id
    )

    if (
        amendment is None
        or str(
            amendment.get(
                "order_request_id"
            )
            or ""
        ).strip()
        != normalized_order_id
    ):
        # Do not expose amendment IDs belonging
        # to another source order.
        raise TradingOrderAmendDenied(
            code="amendment_not_found",
            message=(
                "Trading amendment not found"
            ),
            status_code=404,
        )

    source_pair = str(
        source.get("pair")
        or ""
    ).strip().upper()

    source_gate_order_id = str(
        source.get("gate_order_id")
        or ""
    ).strip()

    identity_matches = (
        str(
            amendment.get("account_id")
            or ""
        ).strip().lower()
        == account_id
        and str(
            amendment.get("pair")
            or ""
        ).strip().upper()
        == source_pair
        and str(
            amendment.get(
                "gate_order_id"
            )
            or ""
        ).strip()
        == source_gate_order_id
    )

    if not identity_matches:
        raise TradingOrderAmendDenied(
            code="amendment_identity_mismatch",
            message=(
                "Amendment identity does not "
                "match its source order"
            ),
            status_code=409,
        )

    if amendment.get("completed_at"):
        raise TradingOrderAmendDenied(
            code="amendment_already_definitive",
            message=(
                "Amendment already has a "
                "definitive outcome"
            ),
            status_code=409,
        )

    # IMPORTANT:
    # This flag was persisted before PATCH.
    # Therefore True means that a crash or network
    # ambiguity may have happened after crossing
    # the write boundary. It does NOT assert that
    # Gate definitely applied the PATCH.
    if (
        amendment.get("write_performed")
        is not True
    ):
        raise TradingOrderAmendDenied(
            code="amendment_not_write_ambiguous",
            message=(
                "Amendment did not cross the "
                "ambiguous Gate write boundary"
            ),
            status_code=409,
        )

    status = str(
        amendment.get("status")
        or ""
    ).strip().lower()

    if status not in {
        "amending",
        "uncertain",
        "attention",
    }:
        raise TradingOrderAmendDenied(
            code="amendment_not_reconcilable",
            message=(
                "Amendment is not in a "
                "manually reconcilable state"
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
        raise TradingOrderAmendDenied(
            code="trading_config_error",
            message=str(exc),
            status_code=503,
        ) from exc

    if (
        trading_account is None
        or not trading_account.enabled
        or not trading_account.configured
    ):
        raise TradingOrderAmendDenied(
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

    # Deliberately no check of
    # settings.trading_order_amends_enabled here.
    #
    # Recovery of a historical ambiguous write must
    # remain possible while new PATCH writes are
    # globally disarmed.
    async with GateClient(
        settings,
        trading_account,
    ) as client:
        result = await (
            _reconcile_after_amend_write(
                client=client,
                source=source,
                amend_request_id=(
                    normalized_amend_id
                ),
                amendment=amendment,
            )
        )

    # _reconcile_after_amend_write() describes the
    # historical amendment as having crossed its
    # write boundary. For this manual invocation,
    # however, Gate was queried read-only.
    result = dict(result)

    result["gate_read_performed"] = True
    result["gate_write_performed"] = False
    result["write_performed"] = False
    result["manual_reconciliation"] = True
    result[
        "historical_amend_write_performed"
    ] = True

    return result
