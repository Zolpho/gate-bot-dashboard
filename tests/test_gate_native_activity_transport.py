from __future__ import annotations

import json

import httpx
import pytest

from app.gate_native_activity_transport import (
    GATE_WEB_ORIGIN,
    GateNativeActivityTransport,
    NativeActivityTransportError,
    native_open_orders_availability,
)


STRATEGY_ID = "5453981"


def _trade_payload() -> dict:
    return {
        "code": 200,
        "label": "",
        "message": "",
        "page": 1,
        "pagesize": 30,
        "pagecount": 2,
        "totalcount": 36,
        "data": [
            {
                "id": 1936565072,
                "order_id": 1937810978,
                "strategy_id": 5453981,
                "positive_order_id":
                    1937734062,
                "me_order_id":
                    1147079562067,
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
            }
        ],
    }


@pytest.mark.asyncio
async def test_fetch_trades_uses_exact_native_endpoint_and_profile() -> None:
    captured: dict[
        str,
        object,
    ] = {}

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        captured[
            "method"
        ] = request.method

        captured[
            "url"
        ] = str(
            request.url
        )

        captured[
            "headers"
        ] = {
            key.lower():
                value
            for key, value
            in request.headers.items()
        }

        return httpx.Response(
            200,
            json=_trade_payload(),
        )

    client = httpx.AsyncClient(
        base_url=GATE_WEB_ORIGIN,
        transport=httpx.MockTransport(
            handler
        ),
    )

    try:
        transport = (
            GateNativeActivityTransport(
                client=client
            )
        )

        result = await transport.fetch_trades(
            STRATEGY_ID
        )

    finally:
        await client.aclose()


    assert (
        captured[
            "method"
        ]
        == "GET"
    )

    assert (
        captured[
            "url"
        ]
        == (
            "https://www.gate.com/"
            "apiw/v2/grid-trading/"
            "order_record/5453981"
            "?page=1"
            "&page_size=30"
            "&status=finished"
        )
    )


    headers = captured[
        "headers"
    ]

    assert isinstance(
        headers,
        dict,
    )

    assert (
        headers.get(
            "accept"
        )
        == (
            "application/json, "
            "text/plain, */*"
        )
    )

    assert (
        headers.get(
            "referer"
        )
        == (
            "https://www.gate.com/"
            "strategybot/underwayStrategy"
        )
    )

    assert "cookie" not in headers
    assert "authorization" not in headers
    assert "key" not in headers
    assert "sign" not in headers

    assert (
        result[
            "credential_mode"
        ]
        == "none"
    )

    assert (
        result[
            "source"
        ]
        == "gate_native_order_record"
    )

    assert (
        result[
            "trades"
        ][
            "pagination"
        ][
            "total_count"
        ]
        == 36
    )

    assert (
        result[
            "trades"
        ][
            "items"
        ][0][
            "profit"
        ]
        == "0.03641413398"
    )


@pytest.mark.asyncio
async def test_fetch_trades_fails_closed_on_strategy_mismatch() -> None:
    payload = _trade_payload()

    payload[
        "data"
    ][0][
        "strategy_id"
    ] = 9999999

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            json=payload,
        )

    client = httpx.AsyncClient(
        base_url=GATE_WEB_ORIGIN,
        transport=httpx.MockTransport(
            handler
        ),
    )

    try:
        transport = (
            GateNativeActivityTransport(
                client=client
            )
        )

        with pytest.raises(
            NativeActivityTransportError,
            match="strategy mismatch",
        ):
            await transport.fetch_trades(
                STRATEGY_ID
            )

    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_trades_rejects_http_failure() -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            403,
            text="403",
        )

    client = httpx.AsyncClient(
        base_url=GATE_WEB_ORIGIN,
        transport=httpx.MockTransport(
            handler
        ),
    )

    try:
        transport = (
            GateNativeActivityTransport(
                client=client
            )
        )

        with pytest.raises(
            NativeActivityTransportError,
            match="HTTP 403",
        ):
            await transport.fetch_trades(
                STRATEGY_ID
            )

    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_trades_rejects_non_json() -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            text="not-json",
        )

    client = httpx.AsyncClient(
        base_url=GATE_WEB_ORIGIN,
        transport=httpx.MockTransport(
            handler
        ),
    )

    try:
        transport = (
            GateNativeActivityTransport(
                client=client
            )
        )

        with pytest.raises(
            NativeActivityTransportError,
            match="non-JSON",
        ):
            await transport.fetch_trades(
                STRATEGY_ID
            )

    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "strategy_id",
    [
        "",
        " ",
        "../123",
        "abc",
        "12?3",
        "１２３",
    ],
)
@pytest.mark.asyncio
async def test_fetch_trades_rejects_invalid_strategy_id(
    strategy_id: str,
) -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        raise AssertionError(
            "HTTP must not run for invalid strategy IDs"
        )

    client = httpx.AsyncClient(
        base_url=GATE_WEB_ORIGIN,
        transport=httpx.MockTransport(
            handler
        ),
    )

    try:
        transport = (
            GateNativeActivityTransport(
                client=client
            )
        )

        with pytest.raises(
            ValueError
        ):
            await transport.fetch_trades(
                strategy_id
            )

    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "page_size",
    [
        0,
        31,
        100,
    ],
)
@pytest.mark.asyncio
async def test_fetch_trades_bounds_page_size(
    page_size: int,
) -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        raise AssertionError(
            "HTTP must not run for invalid page size"
        )

    client = httpx.AsyncClient(
        base_url=GATE_WEB_ORIGIN,
        transport=httpx.MockTransport(
            handler
        ),
    )

    try:
        transport = (
            GateNativeActivityTransport(
                client=client
            )
        )

        with pytest.raises(
            ValueError,
            match="page_size",
        ):
            await transport.fetch_trades(
                STRATEGY_ID,
                page_size=page_size,
            )

    finally:
        await client.aclose()


def test_open_orders_are_explicitly_session_required() -> None:
    availability = (
        native_open_orders_availability()
    )

    assert availability.available is False

    assert (
        availability.reason
        == "gate_web_session_required"
    )

    assert (
        availability.source
        == "gate_native_order_book"
    )

    assert (
        availability.requires_gate_web_session
        is True
    )


def test_transport_source_contains_no_cookie_or_api_secret_parameters() -> None:
    import inspect

    source = inspect.getsource(
        GateNativeActivityTransport
    ).lower()

    assert "api_secret" not in source
    assert "api_key" not in source

    # Comments may discuss cookies; constructor/method
    # signatures must not accept credential material.
    signature = str(
        inspect.signature(
            GateNativeActivityTransport
        )
    ).lower()

    fetch_signature = str(
        inspect.signature(
            GateNativeActivityTransport.fetch_trades
        )
    ).lower()

    assert "cookie" not in signature
    assert "cookie" not in fetch_signature
    assert "token" not in signature
    assert "token" not in fetch_signature
