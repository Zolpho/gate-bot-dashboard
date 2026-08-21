from __future__ import annotations

import asyncio
import re
import time
from decimal import (
    Decimal,
    InvalidOperation,
)
from typing import Any

from .accounts import (
    AccountConfigError,
    get_gate_account,
)
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
    TradingOrderIdempotencyConflict,
    mark_order_request,
    reserve_limit_order,
)
from .trading_order_locks import (
    TradingOrderLocked,
    acquire_trading_lock,
    release_trading_lock,
)
from .trading_order_reconcile import (
    reconcile_spot_order_request,
)
from .trading_rate_limit import (
    TradingRateLimitExceeded,
    enforce_trading_rate_limit,
)


_PAIR_RE = re.compile(
    r"^[A-Z0-9]+_[A-Z0-9]+$"
)

_AMBIGUOUS_HTTP_STATUS_CODES = {
    408,
    409,
    425,
    429,
}


class TradingExecutionDenied(
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


class TradingPreflightError(
    RuntimeError
):
    pass


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


def _int_or_none(
    value: Any,
) -> int | None:
    try:
        result = int(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if result < 0:
        return None

    return result


def _decimal_places(
    value: Decimal,
) -> int:
    normalized = value.normalize()
    exponent = (
        normalized
        .as_tuple()
        .exponent
    )

    if exponent >= 0:
        return 0

    return -exponent


def _market(
    value: str,
) -> str:
    normalized = (
        value.strip().upper()
    )

    if not _PAIR_RE.fullmatch(
        normalized
    ):
        raise TradingExecutionDenied(
            code="invalid_pair",
            message=(
                "Invalid Gate Spot "
                "currency pair"
            ),
            status_code=400,
        )

    return normalized


def _normalized_side(
    value: str,
) -> str:
    normalized = (
        value.strip().lower()
    )

    if normalized not in {
        "buy",
        "sell",
    }:
        raise TradingExecutionDenied(
            code="invalid_side",
            message=(
                "Spot order side must "
                "be buy or sell"
            ),
            status_code=400,
        )

    return normalized


def _normalized_tif(
    value: str,
) -> str:
    normalized = (
        value.strip().lower()
    )

    if normalized not in {
        "gtc",
        "poc",
    }:
        raise TradingExecutionDenied(
            code="invalid_time_in_force",
            message=(
                "Only gtc and poc "
                "are supported"
            ),
            status_code=400,
        )

    return normalized


def funding_asset_for_order(
    *,
    pair: str,
    side: str,
) -> str:
    market = _market(
        pair
    )

    normalized_side = (
        _normalized_side(
            side
        )
    )

    base, quote = market.split(
        "_",
        1,
    )

    if normalized_side == "buy":
        return quote

    return base


def _available_balance(
    rows: Any,
    currency: str,
) -> Decimal:
    if not isinstance(
        rows,
        list,
    ):
        return Decimal("0")

    for row in rows:
        if not isinstance(
            row,
            dict,
        ):
            continue

        if str(
            row.get("currency")
            or ""
        ).upper() != currency:
            continue

        return (
            _decimal(
                row.get(
                    "available"
                )
            )
            or Decimal("0")
        )

    return Decimal("0")


def _book_prices(
    payload: Any,
) -> tuple[
    Decimal | None,
    Decimal | None,
]:
    if not isinstance(
        payload,
        dict,
    ):
        return (
            None,
            None,
        )

    ask_prices: list[
        Decimal
    ] = []

    bid_prices: list[
        Decimal
    ] = []

    for row in (
        payload.get("asks")
        or []
    ):
        if (
            not isinstance(
                row,
                (list, tuple),
            )
            or not row
        ):
            continue

        value = _decimal(
            row[0]
        )

        if (
            value is not None
            and value > 0
        ):
            ask_prices.append(
                value
            )

    for row in (
        payload.get("bids")
        or []
    ):
        if (
            not isinstance(
                row,
                (list, tuple),
            )
            or not row
        ):
            continue

        value = _decimal(
            row[0]
        )

        if (
            value is not None
            and value > 0
        ):
            bid_prices.append(
                value
            )

    best_ask = (
        min(ask_prices)
        if ask_prices
        else None
    )

    best_bid = (
        max(bid_prices)
        if bid_prices
        else None
    )

    return (
        best_bid,
        best_ask,
    )


def _limit_order_checks(
    *,
    side: str,
    time_in_force: str,
    price: Decimal,
    amount: Decimal,
    trade_status: str,
    price_precision: int | None,
    amount_precision: int | None,
    min_base_amount: Decimal | None,
    min_quote_amount: Decimal | None,
    base_available: Decimal,
    quote_available: Decimal,
    best_bid: Decimal | None,
    best_ask: Decimal | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    normalized_status = (
        trade_status
        .strip()
        .lower()
    )

    side_allowed = (
        normalized_status
        == "tradable"
        or (
            normalized_status
            == "buyable"
            and side == "buy"
        )
        or (
            normalized_status
            == "sellable"
            and side == "sell"
        )
    )

    if not side_allowed:
        blockers.append(
            "Gate does not currently "
            "allow this side for the "
            "pair "
            "(trade_status="
            f"{normalized_status or 'unknown'})."
        )

    if price_precision is None:
        blockers.append(
            "Gate pair price precision "
            "is unavailable."
        )

    elif (
        _decimal_places(
            price
        )
        > price_precision
    ):
        blockers.append(
            "Price exceeds Gate pair "
            "precision "
            f"({price_precision} "
            "decimal places)."
        )

    if amount_precision is None:
        blockers.append(
            "Gate pair amount precision "
            "is unavailable."
        )

    elif (
        _decimal_places(
            amount
        )
        > amount_precision
    ):
        blockers.append(
            "Amount exceeds Gate pair "
            "precision "
            f"({amount_precision} "
            "decimal places)."
        )

    total = (
        price * amount
    )

    if (
        min_base_amount
        is not None
        and min_base_amount > 0
        and amount
        < min_base_amount
    ):
        blockers.append(
            "Amount is below Gate "
            "minimum base amount "
            f"({_decimal_text(min_base_amount)})."
        )

    if (
        min_quote_amount
        is not None
        and min_quote_amount > 0
        and total
        < min_quote_amount
    ):
        blockers.append(
            "Order total is below Gate "
            "minimum quote amount "
            f"({_decimal_text(min_quote_amount)})."
        )

    if side == "buy":
        required_currency = (
            "quote"
        )

        available = (
            quote_available
        )

        required = total

        marketable = (
            best_ask is not None
            and price >= best_ask
        )

    else:
        required_currency = (
            "base"
        )

        available = (
            base_available
        )

        required = amount

        marketable = (
            best_bid is not None
            and price <= best_bid
        )

    remaining = (
        available - required
    )

    if required > available:
        blockers.append(
            "Insufficient available "
            "spot balance."
        )

    if marketable:
        if (
            time_in_force
            == "poc"
        ):
            blockers.append(
                "Post-only order would "
                "currently cross the "
                "order book."
            )

        else:
            warnings.append(
                "This limit order is "
                "currently marketable "
                "and may execute "
                "immediately."
            )

    warnings.append(
        "Estimated total does not "
        "include trading fees."
    )

    return {
        "blockers": blockers,
        "warnings": warnings,
        "total": total,
        "required_currency": (
            required_currency
        ),
        "available": available,
        "required": required,
        "remaining": remaining,
        "marketable": marketable,
    }


async def fresh_limit_order_preflight(
    *,
    settings: Settings,
    account_id: str,
    pair: str,
    side: str,
    price: Decimal,
    amount: Decimal,
    time_in_force: str,
) -> dict[str, Any]:
    """
    Perform a fresh, read-only preflight using
    the Monitor credential for account_id.

    This function performs only Gate GETs.
    """
    market = _market(
        pair
    )

    normalized_side = (
        _normalized_side(
            side
        )
    )

    normalized_tif = (
        _normalized_tif(
            time_in_force
        )
    )

    if (
        not price.is_finite()
        or price <= 0
    ):
        raise TradingExecutionDenied(
            code="invalid_price",
            message=(
                "Price must be a "
                "positive finite value"
            ),
            status_code=400,
        )

    if (
        not amount.is_finite()
        or amount <= 0
    ):
        raise TradingExecutionDenied(
            code="invalid_amount",
            message=(
                "Amount must be a "
                "positive finite value"
            ),
            status_code=400,
        )

    try:
        monitor_account = (
            get_gate_account(
                account_id
            )
        )

    except AccountConfigError as exc:
        raise TradingPreflightError(
            str(exc)
        ) from exc

    if (
        monitor_account is None
        or not monitor_account.enabled
        or not monitor_account.configured
    ):
        raise TradingPreflightError(
            "Monitor credentials are "
            "not configured for Gate "
            f"account {account_id}"
        )

    async with GateClient(
        settings,
        monitor_account,
    ) as client:
        (
            pair_response,
            balance_response,
            book_response,
        ) = await asyncio.gather(
            client.get_spot_currency_pair(
                market
            ),
            client.list_spot_accounts(),
            client.get_spot_order_book(
                market,
                interval="0",
                limit=20,
                with_id=True,
            ),
        )

    pair_data = (
        pair_response.data
        if isinstance(
            pair_response.data,
            dict,
        )
        else {}
    )

    if not pair_data:
        raise TradingPreflightError(
            "Gate did not return Spot "
            "pair metadata"
        )

    base = str(
        pair_data.get("base")
        or market.split(
            "_",
            1,
        )[0]
    ).upper()

    quote = str(
        pair_data.get("quote")
        or market.split(
            "_",
            1,
        )[1]
    ).upper()

    balances = (
        balance_response.data
    )

    base_available = (
        _available_balance(
            balances,
            base,
        )
    )

    quote_available = (
        _available_balance(
            balances,
            quote,
        )
    )

    (
        best_bid,
        best_ask,
    ) = _book_prices(
        book_response.data
    )

    min_base_amount = _decimal(
        pair_data.get(
            "min_base_amount"
        )
    )

    min_quote_amount = _decimal(
        pair_data.get(
            "min_quote_amount"
        )
    )

    checks = (
        _limit_order_checks(
            side=normalized_side,
            time_in_force=(
                normalized_tif
            ),
            price=price,
            amount=amount,
            trade_status=str(
                pair_data.get(
                    "trade_status"
                )
                or ""
            ),
            price_precision=(
                _int_or_none(
                    pair_data.get(
                        "precision"
                    )
                )
            ),
            amount_precision=(
                _int_or_none(
                    pair_data.get(
                        "amount_precision"
                    )
                )
            ),
            min_base_amount=(
                min_base_amount
            ),
            min_quote_amount=(
                min_quote_amount
            ),
            base_available=(
                base_available
            ),
            quote_available=(
                quote_available
            ),
            best_bid=best_bid,
            best_ask=best_ask,
        )
    )

    funding_asset = (
        quote
        if checks[
            "required_currency"
        ]
        == "quote"
        else base
    )

    return {
        "status": (
            "ready"
            if not checks[
                "blockers"
            ]
            else "invalid"
        ),
        "account_id": (
            account_id
            .strip()
            .lower()
        ),
        "pair": market,
        "base": base,
        "quote": quote,
        "funding_asset": (
            funding_asset
        ),
        "side": normalized_side,
        "time_in_force": (
            normalized_tif
        ),
        "price": (
            _decimal_text(
                price
            )
        ),
        "amount": (
            _decimal_text(
                amount
            )
        ),
        "total": (
            _decimal_text(
                checks["total"]
            )
        ),
        "available": (
            _decimal_text(
                checks[
                    "available"
                ]
            )
        ),
        "required": (
            _decimal_text(
                checks[
                    "required"
                ]
            )
        ),
        "remaining": (
            _decimal_text(
                checks[
                    "remaining"
                ]
            )
        ),
        "best_bid": (
            _decimal_text(
                best_bid
            )
            if best_bid is not None
            else None
        ),
        "best_ask": (
            _decimal_text(
                best_ask
            )
            if best_ask is not None
            else None
        ),
        "marketable": (
            checks[
                "marketable"
            ]
        ),
        "blockers": list(
            checks["blockers"]
        ),
        "warnings": list(
            checks["warnings"]
        ),
        "gate_payload": {
            "currency_pair": market,
            "type": "limit",
            "account": "spot",
            "side": (
                normalized_side
            ),
            "amount": (
                _decimal_text(
                    amount
                )
            ),
            "price": (
                _decimal_text(
                    price
                )
            ),
            "time_in_force": (
                normalized_tif
            ),
        },
    }


def _definitive_gate_rejection(
    exc: GateAPIError,
) -> bool:
    status = exc.status_code

    if status is None:
        return False

    if (
        status
        in _AMBIGUOUS_HTTP_STATUS_CODES
    ):
        return False

    return (
        400
        <= status
        < 500
    )


def _response_mismatches(
    *,
    data: Any,
    payload: dict[str, Any],
) -> tuple[
    str,
    list[str],
]:
    if not isinstance(
        data,
        dict,
    ):
        return (
            "",
            [
                "response_shape",
            ],
        )

    order_id = str(
        data.get("id")
        or ""
    )

    mismatches: list[str] = []

    if not order_id:
        mismatches.append(
            "order_id"
        )

    comparable = {
        "text": (
            payload["text"]
        ),
        "currency_pair": (
            payload[
                "currency_pair"
            ]
        ),
        "type": "limit",
        "account": "spot",
        "side": payload["side"],
        "amount": (
            payload["amount"]
        ),
        "price": payload["price"],
        "time_in_force": (
            payload[
                "time_in_force"
            ]
        ),
    }

    decimal_fields = {
        "amount",
        "price",
    }

    for key, expected in (
        comparable.items()
    ):
        actual = data.get(
            key
        )

        # Gate FULL responses normally contain
        # these fields. We tolerate a missing
        # non-ID field so a reduced successful
        # response can still be reconciled by ID.
        if actual in (
            None,
            "",
        ):
            continue

        if key in decimal_fields:
            if (
                _decimal(actual)
                != _decimal(expected)
            ):
                mismatches.append(
                    key
                )

        elif str(
            actual
        ).lower() != str(
            expected
        ).lower():
            mismatches.append(
                key
            )

    return (
        order_id,
        mismatches,
    )


def _bounded_exptime_ms(
    settings: Settings,
) -> int:
    return max(
        1000,
        min(
            int(
                settings
                .trading_order_exptime_ms
            ),
            30000,
        ),
    )


def _base_result(
    *,
    status: str,
    request_id: str,
    gate_write_performed: bool,
    audit: dict[str, Any],
    lock_released: bool = False,
    manual_review_required: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "status": status,
        "request_id": request_id,
        "gate_write_performed": (
            gate_write_performed
        ),
        "write_performed": (
            gate_write_performed
        ),
        "lock_released": (
            lock_released
        ),
        "manual_review_required": (
            manual_review_required
        ),
        "audit": audit,
    }

    result.update(
        extra
    )

    return result


async def _reconcile_ambiguous(
    *,
    client: GateClient,
    request_id: str,
    audit: dict[str, Any],
) -> dict[str, Any]:
    try:
        reconciled = (
            await reconcile_spot_order_request(
                client=client,
                request_id=(
                    request_id
                ),
            )
        )

    except Exception as exc:
        return _base_result(
            status="uncertain",
            request_id=request_id,
            gate_write_performed=True,
            audit=audit,
            lock_released=False,
            manual_review_required=True,
            reconciliation_error=(
                str(exc)
            ),
        )

    return _base_result(
        status=str(
            reconciled.get(
                "status"
            )
            or "uncertain"
        ),
        request_id=request_id,
        gate_write_performed=True,
        audit=(
            reconciled.get(
                "audit"
            )
            or audit
        ),
        lock_released=bool(
            reconciled.get(
                "lock_released"
            )
        ),
        manual_review_required=bool(
            reconciled.get(
                "manual_review_required"
            )
        ),
        reconciliation=(
            reconciled
        ),
    )


async def execute_limit_order(
    *,
    settings: Settings,
    username: str,
    allowed_account_ids: set[str],
    request_id: str,
    account_id: str,
    pair: str,
    side: str,
    price: Decimal,
    amount: Decimal,
    time_in_force: str,
    confirmation: str,
) -> dict[str, Any]:
    """
    Execute one reviewed Gate Spot limit order.

    Safety invariants:
    - explicit dashboard account assignment;
    - independent Trading live arm;
    - exact confirmation;
    - isolated Trading credential;
    - persistent idempotency;
    - persistent rate limit;
    - fresh Monitor-credential preflight;
    - account + funding-asset lock;
    - audit write boundary before POST;
    - exactly one POST attempt;
    - no automatic POST retry;
    - ambiguous results are reconciled
      using reads only.
    """
    normalized_username = (
        username.strip()
    )

    if not normalized_username:
        raise TradingExecutionDenied(
            code="invalid_user",
            message=(
                "Dashboard username "
                "is required"
            ),
            status_code=400,
        )

    normalized_request_id = (
        request_id.strip()
    )

    if not normalized_request_id:
        raise TradingExecutionDenied(
            code="invalid_request_id",
            message=(
                "request_id is required"
            ),
            status_code=400,
        )

    normalized_account = (
        account_id
        .strip()
        .lower()
    )

    allowed = {
        value.strip().lower()
        for value
        in allowed_account_ids
        if value.strip()
    }

    if normalized_account not in (
        allowed
    ):
        raise TradingExecutionDenied(
            code="account_not_assigned",
            message=(
                "Trading is limited to "
                "Gate accounts explicitly "
                "assigned to this "
                "dashboard user"
            ),
            status_code=403,
        )

    market = _market(
        pair
    )

    normalized_side = (
        _normalized_side(
            side
        )
    )

    normalized_tif = (
        _normalized_tif(
            time_in_force
        )
    )

    if (
        not price.is_finite()
        or price <= 0
    ):
        raise TradingExecutionDenied(
            code="invalid_price",
            message=(
                "Price must be a "
                "positive finite value"
            ),
            status_code=400,
        )

    if (
        not amount.is_finite()
        or amount <= 0
    ):
        raise TradingExecutionDenied(
            code="invalid_amount",
            message=(
                "Amount must be a "
                "positive finite value"
            ),
            status_code=400,
        )

    # Important: disabled means no audit row,
    # no Gate read and certainly no Gate write.
    if not (
        settings
        .trading_limit_orders_enabled
    ):
        raise TradingExecutionDenied(
            code="trading_disabled",
            message=(
                "Live Spot limit-order "
                "execution is disabled"
            ),
            status_code=503,
        )

    if confirmation != (
        settings
        .trading_limit_order_confirmation_text
    ):
        raise TradingExecutionDenied(
            code="confirmation_mismatch",
            message=(
                "Exact live-order "
                "confirmation text "
                "is required"
            ),
            status_code=400,
        )

    try:
        trading_account = (
            get_trading_account(
                normalized_account
            )
        )

    except TradingConfigError as exc:
        raise TradingExecutionDenied(
            code="trading_config_error",
            message=str(exc),
            status_code=503,
        ) from exc

    if (
        trading_account is None
        or not trading_account.enabled
        or not trading_account.configured
    ):
        raise TradingExecutionDenied(
            code=(
                "trading_credentials_missing"
            ),
            message=(
                "Isolated Spot Trading "
                "credentials are not "
                "configured for Gate "
                f"account {normalized_account}"
            ),
            status_code=503,
        )

    funding_asset = (
        funding_asset_for_order(
            pair=market,
            side=(
                normalized_side
            ),
        )
    )

    try:
        (
            audit,
            created,
        ) = reserve_limit_order(
            request_id=(
                normalized_request_id
            ),
            account_id=(
                normalized_account
            ),
            username=(
                normalized_username
            ),
            pair=market,
            side=normalized_side,
            price=price,
            amount=amount,
            time_in_force=(
                normalized_tif
            ),
            funding_asset=(
                funding_asset
            ),
        )

    except (
        TradingOrderIdempotencyConflict
    ) as exc:
        raise TradingExecutionDenied(
            code=(
                "idempotency_conflict"
            ),
            message=str(exc),
            status_code=409,
        ) from exc

    # Any existing request ID is replay-safe.
    # Never resume into another POST.
    if not created:
        return _base_result(
            status=(
                "idempotent_replay"
            ),
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=audit,
            lock_released=False,
            manual_review_required=bool(
                audit.get(
                    "write_performed"
                )
                and audit.get(
                    "status"
                )
                in {
                    "submitting",
                    "uncertain",
                    "attention",
                }
            ),
            original_status=(
                audit.get("status")
            ),
            original_write_performed=(
                bool(
                    audit.get(
                        "write_performed"
                    )
                )
            ),
        )

    try:
        rate_limit = (
            enforce_trading_rate_limit(
                settings=settings,
                username=(
                    normalized_username
                ),
                account_id=(
                    normalized_account
                ),
            )
        )

    except (
        TradingRateLimitExceeded
    ) as exc:
        detail = exc.detail()

        updated = mark_order_request(
            normalized_request_id,
            status="rate_limited",
            response=detail,
            error=str(exc),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="rate_limited",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            rate_limit=detail,
        )

    try:
        preflight = (
            await fresh_limit_order_preflight(
                settings=settings,
                account_id=(
                    normalized_account
                ),
                pair=market,
                side=(
                    normalized_side
                ),
                price=price,
                amount=amount,
                time_in_force=(
                    normalized_tif
                ),
            )
        )

    except GateAPIError as exc:
        updated = mark_order_request(
            normalized_request_id,
            status="preflight_error",
            response={
                "phase": (
                    "fresh_monitor_preflight"
                ),
                "status_code": (
                    exc.status_code
                ),
                "label": (
                    exc.label
                ),
                "gate_response": (
                    exc.response
                ),
            },
            error=str(exc),
            gate_status_code=(
                exc.status_code
            ),
            gate_label=(
                exc.label
            ),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="preflight_error",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            rate_limit=rate_limit,
        )

    except TradingPreflightError as exc:
        updated = mark_order_request(
            normalized_request_id,
            status="preflight_error",
            response={
                "phase": (
                    "fresh_monitor_preflight"
                ),
                "message": str(exc),
            },
            error=str(exc),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="preflight_error",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            rate_limit=rate_limit,
        )

    if (
        preflight[
            "funding_asset"
        ]
        != funding_asset
    ):
        updated = mark_order_request(
            normalized_request_id,
            status="preflight_error",
            response={
                "phase": (
                    "funding_asset_validation"
                ),
                "expected": (
                    funding_asset
                ),
                "actual": (
                    preflight[
                        "funding_asset"
                    ]
                ),
            },
            error=(
                "Gate pair metadata produced "
                "an unexpected funding asset"
            ),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="preflight_error",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            rate_limit=rate_limit,
            preflight=preflight,
        )

    blockers = list(
        preflight.get(
            "blockers"
        )
        or []
    )

    if blockers:
        updated = mark_order_request(
            normalized_request_id,
            status="preflight_failed",
            response={
                "preflight": preflight,
            },
            error="; ".join(
                blockers
            ),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="preflight_failed",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            rate_limit=rate_limit,
            preflight=preflight,
        )

    try:
        lock = acquire_trading_lock(
            account_id=(
                normalized_account
            ),
            funding_asset=(
                funding_asset
            ),
            pair=market,
            side=normalized_side,
            owner_request_id=(
                normalized_request_id
            ),
            username=(
                normalized_username
            ),
        )

    except TradingOrderLocked as exc:
        updated = mark_order_request(
            normalized_request_id,
            status="lock_blocked",
            response={
                "blocking_lock": (
                    exc.lock
                ),
            },
            error=str(exc),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="lock_blocked",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            rate_limit=rate_limit,
            preflight=preflight,
            blocking_lock=(
                exc.lock
            ),
        )

    # Recheck the final safety gates after
    # lock acquisition and immediately before
    # the write boundary.
    if not (
        settings
        .trading_limit_orders_enabled
    ):
        released = (
            release_trading_lock(
                account_id=(
                    normalized_account
                ),
                funding_asset=(
                    funding_asset
                ),
                owner_request_id=(
                    normalized_request_id
                ),
            )
        )

        updated = mark_order_request(
            normalized_request_id,
            status="aborted",
            response={
                "reason": (
                    "Trading live arm "
                    "is disabled"
                ),
            },
            error=(
                "Trading live arm "
                "is disabled"
            ),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="aborted",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            lock_released=(
                released
            ),
            rate_limit=rate_limit,
            preflight=preflight,
        )

    try:
        final_trading_account = (
            get_trading_account(
                normalized_account
            )
        )

    except TradingConfigError:
        final_trading_account = None

    if (
        final_trading_account
        is None
        or not final_trading_account.enabled
        or not final_trading_account.configured
        or (
            final_trading_account
            .api_key
            != trading_account.api_key
        )
    ):
        released = (
            release_trading_lock(
                account_id=(
                    normalized_account
                ),
                funding_asset=(
                    funding_asset
                ),
                owner_request_id=(
                    normalized_request_id
                ),
            )
        )

        updated = mark_order_request(
            normalized_request_id,
            status="aborted",
            response={
                "reason": (
                    "Trading credential "
                    "changed or became "
                    "unavailable before "
                    "submission"
                ),
            },
            error=(
                "Trading credential "
                "changed or became "
                "unavailable"
            ),
            write_performed=False,
            completed=True,
        )

        return _base_result(
            status="aborted",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=False,
            audit=updated,
            lock_released=(
                released
            ),
            rate_limit=rate_limit,
            preflight=preflight,
        )

    payload = dict(
        preflight[
            "gate_payload"
        ]
    )

    payload["text"] = (
        audit["gate_text"]
    )

    expires_at_ms = (
        int(
            time.time_ns()
            // 1_000_000
        )
        + _bounded_exptime_ms(
            settings
        )
    )

    # Persist the write boundary BEFORE
    # invoking Gate. A crash after this line
    # therefore fails closed as uncertain.
    submitting = mark_order_request(
        normalized_request_id,
        status="submitting",
        response={
            "preflight": preflight,
            "gate_payload": payload,
            "expires_at_ms": (
                expires_at_ms
            ),
            "lock": lock,
        },
        write_performed=True,
        completed=False,
    )

    async with GateClient(
        settings,
        final_trading_account,
    ) as client:
        try:
            response = (
                await client
                .create_spot_order(
                    payload,
                    expires_at_ms=(
                        expires_at_ms
                    ),
                )
            )

        except ValueError as exc:
            # create_spot_order validation
            # happens before the HTTP call.
            released = (
                release_trading_lock(
                    account_id=(
                        normalized_account
                    ),
                    funding_asset=(
                        funding_asset
                    ),
                    owner_request_id=(
                        normalized_request_id
                    ),
                )
            )

            updated = (
                mark_order_request(
                    normalized_request_id,
                    status=(
                        "local_rejected"
                    ),
                    response={
                        "message": (
                            str(exc)
                        ),
                    },
                    error=str(exc),
                    write_performed=False,
                    completed=True,
                )
            )

            return _base_result(
                status=(
                    "local_rejected"
                ),
                request_id=(
                    normalized_request_id
                ),
                gate_write_performed=False,
                audit=updated,
                lock_released=(
                    released
                ),
                rate_limit=(
                    rate_limit
                ),
                preflight=(
                    preflight
                ),
            )

        except GateAPIError as exc:
            if (
                _definitive_gate_rejection(
                    exc
                )
            ):
                released = (
                    release_trading_lock(
                        account_id=(
                            normalized_account
                        ),
                        funding_asset=(
                            funding_asset
                        ),
                        owner_request_id=(
                            normalized_request_id
                        ),
                    )
                )

                updated = (
                    mark_order_request(
                        normalized_request_id,
                        status="rejected",
                        response={
                            "gate_response": (
                                exc.response
                            ),
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
                    request_id=(
                        normalized_request_id
                    ),
                    gate_write_performed=True,
                    audit=updated,
                    lock_released=(
                        released
                    ),
                    rate_limit=(
                        rate_limit
                    ),
                    preflight=(
                        preflight
                    ),
                    definitive_rejection=True,
                )

            uncertain = (
                mark_order_request(
                    normalized_request_id,
                    status="uncertain",
                    response={
                        "phase": (
                            "gate_submit"
                        ),
                        "gate_response": (
                            exc.response
                        ),
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
                _reconcile_ambiguous(
                    client=client,
                    request_id=(
                        normalized_request_id
                    ),
                    audit=uncertain,
                )
            )

        except Exception as exc:
            uncertain = (
                mark_order_request(
                    normalized_request_id,
                    status="uncertain",
                    response={
                        "phase": (
                            "gate_submit"
                        ),
                        "exception_type": (
                            type(exc)
                            .__name__
                        ),
                    },
                    error=str(exc),
                    write_performed=True,
                    completed=False,
                )
            )

            return await (
                _reconcile_ambiguous(
                    client=client,
                    request_id=(
                        normalized_request_id
                    ),
                    audit=uncertain,
                )
            )

        (
            gate_order_id,
            mismatches,
        ) = _response_mismatches(
            data=response.data,
            payload=payload,
        )

        if (
            response.status_code
            < 200
            or response.status_code
            >= 300
            or not gate_order_id
            or mismatches
        ):
            uncertain = (
                mark_order_request(
                    normalized_request_id,
                    status="uncertain",
                    response={
                        "phase": (
                            "gate_submit_response"
                        ),
                        "gate_response": (
                            response.data
                        ),
                        "response_status": (
                            response
                            .status_code
                        ),
                        "mismatches": (
                            mismatches
                        ),
                    },
                    error=(
                        "Gate Spot order "
                        "response could not "
                        "be accepted as "
                        "definitive"
                    ),
                    gate_order_id=(
                        gate_order_id
                    ),
                    gate_status_code=(
                        response
                        .status_code
                    ),
                    write_performed=True,
                    completed=False,
                )
            )

            return await (
                _reconcile_ambiguous(
                    client=client,
                    request_id=(
                        normalized_request_id
                    ),
                    audit=uncertain,
                )
            )

        released = (
            release_trading_lock(
                account_id=(
                    normalized_account
                ),
                funding_asset=(
                    funding_asset
                ),
                owner_request_id=(
                    normalized_request_id
                ),
            )
        )

        updated = mark_order_request(
            normalized_request_id,
            status="submitted",
            response={
                "gate_response": (
                    response.data
                ),
                "response_status": (
                    response.status_code
                ),
            },
            gate_order_id=(
                gate_order_id
            ),
            gate_status_code=(
                response.status_code
            ),
            write_performed=True,
            completed=True,
        )

        return _base_result(
            status="submitted",
            request_id=(
                normalized_request_id
            ),
            gate_write_performed=True,
            audit=updated,
            lock_released=(
                released
            ),
            rate_limit=(
                rate_limit
            ),
            preflight=preflight,
            gate_order_id=(
                gate_order_id
            ),
            gate_status=str(
                (
                    response.data
                    if isinstance(
                        response.data,
                        dict,
                    )
                    else {}
                ).get(
                    "status"
                )
                or ""
            ),
        )
