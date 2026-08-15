from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

import segno


_TRUE_VALUES = {"1", "true", "yes", "on", "disabled"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_currency_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol or len(symbol) > 32:
        raise ValueError("Invalid Gate currency symbol")
    if not re.fullmatch(r"[A-Z0-9._-]+", symbol):
        raise ValueError("Invalid Gate currency symbol")
    return symbol


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    return str(value or "").strip().lower() in _TRUE_VALUES


def _chain_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def normalize_currency_chains(raw_chains: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    if not isinstance(raw_chains, list):
        return result

    for raw in raw_chains:
        if not isinstance(raw, dict):
            continue

        chain = str(raw.get("chain") or raw.get("name") or "").strip()
        if not chain:
            continue

        key = _chain_key(chain)
        if not key or key in seen:
            continue
        seen.add(key)

        disabled = _flag(raw.get("is_disabled"))
        deposit_disabled = _flag(
            raw.get(
                "is_deposit_disabled",
                raw.get("deposit_disabled"),
            )
        )

        withdraw_disabled = _flag(
            raw.get(
                "is_withdraw_disabled",
                raw.get("withdraw_disabled"),
            )
        )

        result.append(
            {
                "chain": chain,
                "name": str(
                    raw.get("name_en")
                    or raw.get("name")
                    or raw.get("name_cn")
                    or chain
                ).strip(),
                "contract_address": str(
                    raw.get("contract_address")
                    or raw.get("addr")
                    or ""
                ).strip(),
                "deposit_enabled": not disabled and not deposit_disabled,
                "withdraw_enabled": not disabled and not withdraw_disabled,
                "deposit_disabled": deposit_disabled,
                "withdraw_disabled": withdraw_disabled,
                "disabled": disabled,
                "requires_memo": _flag(raw.get("is_tag")),
                "decimal": str(raw.get("decimal") or "").strip() or None,
            }
        )

    return result


def normalize_currency_catalog(
    raw_currencies: Any,
    favorites: Iterable[str],
) -> dict[str, Any]:
    favorite_list = [normalize_currency_symbol(item) for item in favorites]
    favorite_set = set(favorite_list)
    currencies: list[dict[str, Any]] = []

    if not isinstance(raw_currencies, list):
        raw_currencies = []

    for raw in raw_currencies:
        if not isinstance(raw, dict):
            continue

        try:
            symbol = normalize_currency_symbol(raw.get("currency"))
        except ValueError:
            continue

        if bool(raw.get("delisted")):
            continue

        chains = normalize_currency_chains(raw.get("chains") or [])
        overall_disabled = _flag(raw.get("deposit_disabled"))
        deposit_available = not overall_disabled and (
            any(item["deposit_enabled"] for item in chains)
            if chains
            else True
        )

        currencies.append(
            {
                "currency": symbol,
                "name": str(raw.get("name") or symbol).strip(),
                "deposit_available": deposit_available,
                "trade_disabled": bool(raw.get("trade_disabled")),
                "main_chain": str(raw.get("chain") or "").strip() or None,
                "chains": chains,
                "favorite": symbol in favorite_set,
            }
        )

    currencies.sort(
        key=lambda item: (
            0 if item["currency"] in favorite_set else 1,
            (
                favorite_list.index(item["currency"])
                if item["currency"] in favorite_set
                else 9999
            ),
            item["currency"],
        )
    )

    return {
        "as_of": utc_now_iso(),
        "favorites": [
            item
            for item in favorite_list
            if any(currency["currency"] == item for currency in currencies)
        ],
        "count": len(currencies),
        "deposit_available_count": sum(
            1 for item in currencies if item["deposit_available"]
        ),
        "currencies": currencies,
    }


def _address_items(raw_address: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_address, dict):
        return []

    multi = raw_address.get("multichain_addresses")
    if multi is None:
        multi = raw_address.get("multichain_address")

    if isinstance(multi, dict):
        multi = [multi]

    if not isinstance(multi, list):
        return []

    return [item for item in multi if isinstance(item, dict)]


def _merge_network(
    chain: dict[str, Any],
    address_item: dict[str, Any] | None,
) -> dict[str, Any]:
    address_item = address_item or {}
    address = str(address_item.get("address") or "").strip()
    obtain_failed = _flag(address_item.get("obtain_failed"))
    payment_id = str(address_item.get("payment_id") or "").strip() or None
    payment_name = str(address_item.get("payment_name") or "").strip() or None

    return {
        **chain,
        "address": address or None,
        "address_available": bool(address) and not obtain_failed,
        "payment_id": payment_id,
        "payment_name": payment_name,
        "requires_memo": bool(chain.get("requires_memo") or payment_id),
        "obtain_failed": obtain_failed,
        "min_confirmations": address_item.get("min_confirms"),
    }


def merge_deposit_networks(
    raw_chains: Any,
    raw_address: Any = None,
) -> list[dict[str, Any]]:
    chains = normalize_currency_chains(raw_chains)
    address_items = _address_items(raw_address)
    address_by_key: dict[str, dict[str, Any]] = {}

    for item in address_items:
        key = _chain_key(item.get("chain"))
        if key:
            address_by_key[key] = item

    networks: list[dict[str, Any]] = []
    consumed: set[str] = set()

    for chain in chains:
        possible_keys = {
            _chain_key(chain["chain"]),
            _chain_key(chain["name"]),
        }
        address_item = next(
            (
                address_by_key[key]
                for key in possible_keys
                if key in address_by_key
            ),
            None,
        )
        if address_item:
            consumed.add(_chain_key(address_item.get("chain")))
        networks.append(_merge_network(chain, address_item))

    for item in address_items:
        key = _chain_key(item.get("chain"))
        if not key or key in consumed:
            continue

        chain_name = str(item.get("chain") or "Unknown")
        networks.append(
            _merge_network(
                {
                    "chain": chain_name,
                    "name": chain_name,
                    "contract_address": "",
                    "deposit_enabled": True,
                    "disabled": False,
                    "requires_memo": bool(item.get("payment_id")),
                    "decimal": None,
                },
                item,
            )
        )

    top_address = (
        str(raw_address.get("address") or "").strip()
        if isinstance(raw_address, dict)
        else ""
    )
    if top_address and len(networks) == 1 and not networks[0]["address"]:
        networks[0]["address"] = top_address
        networks[0]["address_available"] = True

    return networks


def select_network(
    networks: list[dict[str, Any]],
    selected_chain: str,
) -> dict[str, Any]:
    wanted = _chain_key(selected_chain)

    for network in networks:
        possible = {
            _chain_key(network.get("chain")),
            _chain_key(network.get("name")),
        }
        if wanted in possible:
            return network

    raise LookupError(
        f"Gate did not return network {selected_chain!r} for this currency"
    )


def qr_svg_data_uri(value: str) -> str:
    qr = segno.make(value, micro=False, error="M")
    return qr.svg_data_uri(
        scale=5,
        border=2,
        dark="#07110e",
        light="#ffffff",
        xmldecl=False,
    )


def build_deposit_details(
    *,
    account_id: str,
    display_name: str,
    currency: str,
    selected_chain: str,
    raw_chains: Any,
    raw_address: Any,
    source: str = "gate",
) -> dict[str, Any]:
    symbol = normalize_currency_symbol(currency)
    networks = merge_deposit_networks(raw_chains, raw_address)
    selected = dict(select_network(networks, selected_chain))

    if not selected.get("deposit_enabled"):
        raise PermissionError(
            f"Deposits are disabled for {symbol} on {selected['name']}"
        )

    if not selected.get("address_available"):
        raise RuntimeError(
            f"Gate did not return a deposit address for "
            f"{symbol} on {selected['name']}"
        )

    address = str(selected["address"])
    selected["qr_payload"] = address
    selected["qr_svg_data_uri"] = qr_svg_data_uri(address)

    minimum = None
    if isinstance(raw_address, dict):
        minimum = (
            str(raw_address.get("min_deposit_amount") or "").strip()
            or None
        )

    return {
        "account_id": account_id,
        "display_name": display_name,
        "currency": symbol,
        "as_of": utc_now_iso(),
        "source": source,
        "minimum_deposit_amount": minimum,
        "network": selected,
        "warning": (
            f"Send only {symbol} using the {selected['name']} network. "
            "Using another asset or an incompatible network may result "
            "in permanent loss."
        ),
    }


DEMO_CURRENCIES = [
    {
        "currency": "USDT",
        "name": "Tether",
        "chains": [
            {"name": "Base", "deposit_disabled": False},
            {"name": "Ethereum", "deposit_disabled": False},
        ],
    },
    {
        "currency": "EQTY",
        "name": "EQTY",
        "chains": [{"name": "Base", "deposit_disabled": False}],
    },
    {
        "currency": "BTC",
        "name": "Bitcoin",
        "chains": [{"name": "BTC", "deposit_disabled": False}],
    },
    {
        "currency": "ETH",
        "name": "Ethereum",
        "chains": [
            {"name": "Ethereum", "deposit_disabled": False},
            {"name": "Base", "deposit_disabled": False},
        ],
    },
    {
        "currency": "SOL",
        "name": "Solana",
        "chains": [{"name": "Solana", "deposit_disabled": False}],
    },
]


def demo_chains(currency: str) -> list[dict[str, Any]]:
    symbol = normalize_currency_symbol(currency)
    mapping: dict[str, list[dict[str, Any]]] = {
        "USDT": [
            {
                "chain": "BASE",
                "name_en": "Base",
                "contract_address": "0x-demo-usdt",
                "is_deposit_disabled": 0,
            },
            {
                "chain": "ETH",
                "name_en": "Ethereum",
                "contract_address": "0x-demo-usdt",
                "is_deposit_disabled": 0,
            },
        ],
        "EQTY": [
            {
                "chain": "BASE",
                "name_en": "Base",
                "contract_address": "0x-demo-eqty",
                "is_deposit_disabled": 0,
            }
        ],
        "BTC": [
            {
                "chain": "BTC",
                "name_en": "Bitcoin",
                "is_deposit_disabled": 0,
            }
        ],
        "ETH": [
            {
                "chain": "ETH",
                "name_en": "Ethereum",
                "is_deposit_disabled": 0,
            },
            {
                "chain": "BASE",
                "name_en": "Base",
                "is_deposit_disabled": 0,
            },
        ],
        "SOL": [
            {
                "chain": "SOL",
                "name_en": "Solana",
                "is_deposit_disabled": 0,
            }
        ],
    }
    return mapping.get(
        symbol,
        [
            {
                "chain": symbol,
                "name_en": symbol,
                "is_deposit_disabled": 0,
            }
        ],
    )


def demo_address(currency: str) -> dict[str, Any]:
    symbol = normalize_currency_symbol(currency)
    items: list[dict[str, Any]] = []

    for chain in demo_chains(symbol):
        chain_id = str(chain["chain"])

        if chain_id in {"ETH", "BASE"}:
            address = "0x000000000000000000000000000000000000dEaD"
        elif chain_id == "BTC":
            address = "bc1qdemonstrationaddressnotforrealdeposits000"
        elif chain_id == "SOL":
            address = "DemoSolanaAddressNotForRealDeposits111111111"
        else:
            address = f"DEMO-{symbol}-{chain_id}-ADDRESS"

        items.append(
            {
                "chain": chain_id,
                "address": address,
                "obtain_failed": 0,
                "min_confirms": 1,
            }
        )

    return {
        "currency": symbol,
        "address": items[0]["address"],
        "min_deposit_amount": "0",
        "multichain_addresses": items,
    }
