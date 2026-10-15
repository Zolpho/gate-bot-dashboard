from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from .balances import (
    build_account_balance_payload,
)
from .config import Settings
from .demo_wallet import DemoWalletStore
from .deposits import (
    build_deposit_details,
    merge_deposit_networks,
    normalize_currency_catalog,
    utc_now_iso,
)


def _display_name(
    store: DemoWalletStore,
    account_id: str,
) -> str:
    for account in store.list_accounts():
        if (
            account["account_id"]
            == account_id
        ):
            return str(
                account["display_name"]
            )

    raise KeyError(
        "Unknown Demo Wallet account"
    )


def _raw_chain(
    network: dict[str, Any],
) -> dict[str, Any]:
    return {
        "chain":
            network["chain"],
        "name_en":
            network["name"],
        "contract_address":
            network.get(
                "contract_address",
                "",
            ),
        "is_disabled":
            0,
        "is_deposit_disabled": (
            0
            if network.get(
                "deposit_enabled"
            )
            else 1
        ),
        "is_withdraw_disabled": (
            0
            if network.get(
                "withdraw_enabled"
            )
            else 1
        ),
        "is_tag": (
            1
            if network.get(
                "requires_memo"
            )
            else 0
        ),
        "decimal":
            network.get(
                "decimal"
            ),
    }


def demo_balance_payload(
    *,
    store: DemoWalletStore,
    account_id: str,
    settings: Settings,
) -> dict[str, Any]:
    state = store.get_balance_state(
        account_id
    )

    spot_accounts = [
        {
            "currency":
                item["currency"],
            "available":
                item["available"],
            "locked":
                item["locked"],
        }
        for item
        in state["assets"]
    ]

    tickers = [
        {
            "currency_pair":
                (
                    f"{item['currency']}"
                    "_USDT"
                ),
            "last":
                item["price_usdt"],
        }
        for item
        in state["assets"]
        if item["currency"] != "USDT"
    ]

    payload = (
        build_account_balance_payload(
            account_id=account_id,
            display_name=(
                state["display_name"]
            ),
            total_balance={
                "total": {
                    "amount":
                        state[
                            "total_value_usdt"
                        ],
                    "currency":
                        "USDT",
                },
                "details": {
                    "spot": {
                        "amount":
                            state[
                                "spot_value_usdt"
                            ],
                        "currency":
                            "USDT",
                    },
                    "quant": {
                        "amount":
                            state[
                                "quant_value_usdt"
                            ],
                        "currency":
                            "USDT",
                    },
                },
            },
            spot_accounts=spot_accounts,
            spot_tickers=tickers,
            bot_summary=(
                state["bot_summary"]
            ),
            dust_usdt=Decimal(
                str(
                    settings
                    .balance_dust_usdt
                )
            ),
            source="demo",
        )
    )

    payload["cache"] = {
        "hit": False,
        "ttl_seconds": 0,
    }

    return payload


def demo_deposit_catalog_payload(
    *,
    store: DemoWalletStore,
    account_id: str,
    favorites: Iterable[str],
) -> dict[str, Any]:
    raw_currencies = []

    for currency in (
        store.list_currencies()
    ):
        networks = (
            store.list_deposit_networks(
                account_id,
                currency["currency"],
            )
        )

        raw_currencies.append(
            {
                "currency":
                    currency[
                        "currency"
                    ],
                "name":
                    currency["name"],
                "chain":
                    currency[
                        "main_chain"
                    ],
                "trade_disabled":
                    currency[
                        "trade_disabled"
                    ],
                "delisted":
                    False,
                "deposit_disabled":
                    False,
                "chains": [
                    _raw_chain(
                        network
                    )
                    for network
                    in networks
                ],
            }
        )

    payload = normalize_currency_catalog(
        raw_currencies,
        favorites,
    )

    payload["source"] = "demo"
    payload["cache"] = {
        "hit": False,
        "ttl_seconds": 0,
    }

    return payload


def demo_deposit_networks_payload(
    *,
    store: DemoWalletStore,
    account_id: str,
    currency: str,
) -> dict[str, Any]:
    networks = (
        store.list_deposit_networks(
            account_id,
            currency,
        )
    )

    return {
        "account_id":
            account_id,
        "display_name":
            _display_name(
                store,
                account_id,
            ),
        "currency":
            currency.upper(),
        "as_of":
            utc_now_iso(),
        "networks":
            merge_deposit_networks(
                [
                    _raw_chain(
                        network
                    )
                    for network
                    in networks
                ]
            ),
    }


def demo_deposit_address_payload(
    *,
    store: DemoWalletStore,
    account_id: str,
    currency: str,
    chain: str,
) -> dict[str, Any]:
    networks = (
        store.list_deposit_networks(
            account_id,
            currency,
        )
    )

    selected = (
        store.get_deposit_address(
            account_id,
            currency,
            chain,
        )
    )

    raw_address = {
        "min_deposit_amount":
            selected[
                "minimum_deposit_amount"
            ],
        "multichain_addresses": [
            {
                "chain":
                    network["chain"],
                "address":
                    network["address"],
                "payment_id":
                    (
                        network.get(
                            "payment_id"
                        )
                        or ""
                    ),
                "payment_name":
                    "",
                "obtain_failed":
                    0,
                "min_confirms":
                    network[
                        "min_confirmations"
                    ],
            }
            for network
            in networks
        ],
    }

    return build_deposit_details(
        account_id=account_id,
        display_name=_display_name(
            store,
            account_id,
        ),
        currency=currency,
        selected_chain=chain,
        raw_chains=[
            _raw_chain(
                network
            )
            for network
            in networks
        ],
        raw_address=raw_address,
        source="demo",
    )


def demo_deposit_list_payload(
    *,
    store: DemoWalletStore,
    account_id: str,
    currency: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    # The deterministic seed is intentionally tiny. Fetching the
    # full bounded Demo history here keeps filtering semantics
    # compatible without touching production DepositRecord tables.
    result = store.list_deposits(
        account_id,
        limit=200,
        offset=0,
    )

    items = list(
        result["items"]
    )

    if currency:
        wanted_currency = (
            currency
            .strip()
            .upper()
        )

        items = [
            item
            for item in items
            if (
                item["currency"]
                == wanted_currency
            )
        ]

    if status:
        wanted_status = (
            status
            .strip()
            .upper()
        )

        items = [
            item
            for item in items
            if (
                item["status"]
                == wanted_status
            )
        ]

    total = len(
        items
    )

    page = items[
        offset:
        offset + limit
    ]

    return {
        "account_id":
            account_id,
        "display_name":
            _display_name(
                store,
                account_id,
            ),
        "total":
            total,
        "limit":
            limit,
        "offset":
            offset,
        "items":
            page,
        "sync": {
            "status":
                "demo",
            "last_sync_at":
                None,
            "last_success_at":
                None,
            "last_reconciliation_at":
                None,
            "last_error":
                "",
            "record_count":
                total,
            "created_count":
                0,
            "updated_count":
                0,
        },
    }


def demo_deposit_detail_payload(
    *,
    store: DemoWalletStore,
    account_id: str,
    deposit_id: int,
) -> dict[str, Any]:
    return {
        "deposit":
            store.get_deposit(
                account_id,
                deposit_id,
            )
    }
