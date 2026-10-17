from __future__ import annotations

from decimal import (
    Decimal,
    InvalidOperation,
)
from pathlib import Path
from typing import Any

from .demo_trading import (
    DEMO_TRADING_REQUIRED_CONFIRMATION,
    DemoTradingStore,
    _decimal_text,
    _normalize_account_id,
)
from .demo_trading_order_lifecycle import (
    DemoTradingOrderLifecycleStore,
    demo_trading_amend_confirmation_text,
    demo_trading_cancel_confirmation_text,
)
from .demo_trading_orders import (
    DemoTradingOrderStore,
    _normalize_request_id,
)


_DEMO_INTERVALS = (
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "1d",
)


class DemoTradingAuthorizationError(
    PermissionError
):
    """Demo Trading account is outside the authenticated scope."""


def _scope(
    account_ids: set[str],
) -> set[str]:
    return {
        _normalize_account_id(
            account_id
        )
        for account_id in account_ids
    }


def _require_account(
    account_ids: set[str],
    account_id: str,
) -> str:
    normalized = _normalize_account_id(
        account_id
    )

    if normalized not in _scope(
        account_ids
    ):
        raise DemoTradingAuthorizationError(
            "Demo Wallet account is outside "
            "the authenticated Trading scope"
        )

    return normalized


def _pair_payload(
    market: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id":
            market["id"],
        "base":
            market["base"],
        "quote":
            market["quote"],
        "trade_status":
            (
                "tradable"
                if market.get(
                    "trade_enabled"
                )
                else "untradable"
            ),
        "precision":
            market[
                "precision"
            ],
        "amount_precision":
            market[
                "amount_precision"
            ],
        "min_base_amount":
            market[
                "minimum_base_amount"
            ],
        "min_quote_amount":
            market[
                "minimum_quote_amount"
            ],
        "reference_price":
            market[
                "reference_price"
            ],
    }


def _book_interval(
    value: str,
) -> str:
    normalized = str(
        value or "0"
    ).strip()

    try:
        parsed = Decimal(
            normalized
        )

    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid Demo order-book interval"
        ) from exc

    if (
        not parsed.is_finite()
        or parsed < 0
    ):
        raise ValueError(
            "Invalid Demo order-book interval"
        )

    if parsed == 0:
        return "0"

    return format(
        parsed.normalize(),
        "f",
    )


def _order_effective_status(
    order: dict[str, Any],
) -> str:
    status = str(
        order.get(
            "status"
        )
        or ""
    ).strip().lower()

    if status == "open":
        return "confirmed_open"

    if status == "cancelled":
        return "confirmed_cancelled"

    return status or "unknown"


def _order_read_row(
    *,
    order: dict[str, Any],
    cancellation: dict[str, Any] | None,
    amendments: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source":
            "demo",
        "simulation":
            True,
        "managed":
            True,
        "request":
            order,
        "order_state": {
            "effective_status":
                _order_effective_status(
                    order
                ),
            "status":
                order["status"],
            "terminal":
                (
                    order[
                        "status"
                    ]
                    == "cancelled"
                ),
        },
        "cancellation":
            cancellation,
        "amendments":
            amendments,
        "amendment_count":
            len(
                amendments
            ),
        "latest_amendment":
            (
                amendments[-1]
                if amendments
                else None
            ),
        "active_amendment":
            None,
        "demo_order": {
            "id":
                order[
                    "demo_order_id"
                ],
            "currency_pair":
                order["pair"],
            "side":
                order["side"],
            "price":
                order["price"],
            "amount":
                order["amount"],
            "left":
                order[
                    "remaining_amount"
                ],
            "filled_total":
                order[
                    "filled_amount"
                ],
            "status":
                order["status"],
            "time_in_force":
                order[
                    "time_in_force"
                ],
            "create_time":
                order[
                    "created_at"
                ],
            "update_time":
                order[
                    "updated_at"
                ],
        },
    }


