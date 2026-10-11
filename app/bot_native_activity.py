from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class NativeBotActivityError(ValueError):
    """
    Raised when a captured/native Gate bot activity response
    does not match the accepted read-only structure.
    """


def _text(value: Any) -> str:
    return str(
        value
        if value is not None
        else ""
    ).strip()


def _optional_id(value: Any) -> str | None:
    normalized = _text(value)

    if normalized in {
        "",
        "0",
    }:
        return None

    return normalized


def _optional_int(value: Any) -> int | None:
    if value in {
        None,
        "",
    }:
        return None

    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise NativeBotActivityError(
            f"Invalid integer value: {value!r}"
        ) from exc


def _business_data(
    payload: Any,
) -> Any:
    if not isinstance(
        payload,
        dict,
    ):
        raise NativeBotActivityError(
            "Native Gate response must be an object"
        )

    code = payload.get(
        "code"
    )

    if (
        code is not None
        and _text(code)
        not in {
            "0",
            "200",
        }
    ):
        raise NativeBotActivityError(
            "Native Gate response returned "
            f"business code {code!r}"
        )

    if "data" not in payload:
        raise NativeBotActivityError(
            "Native Gate response is missing data"
        )

    return payload.get(
        "data"
    )


def _positive_decimal(
    value: Any,
) -> bool:
    normalized = _text(value)

    if not normalized:
        return False

    try:
        parsed = Decimal(
            normalized
        )
    except (
        InvalidOperation,
        ValueError,
    ):
        return False

    return (
        parsed.is_finite()
        and parsed > 0
    )


def _normalize_row(
    row: Any,
    *,
    expected_strategy_id: str,
    book_side: str | None = None,
) -> dict[str, Any]:
    if not isinstance(
        row,
        dict,
    ):
        raise NativeBotActivityError(
            "Native Gate activity row must be an object"
        )

    strategy_id = _text(
        row.get(
            "strategy_id"
        )
    )

    if not strategy_id:
        raise NativeBotActivityError(
            "Native Gate activity row is missing strategy_id"
        )

    if (
        strategy_id
        != expected_strategy_id
    ):
        raise NativeBotActivityError(
            "Native Gate activity strategy mismatch: "
            f"expected {expected_strategy_id}, "
            f"received {strategy_id}"
        )

    side = _text(
        row.get(
            "side"
        )
    ).lower()

    if side not in {
        "buy",
        "sell",
    }:
        raise NativeBotActivityError(
            f"Invalid native order side: {side!r}"
        )

    if (
        book_side == "ask"
        and side != "sell"
    ):
        raise NativeBotActivityError(
            "Native ask row is not a sell order"
        )

    if (
        book_side == "bid"
        and side != "buy"
    ):
        raise NativeBotActivityError(
            "Native bid row is not a buy order"
        )

    status = _text(
        row.get(
            "status"
        )
    ).lower()

    positive_order_id = (
        _optional_id(
            row.get(
                "positive_order_id"
            )
        )
    )

    profit = _text(
        row.get(
            "profit"
        )
    )

    normalized = {
        "native_id": _optional_id(
            row.get(
                "id"
            )
        ),
        "order_id": _optional_id(
            row.get(
                "order_id"
            )
        ),
        "strategy_id": strategy_id,
        "positive_order_id": (
            positive_order_id
        ),
        "linked_order_id": (
            positive_order_id
        ),
        "me_order_id": _optional_id(
            row.get(
                "me_order_id"
            )
        ),
        "side": side,
        "price": _text(
            row.get(
                "price"
            )
        ),
        "quantity": _text(
            row.get(
                "qty"
            )
        ),
        "match_price": _text(
            row.get(
                "match_price"
            )
        ),
        "match_quantity": _text(
            row.get(
                "match_qty"
            )
        ),
        "match_amount": _text(
            row.get(
                "match_amount"
            )
        ),
        "fee": _text(
            row.get(
                "fee"
            )
        ),
        "profit": profit,
        "profit_positive": (
            _positive_decimal(
                profit
            )
        ),
        "status": status,
        "finish_as": _text(
            row.get(
                "finish_as"
            )
        ).lower(),
        "order_index": _optional_int(
            row.get(
                "order_index"
            )
        ),
        "order_type": _text(
            row.get(
                "order_type"
            )
        ),
        "create_time": _optional_int(
            row.get(
                "create_time"
            )
        ),
        "finish_time": _optional_int(
            row.get(
                "finish_time"
            )
        ),
        "gt_fee": _text(
            row.get(
                "gt_fee"
            )
        ),
        "point_fee": _text(
            row.get(
                "point_fee"
            )
        ),
        "market": _text(
            row.get(
                "market"
            )
        ).upper(),
        "vip": _optional_int(
            row.get(
                "vip"
            )
        ),
        "vip_fee_discount": _text(
            row.get(
                "vip_fee_discount"
            )
        ),
        "book_side": book_side,
        # Keep a shallow copy so future Gate-only fields are
        # not destroyed by normalization.
        "raw": dict(
            row
        ),
    }

    return normalized


