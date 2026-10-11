from __future__ import annotations

import copy

import pytest

from app.bot_native_activity import (
    NativeBotActivityError,
    normalize_native_activity,
    normalize_native_open_orders,
    normalize_native_trades,
)


STRATEGY_ID = "5453981"


# Exact representative objects transcribed from the
# previously captured real Gate Infinity Grid open-order JSON.
CAPTURED_OPEN_ORDERS = {
    "code": 200,
    "label": "",
    "message": "",
    "data": {
        "ask": [
            {
                "id": 1937571022,
                "order_id": 1938066916,
                "strategy_id": 5453981,
                "positive_order_id": 1938066617,
                "me_order_id": 1147245804409,
                "side": "sell",
                "price": "0.001869",
                "qty": "2121",
                "match_price": "0.000000",
                "match_qty": "0",
                "match_amount": "0",
                "fee": "0",
                "profit": "0",
                "status": "open",
                "order_index": 3,
                "order_type": "",
                "create_time": 1791678911,
                "gt_fee": "0",
                "point_fee": "0",
                "market": "EQTY_USDT",
                "vip": -1,
                "vip_fee_discount": "1",
            },
            {
                "id": 1931642655,
                "order_id": 1932131565,
                "strategy_id": 5453981,
                "positive_order_id": 0,
                "me_order_id": 1144458572272,
                "side": "sell",
                "price": "0.002000",
                "qty": "1848",
                "match_price": "0.000000",
                "match_qty": "0",
                "match_amount": "0",
                "fee": "0",
                "profit": "0",
                "status": "open",
                "order_index": 10,
                "order_type": "",
                "create_time": 1791257286,
                "gt_fee": "0",
                "point_fee": "0",
                "market": "EQTY_USDT",
                "vip": -1,
                "vip_fee_discount": "1",
            },
        ],
        "bid": [
            {
                "id": 1937502331,
                "order_id": 1937998121,
                "strategy_id": 5453981,
                "positive_order_id": 0,
                "me_order_id": 1147195439071,
                "side": "buy",
                "price": "0.001831",
                "qty": "2165",
                "match_price": "0.000000",
                "match_qty": "0",
                "match_amount": "0",
                "fee": "0",
                "profit": "0",
                "status": "open",
                "order_index": 1,
                "order_type": "",
                "create_time": 1791666711,
                "gt_fee": "0",
                "point_fee": "0",
                "market": "EQTY_USDT",
                "vip": -1,
                "vip_fee_discount": "1",
            },
            {
                "id": 1937473990,
                "order_id": 1937969747,
                "strategy_id": 5453981,
                "positive_order_id": 0,
                "me_order_id": 1147172013618,
                "side": "buy",
                "price": "0.001812",
                "qty": "2211",
                "match_price": "0.000000",
                "match_qty": "0",
                "match_amount": "0",
                "fee": "0",
                "profit": "0",
                "status": "open",
                "order_index": 0,
                "order_type": "",
                "create_time": 1791661084,
                "gt_fee": "0",
                "point_fee": "0",
                "market": "EQTY_USDT",
                "vip": -1,
                "vip_fee_discount": "1",
            },
        ],
        "total_qty": "0",
        "total_match_qty": "0",
    },
}


# Exact representative objects transcribed from the
# previously captured real Gate Infinity Grid order-record JSON.
CAPTURED_TRADES = {
    "code": 200,
    "label": "",
    "message": "",
    "page": 1,
    "pagesize": 30,
    "pagecount": 2,
    "totalcount": 34,
    "data": [
        {
            "id": 1936565292,
            "order_id": 1938066617,
            "strategy_id": 5453981,
            "positive_order_id": 0,
            "me_order_id": 1147245784713,
            "side": "buy",
            "price": "0.00185",
            "qty": "2121",
            "match_price": "0.00185",
            "match_qty": "2121",
            "match_amount": "3.92385",
            "fee": "2.07858",
            "profit": "0",
            "status": "finished",
            "finish_as": "filled",
            "order_index": 2,
            "order_type": "",
            "create_time": 1791678906,
            "finish_time": 1791678911,
            "gt_fee": "0",
            "point_fee": "0",
            "market": "EQTY_USDT",
            "vip": -1,
            "vip_fee_discount": "1",
        },
        {
            "id": 1936565072,
            "order_id": 1937810978,
            "strategy_id": 5453981,
            "positive_order_id": 1937734062,
            "me_order_id": 1147079562067,
            "side": "sell",
            "price": "0.001869",
            "qty": "2121",
            "match_price": "0.001869",
            "match_qty": "2121",
            "match_amount": "3.964149",
            "fee": "0.00388486602",
            "profit": "0.03641413398",
            "status": "finished",
            "finish_as": "filled",
            "order_index": 3,
            "order_type": "",
            "create_time": 1791642908,
            "finish_time": 1791678906,
            "gt_fee": "0",
            "point_fee": "0",
            "market": "EQTY_USDT",
            "vip": -1,
            "vip_fee_discount": "1",
        },
        {
            "id": 1930726127,
            "order_id": 1932131558,
            "strategy_id": 5453981,
            "positive_order_id": 0,
            "me_order_id": 1144458571367,
            "side": "sell",
            "price": "0.001887",
            "qty": "1966",
            "match_price": "0.001887",
            "match_qty": "1966",
            "match_amount": "3.709842",
            "fee": "0.00363564516",
            "profit": "0",
            "status": "finished",
            "finish_as": "filled",
            "order_index": 4,
            "order_type": "",
            "create_time": 1791257285,
            "finish_time": 1791269170,
            "gt_fee": "0",
            "point_fee": "0",
            "market": "EQTY_USDT",
            "vip": -1,
            "vip_fee_discount": "1",
        },
    ],
}


