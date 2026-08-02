from __future__ import annotations

from app.deposits import (
    build_deposit_details,
    merge_deposit_networks,
    normalize_currency_catalog,
)


def test_currency_catalog_and_network_normalization() -> None:
    payload = normalize_currency_catalog(
        [
            {
                "currency": "USDT",
                "name": "Tether",
                "chains": [
                    {"name": "Base", "deposit_disabled": False},
                    {"name": "Ethereum", "deposit_disabled": True},
                ],
            },
            {
                "currency": "OLD",
                "name": "Old",
                "delisted": True,
            },
        ],
        ["USDT", "EQTY"],
    )

    assert payload["count"] == 1
    assert payload["favorites"] == ["USDT"]
    assert payload["currencies"][0]["deposit_available"] is True

    networks = merge_deposit_networks(
        [
            {
                "chain": "BASE",
                "name_en": "Base",
                "is_deposit_disabled": 0,
            },
            {
                "chain": "ETH",
                "name_en": "Ethereum",
                "is_deposit_disabled": 1,
            },
        ],
        {
            "multichain_addresses": [
                {
                    "chain": "BASE",
                    "address": "0xabc",
                    "obtain_failed": 0,
                },
                {
                    "chain": "ETH",
                    "address": "0xdef",
                    "obtain_failed": 0,
                },
            ]
        },
    )

    assert networks[0]["address"] == "0xabc"
    assert networks[0]["deposit_enabled"] is True
    assert networks[1]["deposit_enabled"] is False


def test_build_deposit_details_generates_private_qr() -> None:
    payload = build_deposit_details(
        account_id="zolnode",
        display_name="Zolnode",
        currency="USDT",
        selected_chain="BASE",
        raw_chains=[
            {
                "chain": "BASE",
                "name_en": "Base",
                "is_deposit_disabled": 0,
            }
        ],
        raw_address={
            "currency": "USDT",
            "min_deposit_amount": "1",
            "multichain_addresses": [
                {
                    "chain": "BASE",
                    "address": "0xabc",
                    "obtain_failed": 0,
                }
            ],
        },
    )

    assert payload["account_id"] == "zolnode"
    assert payload["network"]["address"] == "0xabc"
    assert payload["network"]["qr_svg_data_uri"].startswith(
        "data:image/svg+xml"
    )
    assert "USDT" in payload["warning"]