def normalize_native_open_orders(
    payload: Any,
    *,
    strategy_id: str,
) -> dict[str, Any]:
    """
    Normalize Gate's captured native bot open-order shape.

    Accepted captured structure:

      {
        "code": 200,
        "data": {
          "ask": [...],
          "bid": [...],
          "total_qty": "...",
          "total_match_qty": "..."
        }
      }

    Rows remain attributable to the exact strategy_id.
    """

    expected_strategy_id = (
        strategy_id.strip()
    )

    if not expected_strategy_id:
        raise NativeBotActivityError(
            "strategy_id cannot be empty"
        )

    data = _business_data(
        payload
    )

    if not isinstance(
        data,
        dict,
    ):
        raise NativeBotActivityError(
            "Native open-order data must be an object"
        )

    result_by_side: dict[
        str,
        list[dict[str, Any]],
    ] = {
        "ask": [],
        "bid": [],
    }

    for book_side in (
        "ask",
        "bid",
    ):
        rows = data.get(
            book_side,
            [],
        )

        if rows is None:
            rows = []

        if not isinstance(
            rows,
            list,
        ):
            raise NativeBotActivityError(
                "Native open-order "
                f"{book_side} must be a list"
            )

        result_by_side[
            book_side
        ] = [
            _normalize_row(
                row,
                expected_strategy_id=(
                    expected_strategy_id
                ),
                book_side=book_side,
            )
            for row in rows
        ]

    asks = result_by_side[
        "ask"
    ]

    bids = result_by_side[
        "bid"
    ]

    items = [
        *asks,
        *bids,
    ]

    return {
        "strategy_id": (
            expected_strategy_id
        ),
        "asks": asks,
        "bids": bids,
        "items": items,
        "gate_total_qty": _text(
            data.get(
                "total_qty"
            )
        ),
        "gate_total_match_qty": _text(
            data.get(
                "total_match_qty"
            )
        ),
        "summary": {
            "open_count": len(
                items
            ),
            "ask_count": len(
                asks
            ),
            "bid_count": len(
                bids
            ),
            "sell_count": sum(
                1
                for item in items
                if item[
                    "side"
                ] == "sell"
            ),
            "buy_count": sum(
                1
                for item in items
                if item[
                    "side"
                ] == "buy"
            ),
        },
    }


def normalize_native_trades(
    payload: Any,
    *,
    strategy_id: str,
) -> dict[str, Any]:
    """
    Normalize Gate's captured native bot trade/order-record shape.

    Gate-provided profit is preserved exactly. No dashboard
    profit calculation is performed here.
    """

    expected_strategy_id = (
        strategy_id.strip()
    )

    if not expected_strategy_id:
        raise NativeBotActivityError(
            "strategy_id cannot be empty"
        )

    data = _business_data(
        payload
    )

    if data is None:
        data = []

    if not isinstance(
        data,
        list,
    ):
        raise NativeBotActivityError(
            "Native trade data must be a list"
        )

    items = [
        _normalize_row(
            row,
            expected_strategy_id=(
                expected_strategy_id
            ),
        )
        for row in data
    ]

    page = _optional_int(
        payload.get(
            "page"
        )
    )

    page_size = _optional_int(
        payload.get(
            "pagesize"
        )
    )

    page_count = _optional_int(
        payload.get(
            "pagecount"
        )
    )

    total_count = _optional_int(
        payload.get(
            "totalcount"
        )
    )

    return {
        "strategy_id": (
            expected_strategy_id
        ),
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
            "total_count": total_count,
        },
        "summary": {
            "returned_count": len(
                items
            ),
            "gate_total_count": (
                total_count
            ),
            "sell_count": sum(
                1
                for item in items
                if item[
                    "side"
                ] == "sell"
            ),
            "buy_count": sum(
                1
                for item in items
                if item[
                    "side"
                ] == "buy"
            ),
            "positive_profit_count": sum(
                1
                for item in items
                if item[
                    "profit_positive"
                ]
            ),
        },
    }


def normalize_native_activity(
    *,
    strategy_id: str,
    open_orders_payload: Any,
    trades_payload: Any,
) -> dict[str, Any]:
    """
    Build one read-only normalized Bot Detail activity model.

    Transport is intentionally outside this module.
    """

    normalized_strategy_id = (
        strategy_id.strip()
    )

    return {
        "strategy_id": (
            normalized_strategy_id
        ),
        "open_orders": (
            normalize_native_open_orders(
                open_orders_payload,
                strategy_id=(
                    normalized_strategy_id
                ),
            )
        ),
        "trades": (
            normalize_native_trades(
                trades_payload,
                strategy_id=(
                    normalized_strategy_id
                ),
            )
        ),
    }
