from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .bot_native_activity import (
    NativeBotActivityError,
    normalize_native_trades,
)


GATE_WEB_ORIGIN = "https://www.gate.com"

_NATIVE_TRADES_PATH = (
    "/apiw/v2/grid-trading/order_record/{strategy_id}"
)

_BROWSER_HEADERS = {
    "Accept":
        "application/json, text/plain, */*",

    "Accept-Language":
        "en-US,en;q=0.9",

    "Cache-Control":
        "no-cache",

    "Pragma":
        "no-cache",

    "Referer":
        "https://www.gate.com/"
        "strategybot/underwayStrategy",

    "Sec-Fetch-Dest":
        "empty",

    "Sec-Fetch-Mode":
        "cors",

    "Sec-Fetch-Site":
        "same-origin",

    "User-Agent":
        "Mozilla/5.0 "
        "(Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/155.0.0.0 "
        "Safari/537.36",
}


class NativeActivityTransportError(
    RuntimeError
):
    pass


@dataclass(
    frozen=True,
    slots=True,
)
class NativeOpenOrdersAvailability:
    available: bool
    reason: str
    source: str
    requires_gate_web_session: bool


def native_open_orders_availability(
) -> NativeOpenOrdersAvailability:
    """
    Gate-native open orders are intentionally not fetched
    by this server-side transport.

    Proven behavior:
      * /apiw/v2/grid-trading/order_book/{strategy_id}
        returns GRID_INVALID_PARAM_USER without Gate web
        session context.
      * official /api/v4/spot/open_orders does not expose
        native strategy orders.

    We do not store or forward Gate web-session cookies.
    """

    return NativeOpenOrdersAvailability(
        available=False,
        reason=(
            "gate_web_session_required"
        ),
        source=(
            "gate_native_order_book"
        ),
        requires_gate_web_session=True,
    )


def _strategy_id(
    value: str,
) -> str:
    normalized = str(
        value
    ).strip()

    if not normalized:
        raise ValueError(
            "strategy_id cannot be empty"
        )

    if (
        not normalized.isascii()
        or not normalized.isdigit()
    ):
        raise ValueError(
            "strategy_id must contain digits only"
        )

    return normalized


def _page(
    value: int,
) -> int:
    normalized = int(
        value
    )

    if normalized < 1:
        raise ValueError(
            "page must be >= 1"
        )

    return normalized


def _page_size(
    value: int,
) -> int:
    normalized = int(
        value
    )

    if (
        normalized < 1
        or normalized > 30
    ):
        raise ValueError(
            "page_size must be between 1 and 30"
        )

    return normalized


class GateNativeActivityTransport:
    """
    Read-only transport for Gate web-native bot activity.

    The Trades endpoint is credential-free when called
    with the same browser-profile request characteristics
    proven during M4.21D2.

    No Gate API key, Gate API secret, browser cookie,
    Authorization header or CSRF token is accepted here.
    """

    def __init__(
        self,
        *,
        client: (
            httpx.AsyncClient
            | None
        ) = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._owns_client = (
            client is None
        )

        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                base_url=GATE_WEB_ORIGIN,
                headers=dict(
                    _BROWSER_HEADERS
                ),
                timeout=httpx.Timeout(
                    timeout_seconds
                ),
                follow_redirects=True,
            )
        )


    async def __aenter__(
        self,
    ) -> "GateNativeActivityTransport":
        return self


    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        await self.close()


    async def close(
        self,
    ) -> None:
        if self._owns_client:
            await self._client.aclose()


    async def fetch_trades(
        self,
        strategy_id: str,
        *,
        page: int = 1,
        page_size: int = 30,
        status: str = "finished",
    ) -> dict[str, Any]:
        normalized_strategy_id = (
            _strategy_id(
                strategy_id
            )
        )

        normalized_page = _page(
            page
        )

        normalized_page_size = (
            _page_size(
                page_size
            )
        )

        normalized_status = str(
            status
        ).strip().lower()

        if normalized_status != "finished":
            raise ValueError(
                "native trade status must be finished"
            )

        path = (
            _NATIVE_TRADES_PATH.format(
                strategy_id=(
                    normalized_strategy_id
                )
            )
        )

        try:
            response = await self._client.get(
                path,
                params={
                    "page":
                        normalized_page,

                    "page_size":
                        normalized_page_size,

                    "status":
                        normalized_status,
                },
                # Set the accepted profile per request too,
                # including injected/mock clients.
                headers=dict(
                    _BROWSER_HEADERS
                ),
            )

        except httpx.HTTPError as exc:
            raise NativeActivityTransportError(
                "Gate native Trades network error: "
                f"{exc}"
            ) from exc


        if response.status_code != 200:
            raise NativeActivityTransportError(
                "Gate native Trades returned "
                f"HTTP {response.status_code}"
            )


        try:
            payload = response.json()

        except ValueError as exc:
            raise NativeActivityTransportError(
                "Gate native Trades returned "
                "non-JSON content"
            ) from exc


        if not isinstance(
            payload,
            dict,
        ):
            raise NativeActivityTransportError(
                "Gate native Trades response "
                "must be an object"
            )


        try:
            normalized = (
                normalize_native_trades(
                    payload,
                    strategy_id=(
                        normalized_strategy_id
                    ),
                )
            )

        except NativeBotActivityError as exc:
            raise NativeActivityTransportError(
                "Gate native Trades contract error: "
                f"{exc}"
            ) from exc


        return {
            "source":
                "gate_native_order_record",

            "credential_mode":
                "none",

            "strategy_id":
                normalized_strategy_id,

            "trades":
                normalized,
        }
