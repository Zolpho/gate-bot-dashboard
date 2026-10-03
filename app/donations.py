from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .deposits import normalize_currency_symbol


DONATION_ACCOUNT_ID = "eqtydao"
DONATION_DISPLAY_NAME = "EQTY DAO Market Making"


class DonationProjectionError(ValueError):
    """Public donation data cannot be safely projected."""


@dataclass(
    frozen=True,
    slots=True,
)
class DonationDestinationIdentity:
    """
    Security identity of one donation destination.

    Chain matching is normalized because Gate may vary
    presentation punctuation/case.

    EVM addresses are compared case-insensitively.
    Other address formats remain case-sensitive.

    Memo/tag is part of the destination identity.
    """

    currency: str
    chain_key: str
    address_key: str
    memo: str


def _text(value: Any) -> str:
    return str(
        value
        if value is not None
        else ""
    ).strip()


def _chain_key(value: Any) -> str:
    return re.sub(
        r"[^A-Z0-9]",
        "",
        _text(value).upper(),
    )


def _address_key(value: Any) -> str:
    address = _text(value)

    if address.lower().startswith("0x"):
        return address.lower()

    return address


def _network_mapping(
    value: Any,
) -> Mapping[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise DonationProjectionError(
            "Donation network is missing"
        )

    return value


def donation_destination_identity(
    payload: Mapping[str, Any],
) -> DonationDestinationIdentity:
    try:
        currency = normalize_currency_symbol(
            payload.get("currency")
        )
    except ValueError as exc:
        raise DonationProjectionError(
            str(exc)
        ) from exc

    network = _network_mapping(
        payload.get("network")
    )

    chain = _text(
        network.get("chain")
        or network.get("name")
    )

    address = _text(
        network.get("address")
    )

    if not chain:
        raise DonationProjectionError(
            "Donation network has no chain identity"
        )

    if not address:
        raise DonationProjectionError(
            "Donation destination has no address"
        )

    return DonationDestinationIdentity(
        currency=currency,
        chain_key=_chain_key(chain),
        address_key=_address_key(
            address
        ),
        memo=_text(
            network.get("payment_id")
        ),
    )


def _project_catalog_network(
    network: Mapping[str, Any],
) -> dict[str, Any] | None:
    chain = _text(
        network.get("chain")
        or network.get("name")
    )

    if not chain:
        return None

    return {
        "chain": chain,
        "name": (
            _text(network.get("name"))
            or chain
        ),
        "contract_address": (
            _text(
                network.get(
                    "contract_address"
                )
            )
            or None
        ),
        "deposit_enabled": bool(
            network.get(
                "deposit_enabled",
                False,
            )
        ),
        "requires_memo": bool(
            network.get(
                "requires_memo",
                False,
            )
        ),
        "decimal": (
            _text(network.get("decimal"))
            or None
        ),
    }


def project_public_donation_catalog(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Return only fields intentionally safe for anonymous use.

    Provider/debug/cache fields are not copied.
    Withdrawal/trading state is not copied.
    Raw Gate objects are not copied.
    """

    raw_currencies = payload.get(
        "currencies"
    )

    if not isinstance(
        raw_currencies,
        list,
    ):
        raw_currencies = []

    currencies: list[
        dict[str, Any]
    ] = []

    for raw in raw_currencies:
        if not isinstance(
            raw,
            Mapping,
        ):
            continue

        try:
            symbol = (
                normalize_currency_symbol(
                    raw.get("currency")
                )
            )
        except ValueError:
            continue

        raw_chains = raw.get(
            "chains"
        )

        if not isinstance(
            raw_chains,
            list,
        ):
            raw_chains = []

        chains = []

        for raw_chain in raw_chains:
            if not isinstance(
                raw_chain,
                Mapping,
            ):
                continue

            projected = (
                _project_catalog_network(
                    raw_chain
                )
            )

            if projected is not None:
                chains.append(
                    projected
                )

        currencies.append(
            {
                "currency": symbol,
                "name": (
                    _text(
                        raw.get("name")
                    )
                    or symbol
                ),
                "deposit_available": bool(
                    raw.get(
                        "deposit_available",
                        False,
                    )
                ),
                "main_chain": (
                    _text(
                        raw.get(
                            "main_chain"
                        )
                    )
                    or None
                ),
                "favorite": bool(
                    raw.get(
                        "favorite",
                        False,
                    )
                ),
                "chains": chains,
            }
        )

    symbols = {
        item["currency"]
        for item in currencies
    }

    favorites = []

    raw_favorites = payload.get(
        "favorites"
    )

    if isinstance(
        raw_favorites,
        list,
    ):
        for value in raw_favorites:
            try:
                symbol = (
                    normalize_currency_symbol(
                        value
                    )
                )
            except ValueError:
                continue

            if (
                symbol in symbols
                and symbol not in favorites
            ):
                favorites.append(
                    symbol
                )

    return {
        "destination": {
            "name":
                DONATION_DISPLAY_NAME,
        },
        "as_of": (
            _text(payload.get("as_of"))
            or None
        ),
        "favorites": favorites,
        "count": len(currencies),
        "deposit_available_count": sum(
            1
            for item in currencies
            if item[
                "deposit_available"
            ]
        ),
        "currencies": currencies,
    }


def project_public_donation_details(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Sanitize one already-normalized deposit detail object.

    This deliberately does not copy:
      - account_id
      - authorized_user
      - Gate UID
      - provider source/debug fields
      - cache internals
      - raw Gate responses
    """

    identity = (
        donation_destination_identity(
            payload
        )
    )

    network = _network_mapping(
        payload.get("network")
    )

    return {
        "destination": {
            "name":
                DONATION_DISPLAY_NAME,
        },
        "currency":
            identity.currency,
        "as_of": (
            _text(payload.get("as_of"))
            or None
        ),
        "minimum_deposit_amount": (
            _text(
                payload.get(
                    "minimum_deposit_amount"
                )
            )
            or None
        ),
        "network": {
            "chain": _text(
                network.get("chain")
            ),
            "name": (
                _text(
                    network.get("name")
                )
                or _text(
                    network.get(
                        "chain"
                    )
                )
            ),
            "contract_address": (
                _text(
                    network.get(
                        "contract_address"
                    )
                )
                or None
            ),
            "deposit_enabled": bool(
                network.get(
                    "deposit_enabled",
                    False,
                )
            ),
            "address_available": bool(
                network.get(
                    "address_available",
                    bool(
                        _text(
                            network.get(
                                "address"
                            )
                        )
                    ),
                )
            ),
            "address": _text(
                network.get(
                    "address"
                )
            ),
            "payment_id": (
                _text(
                    network.get(
                        "payment_id"
                    )
                )
                or None
            ),
            "payment_name": (
                _text(
                    network.get(
                        "payment_name"
                    )
                )
                or None
            ),
            "requires_memo": bool(
                network.get(
                    "requires_memo",
                    bool(
                        _text(
                            network.get(
                                "payment_id"
                            )
                        )
                    ),
                )
            ),
            "min_confirmations": (
                network.get(
                    "min_confirmations"
                )
            ),
            "qr_svg_data_uri": (
                _text(
                    network.get(
                        "qr_svg_data_uri"
                    )
                )
                or None
            ),
        },
        "warning": (
            _text(
                payload.get(
                    "warning"
                )
            )
            or None
        ),
    }


def published_destination_state(
    current_payload: Mapping[
        str,
        Any,
    ],
    published_payloads: Iterable[
        Mapping[str, Any]
    ],
) -> str:
    """
    Compare the Gate-observed destination with the
    destination(s) already considered published.

    Result:
      first_seen  - nothing is published yet
      verified    - exactly one published identity matches
      changed     - exactly one published identity differs
      ambiguous   - multiple distinct published identities exist

    The later API/DB layer will fail closed for changed
    and ambiguous states.
    """

    current = (
        donation_destination_identity(
            current_payload
        )
    )

    identities = {
        donation_destination_identity(
            item
        )
        for item in published_payloads
    }

    if not identities:
        return "first_seen"

    if len(identities) != 1:
        return "ambiguous"

    published = next(
        iter(identities)
    )

    if published == current:
        return "verified"

    return "changed"
