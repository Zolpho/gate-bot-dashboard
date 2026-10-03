from __future__ import annotations

import pytest

from app.donations import (
    DONATION_ACCOUNT_ID,
    DONATION_DISPLAY_NAME,
    DonationProjectionError,
    donation_destination_identity,
    project_public_donation_catalog,
    project_public_donation_details,
    published_destination_state,
)


def _detail(
    *,
    address: str = "0xAbCdEf",
    memo: str | None = None,
    chain: str = "BASE",
) -> dict:
    return {
        "account_id": "eqtydao",
        "display_name": "Internal account name",
        "currency": "USDT",
        "as_of": "2026-10-03T12:00:00+00:00",
        "source": "gate",
        "cache": {
            "hit": False,
            "ttl_seconds": 300,
        },
        "authorized_user": {
            "username": "should-never-leak",
        },
        "raw_gate_response": {
            "secret": "never-public",
        },
        "minimum_deposit_amount": "1",
        "network": {
            "chain": chain,
            "name": "Base",
            "contract_address": "0xToken",
            "deposit_enabled": True,
            "withdraw_enabled": True,
            "address_available": True,
            "address": address,
            "payment_id": memo,
            "payment_name": (
                "Destination Tag"
                if memo
                else None
            ),
            "requires_memo": bool(memo),
            "min_confirmations": 10,
            "qr_svg_data_uri":
                "data:image/svg+xml,SAFE",
            "provider_private":
                "must-not-leak",
        },
        "warning":
            "Send only USDT using Base.",
    }


def test_public_donation_identity_is_fixed() -> None:
    assert DONATION_ACCOUNT_ID == "eqtydao"
    assert (
        DONATION_DISPLAY_NAME
        == "EQTY DAO Market Making"
    )


def test_catalog_projection_is_allowlisted() -> None:
    payload = {
        "source": "gate",
        "cache": {
            "hit": False,
        },
        "provider_private":
            "must-not-leak",
        "favorites": [
            "USDT",
            "EQTY",
        ],
        "as_of":
            "2026-10-03T12:00:00+00:00",
        "currencies": [
            {
                "currency": "USDT",
                "name": "Tether",
                "deposit_available": True,
                "trade_disabled": False,
                "main_chain": "ETH",
                "favorite": True,
                "provider_private":
                    "must-not-leak",
                "chains": [
                    {
                        "chain": "BASE",
                        "name": "Base",
                        "contract_address":
                            "0xToken",
                        "deposit_enabled":
                            True,
                        "withdraw_enabled":
                            True,
                        "requires_memo":
                            False,
                        "decimal": "6",
                        "provider_private":
                            "must-not-leak",
                    }
                ],
            }
        ],
    }

    result = (
        project_public_donation_catalog(
            payload
        )
    )

    assert result["destination"] == {
        "name":
            "EQTY DAO Market Making",
    }

    assert result["count"] == 1
    assert (
        result[
            "deposit_available_count"
        ]
        == 1
    )

    assert result["favorites"] == [
        "USDT"
    ]

    assert "source" not in result
    assert "cache" not in result
    assert (
        "provider_private"
        not in result
    )

    currency = result[
        "currencies"
    ][0]

    assert set(currency) == {
        "currency",
        "name",
        "deposit_available",
        "main_chain",
        "favorite",
        "chains",
    }

    chain = currency["chains"][0]

    assert set(chain) == {
        "chain",
        "name",
        "contract_address",
        "deposit_enabled",
        "requires_memo",
        "decimal",
    }

    assert "withdraw_enabled" not in chain
    assert (
        "provider_private"
        not in chain
    )


def test_detail_projection_strips_private_context() -> None:
    result = (
        project_public_donation_details(
            _detail()
        )
    )

    assert result["destination"] == {
        "name":
            "EQTY DAO Market Making",
    }

    assert result["currency"] == "USDT"

    assert result["network"][
        "address"
    ] == "0xAbCdEf"

    assert result["network"][
        "qr_svg_data_uri"
    ].startswith(
        "data:image/svg+xml"
    )

    serialized = repr(result)

    assert "authorized_user" not in serialized
    assert "should-never-leak" not in serialized
    assert "raw_gate_response" not in serialized
    assert "never-public" not in serialized
    assert "provider_private" not in serialized
    assert "Internal account name" not in serialized
    assert "'account_id'" not in serialized
    assert "'source'" not in serialized
    assert "'cache'" not in serialized
    assert "withdraw_enabled" not in serialized


def test_memo_is_part_of_destination_identity() -> None:
    plain = donation_destination_identity(
        _detail()
    )

    tagged = donation_destination_identity(
        _detail(
            memo="12345"
        )
    )

    assert plain != tagged
    assert tagged.memo == "12345"


def test_evm_address_case_does_not_create_false_change() -> None:
    current = _detail(
        address="0xAbCdEf",
    )

    published = _detail(
        address="0xabcdef",
    )

    assert (
        published_destination_state(
            current,
            [published],
        )
        == "verified"
    )


def test_non_evm_address_remains_case_sensitive() -> None:
    current = _detail(
        address="SOLCaseSensitiveAddress",
        chain="SOL",
    )

    published = _detail(
        address="solcasesensitiveaddress",
        chain="SOL",
    )

    assert (
        published_destination_state(
            current,
            [published],
        )
        == "changed"
    )


@pytest.mark.parametrize(
    (
        "published",
        "expected",
    ),
    [
        (
            [],
            "first_seen",
        ),
        (
            [
                _detail(),
            ],
            "verified",
        ),
        (
            [
                _detail(
                    address="0x1111",
                ),
            ],
            "changed",
        ),
        (
            [
                _detail(
                    address="0x1111",
                ),
                _detail(
                    address="0x2222",
                ),
            ],
            "ambiguous",
        ),
    ],
)
def test_published_destination_states(
    published: list[dict],
    expected: str,
) -> None:
    assert (
        published_destination_state(
            _detail(),
            published,
        )
        == expected
    )


def test_missing_address_fails_closed() -> None:
    payload = _detail()
    payload["network"]["address"] = ""

    with pytest.raises(
        DonationProjectionError,
        match="no address",
    ):
        project_public_donation_details(
            payload
        )