class DemoTradingApi:
    """
    Route-neutral adapter over isolated Demo Trading state.

    This class deliberately exposes no reconciliation method.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.market = DemoTradingStore(
            database_path
        )

        self.orders = DemoTradingOrderStore(
            database_path
        )

        self.lifecycle = (
            DemoTradingOrderLifecycleStore(
                database_path
            )
        )

    @staticmethod
    def _base(
        *,
        demo_write_performed: bool = False,
    ) -> dict[str, Any]:
        return {
            "source":
                "demo",
            "simulation":
                True,
            "gate_read_performed":
                False,
            "gate_write_performed":
                False,
            "write_performed":
                False,
            "demo_write_performed":
                demo_write_performed,
        }

    def catalog_payload(
        self,
        *,
        account_ids: set[str],
    ) -> dict[str, Any]:
        scope = _scope(
            account_ids
        )

        result = self.market.catalog(
            account_ids=
                scope,
        )

        return {
            **self._base(),
            "market_data_only":
                True,
            "accounts":
                result[
                    "accounts"
                ],
            "pairs": [
                _pair_payload(
                    pair
                )
                for pair in result[
                    "pairs"
                ]
            ],
            "default_pair":
                result[
                    "default_pair"
                ],
            "intervals":
                list(
                    _DEMO_INTERVALS
                ),
        }

    def snapshot_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        pair: str,
        depth: int,
        book_interval: str,
    ) -> dict[str, Any]:
        account = _require_account(
            account_ids,
            account_id,
        )

        normalized_interval = (
            _book_interval(
                book_interval
            )
        )

        result = self.market.snapshot(
            account_id=
                account,
            pair=pair,
            depth=depth,
        )

        catalog = self.market.catalog(
            account_ids={
                account,
            }
        )

        account_row = next(
            (
                row
                for row in catalog[
                    "accounts"
                ]
                if row["id"]
                == account
            ),
            {
                "id":
                    account,
                "name":
                    account,
                "execution_mode":
                    "demo",
            },
        )

        return {
            **self._base(),
            "market_data_only":
                True,
            "account":
                account_row,
            "account_id":
                account,
            "pair":
                _pair_payload(
                    result[
                        "pair"
                    ]
                ),
            "ticker":
                result[
                    "ticker"
                ],
            "book_interval":
                normalized_interval,
            "order_book":
                result[
                    "order_book"
                ],
            "balances":
                result[
                    "balances"
                ],
        }

    def candles_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        pair: str,
        interval: str,
        limit: int,
    ) -> dict[str, Any]:
        account = _require_account(
            account_ids,
            account_id,
        )

        result = self.market.candles(
            pair=pair,
            interval=interval,
            limit=limit,
        )

        return {
            **self._base(),
            "market_data_only":
                True,
            "account_id":
                account,
            "pair":
                result["pair"],
            "interval":
                result[
                    "interval"
                ],
            "candles":
                result[
                    "candles"
                ],
        }

    def trades_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        pair: str,
        limit: int,
    ) -> dict[str, Any]:
        account = _require_account(
            account_ids,
            account_id,
        )

        result = self.market.trades(
            pair=pair,
            limit=limit,
        )

        rows = []

        for item in result[
            "trades"
        ]:
            price = Decimal(
                str(
                    item["price"]
                )
            )

            amount = Decimal(
                str(
                    item["amount"]
                )
            )

            rows.append(
                {
                    "id":
                        item["id"],
                    "time_ms":
                        str(
                            item["time"]
                        ),
                    "side":
                        item["side"],
                    "price":
                        item["price"],
                    "amount":
                        item["amount"],
                    "total":
                        _decimal_text(
                            price
                            * amount
                        ),
                }
            )

        return {
            **self._base(),
            "market_data_only":
                True,
            "account_id":
                account,
            "pair":
                result["pair"],
            "trades":
                rows,
        }

    def execution_capabilities_payload(
        self,
        *,
        account_ids: set[str],
    ) -> dict[str, Any]:
        scope = sorted(
            _scope(
                account_ids
            )
        )

        return {
            **self._base(),
            "execution_implemented":
                True,
            "execution_route_available":
                True,
            "live_arm_enabled":
                False,
            "required_confirmation":
                DEMO_TRADING_REQUIRED_CONFIRMATION,
            "demo_execution_enabled":
                True,
            "cancellation_implemented":
                True,
            "cancellation_route_available":
                True,
            "cancel_arm_enabled":
                False,
            "demo_cancellation_enabled":
                True,
            "amendment_implemented":
                True,
            "amendment_route_available":
                True,
            "amend_arm_enabled":
                False,
            "demo_amendment_enabled":
                True,
            "authorized_account_ids":
                scope,
            "configured_account_ids":
                scope,
            "policy_allowed_account_ids":
                scope,
            "config_error":
                "",
        }

    def preview_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        pair: str,
        side: str,
        price,
        amount,
        time_in_force: str,
    ) -> dict[str, Any]:
        account = _require_account(
            account_ids,
            account_id,
        )

        result = (
            self.market
            .preview_limit_order(
                account_id=
                    account,
                pair=pair,
                side=side,
                price=price,
                amount=amount,
                time_in_force=
                    time_in_force,
            )
        )

        result = dict(
            result
        )

        result[
            "pair"
        ] = _pair_payload(
            result["pair"]
        )

        result.update(
            {
                "preview_only":
                    True,
                "execution_implemented":
                    True,
                "execution_enabled":
                    bool(
                        result[
                            "demo_execution_ready"
                        ]
                    ),
                "can_execute":
                    bool(
                        result[
                            "demo_execution_ready"
                        ]
                    ),
                "gate_write_required":
                    False,
            }
        )

        return result

    def execute_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        username: str,
        account_id: str,
        pair: str,
        side: str,
        price,
        amount,
        time_in_force: str,
        confirmation: str,
    ) -> dict[str, Any]:
        account = _require_account(
            account_ids,
            account_id,
        )

        return self.orders.create_limit_order(
            request_id=request_id,
            username=username,
            account_id=account,
            pair=pair,
            side=side,
            price=price,
            amount=amount,
            time_in_force=
                time_in_force,
            confirmation=
                confirmation,
        )

    def _rows(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        pair: str | None,
        limit: int,
        open_only: bool,
    ) -> list[dict[str, Any]]:
        account = _require_account(
            account_ids,
            account_id,
        )

        rows = self.orders.list_orders(
            account_ids={
                account,
            },
            limit=max(
                int(limit),
                1,
            ),
        )

        if pair:
            normalized_pair = (
                self.market.market(
                    pair
                )[
                    "id"
                ]
            )

            rows = [
                row
                for row in rows
                if row[
                    "pair"
                ]
                == normalized_pair
            ]

        if open_only:
            rows = [
                row
                for row in rows
                if row[
                    "status"
                ]
                == "open"
            ]

        result = []

        for order in rows[
            :max(
                1,
                int(limit),
            )
        ]:
            request_id = str(
                order[
                    "request_id"
                ]
            )

            cancellation = (
                self.lifecycle
                .get_cancellation(
                    request_id,
                    account_ids={
                        account,
                    },
                )
            )

            amendments = (
                self.lifecycle
                .list_amendments(
                    request_id,
                    account_ids={
                        account,
                    },
                )
            )

            result.append(
                _order_read_row(
                    order=order,
                    cancellation=
                        cancellation,
                    amendments=
                        amendments,
                )
            )

        return result

    def open_orders_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        pair: str | None,
        limit: int,
    ) -> dict[str, Any]:
        account = _require_account(
            account_ids,
            account_id,
        )

        rows = self._rows(
            account_ids=
                account_ids,
            account_id=
                account,
            pair=pair,
            limit=limit,
            open_only=True,
        )

        return {
            **self._base(),
            "account_id":
                account,
            "scope":
                (
                    "market"
                    if pair
                    else "account"
                ),
            "pair":
                (
                    self.market.market(
                        pair
                    )["id"]
                    if pair
                    else None
                ),
            "count":
                len(rows),
            "orders":
                rows,
        }

    def recent_orders_payload(
        self,
        *,
        account_ids: set[str],
        account_id: str,
        pair: str | None,
        limit: int,
    ) -> dict[str, Any]:
        account = _require_account(
            account_ids,
            account_id,
        )

        rows = self._rows(
            account_ids=
                account_ids,
            account_id=
                account,
            pair=pair,
            limit=limit,
            open_only=False,
        )

        return {
            **self._base(),
            "history_source":
                "demo",
            "account_id":
                account,
            "scope":
                (
                    "market"
                    if pair
                    else "account"
                ),
            "pair":
                (
                    self.market.market(
                        pair
                    )["id"]
                    if pair
                    else None
                ),
            "count":
                len(rows),
            "orders":
                rows,
        }

    def order_detail_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
    ) -> dict[str, Any]:
        scope = _scope(
            account_ids
        )

        order = self.orders.get_order(
            request_id,
            account_ids=
                scope,
        )

        normalized_request_id = str(
            order[
                "request_id"
            ]
        )

        cancellation = (
            self.lifecycle
            .get_cancellation(
                normalized_request_id,
                account_ids=
                    scope,
            )
        )

        amendments = (
            self.lifecycle
            .list_amendments(
                normalized_request_id,
                account_ids=
                    scope,
            )
        )

        events = self.orders.list_events(
            normalized_request_id,
            account_ids=
                scope,
        )

        return {
            **self._base(),
            "request":
                order,
            "order_state": {
                "effective_status":
                    _order_effective_status(
                        order
                    ),
                "status":
                    order[
                        "status"
                    ],
                "terminal":
                    (
                        order[
                            "status"
                        ]
                        == "cancelled"
                    ),
            },
            "events":
                events,
            "reconciliations":
                [],
            "cancellation":
                cancellation,
            "active_amendment":
                None,
            "amendments":
                amendments,
            "lock":
                None,
        }

    def cancel_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        cancel_request_id: str,
        username: str,
        confirmation: str,
    ) -> dict[str, Any]:
        scope = _scope(
            account_ids
        )

        normalized_cancel_id = (
            _normalize_request_id(
                cancel_request_id
            )
        )

        # Parent authorization occurs before lifecycle mutation.
        self.orders.get_order(
            request_id,
            account_ids=
                scope,
        )

        result = (
            self.lifecycle
            .cancel_order(
                request_id=
                    request_id,
                username=
                    username,
                confirmation=
                    confirmation,
                account_ids=
                    scope,
            )
        )

        return {
            **result,
            "cancel_request_id":
                normalized_cancel_id,
        }

    def amend_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        amend_request_id: str,
        username: str,
        requested_price,
        confirmation: str,
    ) -> dict[str, Any]:
        scope = _scope(
            account_ids
        )

        # Parent authorization occurs before lifecycle mutation.
        self.orders.get_order(
            request_id,
            account_ids=
                scope,
        )

        return (
            self.lifecycle
            .amend_order_price(
                amendment_id=
                    amend_request_id,
                request_id=
                    request_id,
                username=
                    username,
                new_price=
                    requested_price,
                confirmation=
                    confirmation,
                account_ids=
                    scope,
            )
        )

    def confirmation_payload(
        self,
        *,
        account_ids: set[str],
        request_id: str,
        operation: str,
        requested_price=None,
    ) -> dict[str, Any]:
        scope = _scope(
            account_ids
        )

        order = self.orders.get_order(
            request_id,
            account_ids=
                scope,
        )

        normalized_operation = str(
            operation or ""
        ).strip().lower()

        if normalized_operation == "cancel":
            required = (
                demo_trading_cancel_confirmation_text(
                    order[
                        "request_id"
                    ]
                )
            )

        elif normalized_operation == "amend":
            if requested_price is None:
                raise ValueError(
                    "Demo amend price is required"
                )

            required = (
                demo_trading_amend_confirmation_text(
                    order[
                        "request_id"
                    ],
                    requested_price,
                )
            )

        else:
            raise ValueError(
                "Unsupported Demo Trading confirmation operation"
            )

        return {
            **self._base(),
            "request_id":
                order[
                    "request_id"
                ],
            "operation":
                normalized_operation,
            "required_confirmation":
                required,
        }
