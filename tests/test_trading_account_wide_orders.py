import inspect

import app.api.trading as trading_api

from app.trading_open_orders import (
    flatten_open_spot_orders,
    merge_account_open_spot_orders,
)


def gate_order(
    *,
    pair,
    order_id,
    text,
):
    return {
        "id": order_id,
        "text": text,
        "status": "open",
        "currency_pair": pair,
        "side": "buy",
        "price": "1",
        "amount": "1",
    }


def request(
    *,
    pair,
    order_id,
    text,
    request_id,
):
    return {
        "request_id": request_id,
        "account_id": "arnold",
        "pair": pair,
        "status": "confirmed_open",
        "order_type": "limit",
        "write_performed": True,
        "gate_order_id": order_id,
        "gate_text": text,
    }


def test_flatten_grouped_open_orders_inherits_pair():
    rows = flatten_open_spot_orders(
        [
            {
                "currency_pair": "BTC_USDT",
                "orders": [
                    {
                        "id": "11",
                        "text": "t-btc",
                        "status": "open",
                    },
                ],
            },
            {
                "currency_pair": "ETH_USDT",
                "orders": [
                    {
                        "id": "12",
                        "text": "t-eth",
                        "status": "open",
                        "currency_pair": "ETH_USDT",
                    },
                ],
            },
        ]
    )

    assert len(rows) == 2

    assert rows[0]["id"] == "11"
    assert (
        rows[0]["currency_pair"]
        == "BTC_USDT"
    )

    assert rows[1]["id"] == "12"
    assert (
        rows[1]["currency_pair"]
        == "ETH_USDT"
    )


def test_account_merge_matches_each_pair_independently():
    gate_rows = [
        gate_order(
            pair="EQTY_USDT",
            order_id="21",
            text="t-eqty",
        ),
        gate_order(
            pair="BTC_USDT",
            order_id="22",
            text="t-btc",
        ),
    ]

    local = [
        request(
            pair="EQTY_USDT",
            order_id="21",
            text="t-eqty",
            request_id="req-eqty",
        ),
        request(
            pair="BTC_USDT",
            order_id="22",
            text="t-btc",
            request_id="req-btc",
        ),
    ]

    rows = merge_account_open_spot_orders(
        account_id="arnold",
        gate_orders=gate_rows,
        local_requests=local,
        cancellations_by_request_id={},
    )

    assert len(rows) == 2

    assert [
        row["managed"]
        for row in rows
    ] == [
        True,
        True,
    ]

    assert {
        row["request"]["pair"]
        for row in rows
    } == {
        "EQTY_USDT",
        "BTC_USDT",
    }


def test_cross_pair_identity_cannot_manage_live_order():
    rows = merge_account_open_spot_orders(
        account_id="arnold",
        gate_orders=[
            gate_order(
                pair="EQTY_USDT",
                order_id="777",
                text="t-shared",
            ),
        ],
        local_requests=[
            request(
                pair="BTC_USDT",
                order_id="777",
                text="t-shared",
                request_id="req-btc",
            ),
        ],
        cancellations_by_request_id={},
    )

    assert len(rows) == 1
    assert rows[0]["managed"] is False
    assert rows[0]["request"] is None


def test_unmanaged_pair_remains_visible():
    rows = merge_account_open_spot_orders(
        account_id="arnold",
        gate_orders=[
            gate_order(
                pair="ETH_USDT",
                order_id="888",
                text="manual-order",
            ),
        ],
        local_requests=[],
        cancellations_by_request_id={},
    )

    assert len(rows) == 1
    assert rows[0]["managed"] is False

    assert (
        rows[0]["gate_order"]
        ["currency_pair"]
        == "ETH_USDT"
    )


def test_open_route_has_account_wide_read_branch():
    source = inspect.getsource(
        trading_api.trading_open_orders
    )

    assert '"/spot/open_orders"' in source
    assert (
        "flatten_open_spot_orders"
        in source
    )
    assert (
        "merge_account_open_spot_orders"
        in source
    )

    # Legacy explicit-pair read remains available.
    assert "list_spot_orders" in source

    assert '"scope"' in source


def test_recent_route_has_account_wide_audit_branch():
    source = inspect.getsource(
        trading_api.trading_recent_orders
    )

    assert "list_order_requests(" in source
    assert (
        "list_order_requests_for_market("
        in source
    )

    assert '"scope"' in source
