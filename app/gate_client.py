from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode, urlsplit

import httpx

from .accounts import GateAccountConfig
from .config import Settings, get_settings


class GateAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        label: str = "",
        response: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.label = label
        self.response = response


@dataclass(slots=True)
class GateResponse:
    data: Any
    status_code: int
    headers: dict[str, str]
    raw: Any


class GateClient:
    """Minimal async Gate API v4 client with native request signing.

    The dashboard uses direct HTTP rather than the generated SDK so it can keep
    unknown strategy-specific map fields intact in bot detail responses.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        account: GateAccountConfig | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.account = account
        self.account_id = account.id if account else self.settings.gate_account_id
        self.api_key = account.api_key if account else self.settings.gate_api_key
        self.api_secret = account.api_secret if account else self.settings.gate_api_secret
        self.base_url = self.settings.gate_base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        self._base_path = parsed.path.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.gate_request_timeout_seconds),
            headers={
                "Accept": "application/json",
                "User-Agent": "gate-bot-dashboard/2.0",
                "X-Gate-App-Lang": self.settings.gate_language,
            },
        )

    async def __aenter__(self) -> "GateClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def build_signature(
        secret: str,
        method: str,
        request_path: str,
        query_string: str,
        payload: bytes,
        timestamp: str,
    ) -> str:
        payload_hash = hashlib.sha512(payload).hexdigest()
        signature_string = "\n".join(
            [method.upper(), request_path, query_string, payload_hash, timestamp]
        )
        return hmac.new(
            secret.encode("utf-8"),
            signature_string.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

    @staticmethod
    def _query_string(params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None) -> str:
        if not params:
            return ""
        items: Iterable[tuple[str, Any]]
        items = params.items() if isinstance(params, Mapping) else params
        clean: list[tuple[str, Any]] = []
        for key, value in items:
            if value is None:
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            clean.append((key, value))
        return urlencode(clean, doseq=True)

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        json_body: Any = None,
        signed: bool = True,
        extra_headers: Mapping[str, str] | None = None,
    ) -> GateResponse:
        endpoint = "/" + endpoint.lstrip("/")
        query_string = self._query_string(params)
        payload = (
            json.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if json_body is not None
            else b""
        )
        request_path = f"{self._base_path}{endpoint}"
        url = f"{self.base_url}{endpoint}"
        if query_string:
            url = f"{url}?{query_string}"

        headers: dict[str, str] = {
            "X-Client-Request-Id": str(uuid.uuid4()),
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)

        if signed:
            if not self.api_key or not self.api_secret:
                raise GateAPIError(f"Gate API key and secret are not configured for account {self.account_id}")
            timestamp = str(int(time.time()))
            headers.update(
                {
                    "KEY": self.api_key,
                    "Timestamp": timestamp,
                    "SIGN": self.build_signature(
                        self.api_secret,
                        method,
                        request_path,
                        query_string,
                        payload,
                        timestamp,
                    ),
                }
            )

        try:
            response = await self._client.request(
                method.upper(), url, content=payload if json_body is not None else None, headers=headers
            )
        except httpx.HTTPError as exc:
            raise GateAPIError(f"Gate network error: {exc}") from exc

        try:
            raw = response.json()
        except ValueError:
            raw = response.text

        if response.status_code >= 400:
            label = raw.get("label", "") if isinstance(raw, dict) else ""
            message = (
                raw.get("message") or raw.get("detail") or str(raw)
                if isinstance(raw, dict)
                else str(raw)
            )
            raise GateAPIError(
                f"Gate API returned {response.status_code}: {message}",
                status_code=response.status_code,
                label=label,
                response=raw,
            )

        # Bot endpoints use a business envelope. A non-zero code is an error even
        # when the HTTP response is 200.
        if endpoint.startswith("/bot/") and isinstance(raw, dict):
            code = raw.get("code")
            if code not in (None, 0, "0", 200, "200"):
                raise GateAPIError(
                    f"Gate bot API error {code}: {raw.get('message', 'Unknown error')}",
                    status_code=response.status_code,
                    label=str(code),
                    response=raw,
                )
            data = raw.get("data")
        else:
            data = raw

        return GateResponse(
            data=data,
            status_code=response.status_code,
            headers=dict(response.headers),
            raw=raw,
        )

    async def server_time(self) -> Any:
        return (await self.request("GET", "/spot/time", signed=False)).data

    async def list_running_bots(
        self,
        *,
        strategy_type: str | None = None,
        market: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> GateResponse:
        return await self.request(
            "GET",
            "/bot/portfolio/running",
            params=[
                ("strategy_type", strategy_type),
                ("market", market),
                ("page", page),
                ("page_size", page_size or self.settings.gate_bot_page_size),
            ],
        )

    async def list_all_running_bots(self) -> tuple[list[dict[str, Any]], list[Any]]:
        page = 1
        all_items: list[dict[str, Any]] = []
        raw_pages: list[Any] = []
        while True:
            response = await self.list_running_bots(page=page)
            raw_pages.append(response.raw)
            data = response.data or {}
            items = data.get("items", []) if isinstance(data, dict) else []
            all_items.extend(item for item in items if isinstance(item, dict))
            total = int(data.get("total", len(all_items))) if isinstance(data, dict) else len(all_items)
            page_size = int(data.get("page_size", self.settings.gate_bot_page_size)) if isinstance(data, dict) else self.settings.gate_bot_page_size
            if not items or len(all_items) >= total or len(items) < page_size:
                break
            page += 1
        return all_items, raw_pages

    async def get_bot_detail(self, strategy_id: str, strategy_type: str) -> GateResponse:
        return await self.request(
            "GET",
            "/bot/portfolio/detail",
            params=[("strategy_id", strategy_id), ("strategy_type", strategy_type)],
        )

    async def get_strategy_recommendations(
        self,
        *,
        market: str | None = None,
        strategy_type: str | None = None,
        direction: str | None = None,
        invest_amount: str | None = None,
        scene: str | None = None,
        limit: int = 10,
        max_drawdown_lte: str | None = None,
        backtest_apr_gte: str | None = None,
    ) -> GateResponse:
        return await self.request(
            "GET",
            "/bot/strategy/recommend",
            params=[
                ("market", market),
                ("strategy_type", strategy_type),
                ("direction", direction),
                ("invest_amount", invest_amount),
                ("scene", scene),
                ("limit", max(1, min(limit, 10))),
                ("max_drawdown_lte", max_drawdown_lte),
                ("backtest_apr_gte", backtest_apr_gte),
            ],
        )

    async def create_spot_grid(
        self,
        payload: dict[str, Any],
    ) -> GateResponse:
        return await self.request(
            "POST",
            "/bot/spot-grid/create",
            json_body=payload,
        )

    async def stop_bot(self, strategy_id: str, strategy_type: str) -> GateResponse:
        return await self.request(
            "POST",
            "/bot/portfolio/stop",
            json_body={"strategy_id": strategy_id, "strategy_type": strategy_type},
        )

    async def get_total_balance(self, currency: str = "USDT") -> GateResponse:
        return await self.request(
            "GET",
            "/wallet/total_balance",
            params={"currency": currency.upper()},
        )

    async def list_spot_accounts(self) -> GateResponse:
        return await self.request("GET", "/spot/accounts")

    async def create_sub_account_transfer(
        self,
        payload: dict[str, Any],
    ) -> GateResponse:
        return await self.request(
            "POST",
            "/wallet/sub_account_transfers",
            json_body=payload,
        )

    async def get_transfer_order_status(
        self,
        *,
        client_order_id: str | None = None,
        tx_id: str | None = None,
    ) -> GateResponse:
        if not client_order_id and not tx_id:
            raise ValueError(
                "client_order_id or tx_id is required"
            )

        return await self.request(
            "GET",
            "/wallet/order_status",
            params={
                "client_order_id": client_order_id,
                "tx_id": tx_id,
            },
        )

    async def list_sub_account_transfers(
        self,
        *,
        sub_uid: str | None = None,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> GateResponse:
        return await self.request(
            "GET",
            "/wallet/sub_account_transfers",
            params=[
                ("sub_uid", sub_uid),
                ("from", from_timestamp),
                ("to", to_timestamp),
                ("limit", max(1, min(limit, 100))),
                ("offset", max(0, offset)),
            ],
        )

    async def get_spot_currency_pair(
        self,
        currency_pair: str,
    ) -> GateResponse:
        return await self.request(
            "GET",
            f"/spot/currency_pairs/{currency_pair.upper()}",
            signed=False,
        )

    async def list_spot_tickers(self, currency_pair: str | None = None) -> GateResponse:
        return await self.request(
            "GET",
            "/spot/tickers",
            params={"currency_pair": currency_pair},
            signed=False,
        )

    async def list_spot_currencies(
        self,
        name: str | None = None,
    ) -> GateResponse:
        return await self.request(
            "GET",
            "/spot/currencies",
            params={"name": name},
            signed=False,
        )

    async def list_currency_chains(
        self,
        currency: str,
    ) -> GateResponse:
        return await self.request(
            "GET",
            "/wallet/currency_chains",
            params={"currency": currency.upper()},
            signed=False,
        )

    async def get_deposit_address(
        self,
        currency: str,
    ) -> GateResponse:
        return await self.request(
            "GET",
            "/wallet/deposit_address",
            params={"currency": currency.upper()},
        )

    async def list_deposits(
        self,
        *,
        currency: str | None = None,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> GateResponse:
        return await self.request(
            "GET",
            "/wallet/deposits",
            params=[
                ("currency", currency),
                ("from", from_timestamp),
                ("to", to_timestamp),
                ("limit", max(1, min(limit, 100))),
                ("offset", max(0, offset)),
            ],
        )

    async def list_all_deposits(
        self,
        *,
        currency: str | None = None,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        page_limit: int = 100,
        max_records: int = 500,
    ) -> tuple[list[dict[str, Any]], int]:
        limit = max(1, min(page_limit, 100))
        maximum = max(1, min(max_records, 500))
        items: list[dict[str, Any]] = []
        page_count = 0
        offset = 0
        while len(items) < maximum:
            response = await self.list_deposits(
                currency=currency,
                from_timestamp=from_timestamp,
                to_timestamp=to_timestamp,
                limit=min(limit, maximum - len(items)),
                offset=offset,
            )
            page = response.data if isinstance(response.data, list) else []
            clean = [item for item in page if isinstance(item, dict)]
            items.extend(clean)
            page_count += 1
            if len(clean) < limit or not clean:
                break
            offset += len(clean)
        return items[:maximum], page_count

    async def account_snapshot(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        calls = {
            "total_balance": ("GET", "/wallet/total_balance", None),
            "spot_accounts": ("GET", "/spot/accounts", None),
            "futures_usdt_account": ("GET", "/futures/usdt/accounts", None),
            "futures_usdt_positions": ("GET", "/futures/usdt/positions", None),
        }
        for name, (method, endpoint, params) in calls.items():
            try:
                results[name] = (await self.request(method, endpoint, params=params)).data
            except GateAPIError as exc:
                results[name] = {
                    "error": str(exc),
                    "label": exc.label,
                    "status_code": exc.status_code,
                }
        return results