def test_open_orders_normalize_real_captured_shape() -> None:
    result = normalize_native_open_orders(
        CAPTURED_OPEN_ORDERS,
        strategy_id=STRATEGY_ID,
    )

    assert result["strategy_id"] == STRATEGY_ID

    assert result["summary"] == {
        "open_count": 4,
        "ask_count": 2,
        "bid_count": 2,
        "sell_count": 2,
        "buy_count": 2,
    }

    assert (
        result["asks"][0]["order_id"]
        == "1938066916"
    )

    assert (
        result["asks"][0]["linked_order_id"]
        == "1938066617"
    )

    assert (
        result["asks"][0]["book_side"]
        == "ask"
    )

    assert (
        result["bids"][0]["book_side"]
        == "bid"
    )

    assert (
        result["bids"][0]["side"]
        == "buy"
    )


def test_open_orders_preserve_gate_price_precision() -> None:
    result = normalize_native_open_orders(
        CAPTURED_OPEN_ORDERS,
        strategy_id=STRATEGY_ID,
    )

    row = next(
        item
        for item in result["asks"]
        if item["order_id"]
        == "1932131565"
    )

    # Gate sent six decimal places here. Do not silently
    # compact it to 0.002.
    assert row["price"] == "0.002000"

    assert (
        row["match_price"]
        == "0.000000"
    )


def test_trades_preserve_gate_profit_and_linkage() -> None:
    result = normalize_native_trades(
        CAPTURED_TRADES,
        strategy_id=STRATEGY_ID,
    )

    assert result["pagination"] == {
        "page": 1,
        "page_size": 30,
        "page_count": 2,
        "total_count": 34,
    }

    assert (
        result["summary"]["returned_count"]
        == 3
    )

    assert (
        result["summary"]["gate_total_count"]
        == 34
    )

    assert (
        result["summary"]["positive_profit_count"]
        == 1
    )

    profitable = next(
        item
        for item in result["items"]
        if item["profit_positive"]
    )

    # This is Gate's own captured profit field.
    # No local calculation is involved.
    assert (
        profitable["profit"]
        == "0.03641413398"
    )

    assert (
        profitable["positive_order_id"]
        == "1937734062"
    )

    assert (
        profitable["linked_order_id"]
        == "1937734062"
    )

    assert (
        profitable["match_amount"]
        == "3.964149"
    )


def test_zero_positive_order_id_becomes_no_link() -> None:
    result = normalize_native_trades(
        CAPTURED_TRADES,
        strategy_id=STRATEGY_ID,
    )

    buy = result["items"][0]

    assert (
        buy["positive_order_id"]
        is None
    )

    assert (
        buy["linked_order_id"]
        is None
    )


def test_strategy_mismatch_fails_closed_for_open_orders() -> None:
    payload = copy.deepcopy(
        CAPTURED_OPEN_ORDERS
    )

    payload["data"]["ask"][0][
        "strategy_id"
    ] = 9999999

    with pytest.raises(
        NativeBotActivityError,
        match="strategy mismatch",
    ):
        normalize_native_open_orders(
            payload,
            strategy_id=STRATEGY_ID,
        )


def test_strategy_mismatch_fails_closed_for_trades() -> None:
    payload = copy.deepcopy(
        CAPTURED_TRADES
    )

    payload["data"][0][
        "strategy_id"
    ] = 9999999

    with pytest.raises(
        NativeBotActivityError,
        match="strategy mismatch",
    ):
        normalize_native_trades(
            payload,
            strategy_id=STRATEGY_ID,
        )


def test_ask_and_bid_side_semantics_fail_closed() -> None:
    payload = copy.deepcopy(
        CAPTURED_OPEN_ORDERS
    )

    payload["data"]["ask"][0][
        "side"
    ] = "buy"

    with pytest.raises(
        NativeBotActivityError,
        match="ask row",
    ):
        normalize_native_open_orders(
            payload,
            strategy_id=STRATEGY_ID,
        )


def test_gate_business_error_fails_closed() -> None:
    with pytest.raises(
        NativeBotActivityError,
        match="business code",
    ):
        normalize_native_trades(
            {
                "code": 500,
                "message": "example failure",
                "data": [],
            },
            strategy_id=STRATEGY_ID,
        )


def test_combined_activity_model_uses_same_strategy() -> None:
    result = normalize_native_activity(
        strategy_id=STRATEGY_ID,
        open_orders_payload=(
            CAPTURED_OPEN_ORDERS
        ),
        trades_payload=(
            CAPTURED_TRADES
        ),
    )

    assert (
        result["strategy_id"]
        == STRATEGY_ID
    )

    assert (
        result[
            "open_orders"
        ][
            "strategy_id"
        ]
        == STRATEGY_ID
    )

    assert (
        result[
            "trades"
        ][
            "strategy_id"
        ]
        == STRATEGY_ID
    )


def test_unknown_gate_fields_are_preserved_in_raw() -> None:
    payload = copy.deepcopy(
        CAPTURED_TRADES
    )

    payload["data"][0][
        "future_gate_field"
    ] = {
        "value": "preserve-me"
    }

    result = normalize_native_trades(
        payload,
        strategy_id=STRATEGY_ID,
    )

    assert (
        result["items"][0][
            "raw"
        ][
            "future_gate_field"
        ][
            "value"
        ]
        == "preserve-me"
    )
